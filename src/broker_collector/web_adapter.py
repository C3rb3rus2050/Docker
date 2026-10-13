"""Generischer Webadapter: gemeinsame Logik für Broker-Webapps auf Basis von DomDiscovery.

Die konkreten Adapter (Trade Republic, Scalable Capital) liefern nur ihre eigene
Konfiguration (offizielle Start-URL, erlaubte Hosts, Login-Erkennung, Schlüsselwörter)
und optional zusätzliche Quellen.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Iterator
from urllib.parse import urlsplit

from .broker_adapter import (
    AreaStatus,
    BrokerAdapter,
    DocumentArea,
    DocumentRef,
    DownloadedFile,
    DownloadError,
    ScanControl,
    ScanStatus,
    SessionExpired,
    Source,
    UserActionRequired,
)
from .browser_manager import BrowserManager
from .config import Settings
from .discovery import (
    DiscoveryLimits,
    DomDiscovery,
    Element,
    PageScanState,
    document_candidates,
    expandable_entries,
    manual_request_candidates,
    navigation_candidates,
)
from .network_capture import NetworkCapture
from .security import UrlPolicy, UrlValidationError, url_without_query, validate_url

log = logging.getLogger(__name__)


class WebBrokerAdapter(BrokerAdapter):
    # ---- von Unterklassen zu setzen ------------------------------------ #
    start_url: str = ""
    url_policy: UrlPolicy = UrlPolicy(())
    login_path_pattern: re.Pattern[str] = re.compile(r"(login|signin|sign-in|anmelden|auth|/u/)", re.I)
    app_hosts: tuple[str, ...] = ()  # Hosts der angemeldeten Webapp
    entry_urls: tuple[tuple[str, str], ...] = ()  # (Name, URL) zusätzliche bekannte Einstiege
    expand_area_pattern: re.Pattern[str] | None = None  # Bereiche, deren Einträge Details mit Dokumenten öffnen
    entry_pattern: re.Pattern[str] | None = None

    def __init__(self, browser: BrowserManager, settings: Settings, control: ScanControl | None = None,
                 on_status: Callable[[ScanStatus], None] | None = None):
        self.browser = browser
        self.settings = settings
        self.control = control or ScanControl()
        self.on_status = on_status
        self.status = ScanStatus(self.broker_id)
        self.context: Any = None
        self.page: Any = None
        extra_hosts = tuple(h.strip() for h in getattr(settings, "extra_document_hosts", "").split(",") if h.strip())
        if extra_hosts:
            self.url_policy = UrlPolicy(self.url_policy.allowed_suffixes + extra_hosts, self.url_policy.allowed_patterns)
        self.network = NetworkCapture(self.url_policy)
        self.limits = DiscoveryLimits(
            max_pages=settings.max_pages_per_area, max_load_more=settings.max_load_more_clicks,
            max_items=settings.max_items_per_area, max_areas=settings.max_areas,
            action_delay_ms=settings.action_delay_ms,
        )
        self.dom: DomDiscovery | None = None
        self._emitted_network: set[str] = set()
        self._list_url = ""

    # ------------------------------------------------------------------ #
    def _update(self, **kw: Any) -> None:
        for k, v in kw.items():
            setattr(self.status, k, v)
        if self.on_status:
            self.on_status(self.status)

    def connect(self) -> None:
        self.context, self.page = self.browser.open(self.broker_id)
        if not self.page.url or self.page.url.startswith(("about:", "chrome:", "data:")):
            self.page.goto(self.start_url, wait_until="domcontentloaded", timeout=60000)
        if self.settings.network_capture:
            self.network.attach(self.context)
        self.dom = DomDiscovery(self.page, self.limits, self.control.checkpoint)

    def _host(self) -> str:
        try:
            return (urlsplit(self.page.url).hostname or "").lower()
        except Exception:
            return ""

    def is_logged_in(self, probe: dict[str, Any]) -> bool:
        """Heuristik – Unterklassen können verfeinern."""
        url = probe.get("url", "")
        host = (urlsplit(url).hostname or "").lower()
        if not any(host == h or host.endswith("." + h) for h in self.app_hosts):
            return False
        path = urlsplit(url).path
        if self.login_path_pattern.search(path):
            return False
        if probe.get("passwordInputs") or probe.get("pinInputs"):
            return False
        return bool(probe.get("logoutPresent") or probe.get("navLinks", 0) >= 3)

    def check_session(self) -> bool:
        if self.page is None:
            return False
        probe = self.browser.probe_session(self.page)
        if probe.get("error"):
            return False
        self.browser.raise_for_user_action(probe)
        return self.is_logged_in(probe)

    def ensure_session(self) -> None:
        try:
            ok = self.check_session()
        except UserActionRequired:
            raise
        if not ok:
            raise SessionExpired()

    def wait_for_login(self, timeout_s: int, on_wait: Callable[[str], None] | None = None) -> bool:
        """Wartet, bis der Benutzer sich im Browser angemeldet hat. Keine Eingabe durch das Tool."""
        import time

        deadline = time.monotonic() + timeout_s
        last_msg = ""
        while time.monotonic() < deadline:
            self.control.checkpoint()
            try:
                if self.check_session():
                    return True
                msg = f"Bitte im Browserfenster bei {self.display_name} anmelden (inkl. 2FA)."
            except UserActionRequired as exc:
                msg = str(exc)
            if msg != last_msg and on_wait:
                on_wait(msg)
                last_msg = msg
            try:
                self.page.wait_for_timeout(2000)
            except Exception:
                # Benutzer hat das Fenster geschlossen → neu öffnen
                self.connect()
        return False

    # ------------------------------------------------------------------ #
    # Bereiche
    # ------------------------------------------------------------------ #
    def _goto(self, url: str) -> None:
        validate_url(url, self.url_policy)
        self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        assert self.dom is not None
        self.dom.settle()

    def _go_home(self) -> None:
        if self._host() not in self.app_hosts:
            self._goto(self.start_url)

    def _area_from_element(self, el: Element, kind: str, from_url: str) -> DocumentArea | None:
        url = ""
        if el.href and not el.href.startswith(("#", "javascript")) and not el.href.endswith("#"):
            try:
                validate_url(el.href, self.url_policy)
                url = el.href
            except UrlValidationError:
                return None  # Link führt aus dem Brokerkonto heraus → ignorieren
        return DocumentArea(self.broker_id, el.label[:80], url=url or from_url, kind=kind,
                            hint={"click_label": "" if url else el.label, "from_url": from_url})

    def discover_document_areas(self) -> list[DocumentArea]:
        assert self.dom is not None
        self.ensure_session()
        self._go_home()
        self.dom.settle()
        home = self.page.url
        areas: dict[str, DocumentArea] = {}

        for el in navigation_candidates(self.dom.snapshot()):
            area = self._area_from_element(el, "nav", home)
            if area and area.key not in areas:
                areas[area.key] = area
        for name, url in self.entry_urls:
            a = DocumentArea(self.broker_id, name, url=url, kind="entry")
            areas.setdefault(a.key, a)

        # Zweite Ebene: Unterbereiche (Tabs, Untermenüs) innerhalb der gefundenen Bereiche
        for area in list(areas.values())[: self.limits.max_areas]:
            self.control.checkpoint()
            try:
                self._open_area(area)
            except Exception as exc:
                area.status = AreaStatus.INACCESSIBLE.value
                area.note = f"Nicht erreichbar: {exc}"
                continue
            for el in navigation_candidates(self.dom.snapshot()):
                sub = self._area_from_element(el, "tab", self.page.url)
                if sub and sub.key not in areas and len(areas) < self.limits.max_areas:
                    sub.name = f"{area.name} › {sub.name}"
                    areas[sub.key] = sub
        result = list(areas.values())
        result.extend(self.extra_areas())
        if self.settings.network_capture:
            result.append(DocumentArea(self.broker_id, "Webapp-Datenantworten (passiv)", kind="network",
                                       source=Source.NETWORK.value))
        self._update(areas_total=len(result))
        return result

    def extra_areas(self) -> list[DocumentArea]:
        """Zusätzliche Quellen der Unterklasse (z. B. Trade-Republic-WebSocket)."""
        return []

    def _open_area(self, area: DocumentArea) -> None:
        assert self.dom is not None
        self.ensure_session()
        if area.hint.get("click_label"):
            from_url = area.hint.get("from_url") or self.start_url
            if url_without_query(self.page.url) != url_without_query(from_url):
                self._goto(from_url)
            el = self.dom.find_by_label(area.hint["click_label"])
            if el is None:
                raise DownloadError("Navigationselement nicht mehr gefunden (Seite geändert?)")
            self.dom.click(el)
            self.dom.settle()
        else:
            self._goto(area.url)
        self.ensure_session()

    # ------------------------------------------------------------------ #
    # Dokumente
    # ------------------------------------------------------------------ #
    def _ref_from_candidate(self, cand: Any, area: DocumentArea, extra_hint: dict | None = None) -> DocumentRef:
        hint = {"label": cand.element.label if cand.element else "", **(extra_hint or {})}
        return DocumentRef(
            broker=self.broker_id, title=cand.title, source=Source.UI.value, area=area.name,
            url=cand.href, date=cand.date, page_url=self.page.url, locator_hint=hint,
        )

    def _network_refs(self, area_name: str) -> Iterator[DocumentRef]:
        self.network.process_pending()
        for key, doc in list(self.network.documents.items()):
            emit_key = f"{key}|{bool(doc.url)}"
            if emit_key in self._emitted_network:
                continue
            self._emitted_network.add(emit_key)
            yield DocumentRef(
                broker=self.broker_id, title=doc.title, source=Source.NETWORK.value, area=area_name, url=doc.url,
                external_id=doc.external_id, date=doc.date, page_url=doc.origin_url,
                downloadable=bool(doc.url),
                not_downloadable_reason="" if doc.url else "Nur Metadaten in der Webapp-Antwort (keine Download-URL)",
            )

    def discover_documents(self, area: DocumentArea) -> Iterator[DocumentRef]:
        assert self.dom is not None
        self._update(current_area=area.name)
        if area.kind == "network":
            yield from self._network_refs(area.name)
            area.status = AreaStatus.COMPLETE.value if self.network.responses_seen else AreaStatus.PARTIAL.value
            area.note = f"{self.network.responses_seen} JSON-Antworten der Webapp ausgewertet"
            return
        if area.kind == "api":
            yield from self.discover_api_documents(area)
            return

        self._open_area(area)
        self._list_url = self.page.url
        periods = self.dom.detect_periods()
        area.periods = [p["label"] for p in periods]
        runs: list[dict[str, str] | None] = [None] + periods
        all_exhausted = True
        expand = bool(self.expand_area_pattern and self.expand_area_pattern.search(area.name))
        manual_seen: set[str] = set()
        area_seen: set[str] = set()  # über alle Zeiträume hinweg – keine doppelten Meldungen
        for period in runs:
            self.control.checkpoint()
            if period is not None:
                if not self.dom.apply_period(period):
                    all_exhausted = False
                    area.note += f" Zeitraum {period['label']} nicht auswählbar."
                    continue
            state = PageScanState()
            for elements in self.dom.iterate_pages(state):
                self.control.checkpoint()
                for cand in document_candidates(elements):
                    key = cand.href or f"t:{cand.title}"
                    if key in state.seen:
                        continue
                    state.seen.add(key)
                    if key in area_seen:
                        continue
                    area_seen.add(key)
                    yield self._ref_from_candidate(cand, area)
                for el in manual_request_candidates(elements):
                    if el.label not in manual_seen:
                        manual_seen.add(el.label)
                        yield DocumentRef(self.broker_id, title=el.context or el.label, area=area.name,
                                          page_url=self.page.url, downloadable=False,
                                          not_downloadable_reason="Nur manuell anforderbar (keine automatische "
                                                                  "Anforderung durch das Tool)")
                if expand:
                    yield from self._expand_entries(area, elements, state)
                if self.settings.network_capture:
                    self.network.process_pending()
            area.pages_visited += state.pages
            if not state.exhausted:
                all_exhausted = False
            if state.limit_hit:
                area.note += " Limit erreicht – Bereich nur teilweise untersucht."
        area.status = AreaStatus.COMPLETE.value if all_exhausted else AreaStatus.PARTIAL.value

    def _expand_entries(self, area: DocumentArea, elements: list[Element], state: PageScanState) -> Iterator[DocumentRef]:
        assert self.dom is not None
        base_keys = {c.href or c.title for c in document_candidates(elements)}
        for entry in expandable_entries(elements, self.entry_pattern):
            ekey = f"e:{entry.label}"
            if ekey in state.seen:
                continue
            state.seen.add(ekey)
            self.control.checkpoint()
            el = self.dom.find_by_label(entry.label)
            if el is None:
                continue
            before_url = self.page.url
            try:
                self.dom.click(el)
                self.dom.settle()
                for cand in document_candidates(self.dom.snapshot(), exclude_nav=False):
                    k = cand.href or cand.title
                    if k in base_keys or f"x:{entry.label}:{k}" in state.seen:
                        continue
                    state.seen.add(f"x:{entry.label}:{k}")
                    ref = self._ref_from_candidate(cand, area, {"expand_label": entry.label})
                    if not ref.date:
                        from .classifier import parse_date

                        ref.date = parse_date(entry.label)
                    yield ref
            finally:
                if self.page.url != before_url:
                    self.page.go_back(wait_until="domcontentloaded")
                    self.dom.settle()
                else:
                    self.dom.close_overlays()

    def discover_api_documents(self, area: DocumentArea) -> Iterator[DocumentRef]:
        return iter(())

    def paginate_history(self, area: DocumentArea) -> Iterator[int]:
        assert self.dom is not None
        state = PageScanState()
        while self.dom.pagination_step(state):
            yield state.pages

    def download_document(self, ref: DocumentRef) -> DownloadedFile:
        if not ref.downloadable:
            raise DownloadError(ref.not_downloadable_reason or "Nicht herunterladbar", status="not_downloadable")
        if ref.url:
            return self.browser.fetch(self.context, self.page, ref.url, self.url_policy, referer=ref.page_url)
        assert self.dom is not None
        label = ref.locator_hint.get("label", "")
        el = self.dom.find_by_label(label, lambda e: e.safe_to_click() and not e.has_clickable_child)
        if el is None:
            raise DownloadError("Dokumenteintrag auf der Seite nicht mehr auffindbar", retryable=False)
        if not el.safe_to_click():
            raise DownloadError("Klick aus Sicherheitsgründen blockiert", status="not_downloadable")
        before = self.page.url
        try:
            return self.browser.capture_click_download(self.context, self.page,
                                                       self.page.locator(el.selector).first, self.url_policy)
        finally:
            if self.page.url != before:
                try:
                    self.page.go_back(wait_until="domcontentloaded")
                    self.dom.settle()
                except Exception:
                    pass
            self.dom.close_overlays()

    def get_scan_status(self) -> ScanStatus:
        return self.status

    def close(self) -> None:
        self.browser.close(self.broker_id)
        self.context = None
        self.page = None
