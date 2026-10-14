"""Browserverwaltung (Playwright, sichtbares Chromium mit persistentem Profil je Broker).

- Pro Broker ein eigenes, lokales Browserprofil (separat löschbar).
- Der Benutzer meldet sich selbst im sichtbaren Fenster an (inkl. 2FA/Passkey).
- Cookies/Tokens verlassen den Browserprozess nicht: Downloads laufen über
  ``context.request`` bzw. ``fetch`` innerhalb der Seite – es wird nichts exportiert.
- Alle Playwright-Aufrufe erfolgen in EINEM Thread (Worker), da das synchrone
  Playwright-API nicht threadsicher ist.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from pathlib import Path
from typing import Any

from .broker_adapter import DownloadedFile, DownloadError, UserActionRequired
from .downloader import detect_format, guess_filename_from_headers, is_retryable_http
from .security import UrlPolicy, UrlValidationError, redact_url, validate_url

log = logging.getLogger(__name__)

DOC_CONTENT_TYPES = ("application/pdf", "application/octet-stream", "application/zip", "text/csv",
                     "application/x-pdf", "application/vnd.ms-excel", "application/force-download")

CAPTCHA_HINTS = ("recaptcha", "hcaptcha", "captcha", "challenges.cloudflare.com", "arkoselabs", "funcaptcha",
                 "turnstile")

BLOB_FETCH_JS = r"""
async ([url, maxBytes]) => {
  // Cookies nur an die eigene Herkunft senden – nie an fremde Hosts (z. B. vorab signierte Speicherlinks)
  const sameOrigin = url.startsWith('blob:') || new URL(url, location.href).origin === location.origin;
  const r = await fetch(url, {credentials: sameOrigin ? 'include' : 'omit'});
  const ct = r.headers.get('content-type') || '';
  const cd = r.headers.get('content-disposition') || '';
  const len = parseInt(r.headers.get('content-length') || '0', 10);
  if (len && len > maxBytes) return {error: 'too_large', status: r.status};
  const buf = new Uint8Array(await r.arrayBuffer());
  if (buf.length > maxBytes) return {error: 'too_large', status: r.status};
  let bin = '';
  const chunk = 0x8000;
  for (let i = 0; i < buf.length; i += chunk) bin += String.fromCharCode.apply(null, buf.subarray(i, i + chunk));
  return {status: r.status, ok: r.ok, contentType: ct, contentDisposition: cd, b64: btoa(bin), finalUrl: r.url};
}
"""

SESSION_PROBE_JS = r"""
() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
                        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const q = (s) => Array.from(document.querySelectorAll(s)).filter(vis).length;
  const text = (document.body ? document.body.innerText : '').slice(0, 20000).toLowerCase();
  const all = (document.body ? document.body.textContent : '').slice(0, 200000).toLowerCase();
  return {
    url: location.href,
    passwordInputs: q('input[type=password]'),
    otpInputs: q('input[autocomplete=one-time-code], input[name*=otp i], input[name*=code i][inputmode=numeric]'),
    pinInputs: q('input[inputmode=numeric][maxlength="1"], input[type=tel][maxlength="1"]'),
    // nur sichtbare, ausreichend große Frames – unsichtbare reCAPTCHA/WAF-Frames gibt es auch im angemeldeten Zustand
    captchaFrames: Array.from(document.querySelectorAll('iframe')).filter(f => {
      const r = f.getBoundingClientRect(); return vis(f) && r.width > 60 && r.height > 60; })
      .map(f => f.src || '').filter(Boolean),
    captchaText: /captcha|ich bin kein roboter|i am not a robot|sicherheitsüberprüfung|verify you are human/.test(text),
    logoutPresent: /abmelden|ausloggen|log out|logout|sign out/.test(all),
    reconfirmText: /erneut bestätigen|bitte bestätige|in der app bestätigen|confirm in (the )?app|zwei-faktor|2fa|sms-code|bestätigungscode/.test(text),
    navLinks: q('nav a, [role=navigation] a, nav button'),
    // Anmeldeformular-Felder (Telefonnummer/E-Mail/Benutzername) – typisch für Loginseiten
    loginInputs: q('input[type=tel], input[type=email], input[autocomplete=username], input[autocomplete=email], ' +
                   'input[autocomplete=tel], input[name*=phone i], input[name*=email i]'),
    links: q('a[href]'),
    textLength: text.length,
  };
}
"""


def chromium_executable_from_env() -> str:
    return os.environ.get("BDC_BROWSER_EXECUTABLE", "")


class BrowserManager:
    def __init__(self, profile_root: Path, headless: bool = False, channel: str = "", executable: str = "",
                 download_timeout_s: int = 90, max_bytes: int = 100 * 1024 * 1024):
        self.profile_root = Path(profile_root)
        self.headless = headless
        self.channel = channel
        self.executable = executable or chromium_executable_from_env()
        self.download_timeout_s = download_timeout_s
        self.max_bytes = max_bytes
        self._pw = None
        self._playwright_cm = None
        self.contexts: dict[str, Any] = {}
        self.pages: dict[str, Any] = {}

    # ------------------------------------------------------------------ #
    def _ensure_playwright(self) -> Any:
        if self._pw is None:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("Playwright ist nicht installiert. Bitte install.bat ausführen.") from exc
            self._playwright_cm = sync_playwright()
            self._pw = self._playwright_cm.start()
        return self._pw

    def open(self, broker: str, start_url: str | None = None) -> tuple[Any, Any]:
        """Öffnet (oder reaktiviert) den persistenten Browserkontext eines Brokers."""
        if broker in self.contexts:
            ctx = self.contexts[broker]
            try:
                page = self.pages.get(broker)
                if page is None or page.is_closed():
                    page = ctx.pages[0] if ctx.pages else ctx.new_page()
                    self.pages[broker] = page
                page.bring_to_front()
                return ctx, page
            except Exception:
                self.close(broker)  # Fenster wurde vom Benutzer geschlossen
        pw = self._ensure_playwright()
        profile = self.profile_root / broker
        profile.mkdir(parents=True, exist_ok=True)
        kwargs: dict[str, Any] = dict(
            user_data_dir=str(profile), headless=self.headless, accept_downloads=True, locale="de-DE",
            viewport=None if not self.headless else {"width": 1366, "height": 900},
            args=["--disable-features=Translate", "--no-default-browser-check"],
        )
        if self.channel:
            kwargs["channel"] = self.channel
        if self.executable:
            kwargs["executable_path"] = self.executable
        try:
            ctx = pw.chromium.launch_persistent_context(**kwargs)
        except Exception as exc:
            raise RuntimeError(
                "Chromium konnte nicht gestartet werden. Läuft bereits ein Fenster mit demselben Profil? "
                f"Details: {exc}"
            ) from exc
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        self.contexts[broker] = ctx
        self.pages[broker] = page
        if start_url:
            page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
        return ctx, page

    def close(self, broker: str) -> None:
        ctx = self.contexts.pop(broker, None)
        self.pages.pop(broker, None)
        if ctx is not None:
            try:
                ctx.close()
            except Exception:
                pass

    def close_all(self) -> None:
        for broker in list(self.contexts):
            self.close(broker)
        if self._playwright_cm is not None:
            try:
                self._playwright_cm.__exit__(None, None, None)
            except Exception:
                pass
        self._pw = None
        self._playwright_cm = None

    # ------------------------------------------------------------------ #
    # Sitzungserkennung (heuristisch, ohne Zugangsdaten)
    # ------------------------------------------------------------------ #
    @staticmethod
    def probe_session(page: Any) -> dict[str, Any]:
        try:
            return page.evaluate(SESSION_PROBE_JS)
        except Exception as exc:
            return {"error": str(exc), "url": getattr(page, "url", "")}

    @staticmethod
    def raise_for_user_action(probe: dict[str, Any]) -> None:
        frames = " ".join(probe.get("captchaFrames") or []).lower()
        if probe.get("captchaText") or any(h in frames for h in CAPTCHA_HINTS):
            raise UserActionRequired("captcha", "Die Seite zeigt eine Sicherheitsprüfung (Captcha). "
                                                "Bitte im Browserfenster selbst lösen.")
        # Nur bei sichtbarem Codefeld – ein bloßer Text wie "2FA" (z. B. in Sicherheitshinweisen) reicht nicht.
        if probe.get("otpInputs"):
            raise UserActionRequired("2fa", "Der Broker verlangt eine Bestätigung (2FA/App/SMS). "
                                            "Bitte im Browser bzw. in der App bestätigen.")

    # ------------------------------------------------------------------ #
    # Downloads – alle innerhalb der angemeldeten Browsersitzung
    # ------------------------------------------------------------------ #
    def fetch(self, context: Any, page: Any, url: str, policy: UrlPolicy, referer: str = "") -> DownloadedFile:
        """Lädt eine Dokument-URL über die Browsersitzung. Prüft Host, Status, Größe."""
        try:
            validate_url(url, policy, allow_blob=True)
        except UrlValidationError as exc:
            raise DownloadError(f"URL abgelehnt: {exc}", retryable=False, status="not_downloadable") from exc
        if url.startswith("blob:"):
            return self.fetch_in_page(page, url, policy)
        try:
            headers = {"Referer": referer} if referer else None
            resp = context.request.get(url, timeout=self.download_timeout_s * 1000, max_redirects=5,
                                       headers=headers, fail_on_status_code=False)
        except Exception as exc:
            log.debug("context.request fehlgeschlagen (%s) – versuche fetch() in der Seite", exc)
            return self.fetch_in_page(page, url, policy)
        try:
            final_url = resp.url
            try:
                validate_url(final_url, policy)
            except UrlValidationError as exc:
                raise DownloadError(f"Weiterleitung auf nicht erlaubten Host: {redact_url(final_url)}",
                                    status="not_downloadable") from exc
            status = resp.status
            if status in (401, 403):
                raise DownloadError(f"Keine Berechtigung (HTTP {status}) – Sitzung abgelaufen oder Link ungültig",
                                    retryable=False, status="failed")
            if status >= 400:
                raise DownloadError(f"HTTP {status}", retryable=is_retryable_http(status))
            hdrs = resp.headers
            length = int(hdrs.get("content-length") or 0)
            if length and length > self.max_bytes:
                raise DownloadError(f"Datei zu groß ({length} Bytes)", status="invalid")
            body = resp.body()
            if len(body) > self.max_bytes:
                raise DownloadError(f"Datei zu groß ({len(body)} Bytes)", status="invalid")
            return DownloadedFile(body, guess_filename_from_headers(hdrs, final_url), final_url,
                                  hdrs.get("content-type", ""), status)
        finally:
            try:
                resp.dispose()
            except Exception:
                pass

    def fetch_in_page(self, page: Any, url: str, policy: UrlPolicy) -> DownloadedFile:
        try:
            validate_url(url, policy, allow_blob=True)
        except UrlValidationError as exc:
            raise DownloadError(f"URL abgelehnt: {exc}", status="not_downloadable") from exc
        try:
            res = page.evaluate(BLOB_FETCH_JS, [url, self.max_bytes])
        except Exception as exc:
            raise DownloadError(f"Download im Browser fehlgeschlagen: {exc}", retryable=True) from exc
        if res.get("error") == "too_large":
            raise DownloadError("Datei zu groß", status="invalid")
        status = int(res.get("status") or 0)
        if status in (401, 403):
            raise DownloadError(f"Keine Berechtigung (HTTP {status})")
        if status >= 400:
            raise DownloadError(f"HTTP {status}", retryable=is_retryable_http(status))
        data = base64.b64decode(res.get("b64") or "")
        headers = {"content-disposition": res.get("contentDisposition", ""), "content-type": res.get("contentType", "")}
        return DownloadedFile(data, guess_filename_from_headers(headers, res.get("finalUrl") or url),
                              res.get("finalUrl") or url, res.get("contentType", ""), status or None)

    def capture_click_download(self, context: Any, page: Any, locator: Any, policy: UrlPolicy,
                               timeout_s: float | None = None) -> DownloadedFile:
        """Klickt auf einen (vorab sicherheitsgeprüften) Dokumenteintrag und fängt das Ergebnis ab:
        Download-Ereignis, Popup mit PDF, PDF-Antwort im Netzwerk oder eingebetteter Viewer (blob/iframe)."""
        from .discovery import FIND_EMBEDDED_DOC_JS

        timeout_s = timeout_s or self.download_timeout_s
        captured: dict[str, Any] = {}

        def on_download(d: Any) -> None:
            captured.setdefault("download", d)

        def on_response(r: Any) -> None:
            try:
                ct = (r.headers or {}).get("content-type", "").lower()
                if any(t in ct for t in DOC_CONTENT_TYPES) or r.url.lower().split("?")[0].endswith(".pdf"):
                    captured.setdefault("response", r)
            except Exception:
                pass

        def on_page(p: Any) -> None:
            captured.setdefault("popup", p)
            p.on("download", on_download)
            p.on("response", on_response)

        start_url = page.url
        page.on("download", on_download)
        context.on("response", on_response)
        context.on("page", on_page)
        try:
            locator.click(timeout=10000)
            deadline = time.monotonic() + timeout_s
            embedded_checked_at = 0.0
            while time.monotonic() < deadline:
                page.wait_for_timeout(250)
                if "download" in captured:
                    d = captured["download"]
                    path = d.path()
                    if path is None:
                        raise DownloadError(f"Download abgebrochen: {d.failure()}", retryable=True)
                    size = Path(path).stat().st_size
                    if size > self.max_bytes:
                        raise DownloadError(f"Datei zu groß ({size} Bytes)", status="invalid")
                    data = Path(path).read_bytes()
                    return DownloadedFile(data, d.suggested_filename or "dokument", d.url, "", None)
                if "response" in captured:
                    r = captured["response"]
                    try:
                        r.finished()
                    except Exception:
                        pass
                    body = r.body()
                    if len(body) > self.max_bytes:
                        raise DownloadError("Datei zu groß", status="invalid")
                    if detect_format(body) == "html":
                        # Chromiums integrierter PDF-Viewer ersetzt den Antworttext durch seine eigene
                        # HTML-Hülle → Dokument-URL über die Sitzung erneut laden.
                        return self.fetch(context, page, r.url, policy, referer=start_url)
                    return DownloadedFile(body, guess_filename_from_headers(r.headers, r.url), r.url,
                                          r.headers.get("content-type", ""), r.status)
                now = time.monotonic()
                if now - embedded_checked_at > 1.0:
                    embedded_checked_at = now
                    for target in [captured.get("popup"), page]:
                        if target is None:
                            continue
                        try:
                            urls = target.evaluate(FIND_EMBEDDED_DOC_JS)
                        except Exception:
                            urls = []
                        if target is captured.get("popup") and target.url.lower().split("?")[0].endswith(".pdf"):
                            urls = [target.url, *urls]
                        for u in urls:
                            try:
                                return self.fetch(context, target, u, policy, referer=start_url)
                            except DownloadError as exc:
                                log.debug("Eingebettetes Dokument nicht ladbar: %s", exc)
            raise DownloadError("Kein Download nach Klick erkannt (Zeitlimit)", retryable=True)
        finally:
            page.remove_listener("download", on_download)
            context.remove_listener("response", on_response)
            context.remove_listener("page", on_page)
            popup = captured.get("popup")
            if popup is not None:
                try:
                    popup.close()
                except Exception:
                    pass
