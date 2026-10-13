"""Trade Republic – inoffizielle WebSocket-Schnittstelle (zweite Quelle für den Abgleich).

WICHTIG – Einordnung (siehe README, Abschnitt „API-Verfügbarkeit“):

- Trade Republic bietet KEINE offiziell dokumentierte API zum Abruf von Kontodokumenten.
  Die Open-Banking-Schnittstelle (PSD2) ist für lizenzierte Drittanbieter und keine
  Dokumenten-Download-API.
- Die Webanwendung app.traderepublic.com kommuniziert über ``wss://api.traderepublic.com``.
  Das Protokoll ist nicht offiziell dokumentiert, aber durch das Open-Source-Projekt
  *pytr* (MIT-Lizenz) öffentlich beschrieben. Es kann sich jederzeit ändern.
- Dieses Modul nutzt die Schnittstelle ausschließlich **innerhalb des vom Benutzer selbst
  angemeldeten Browsers**: Der WebSocket wird in der Seite von app.traderepublic.com
  geöffnet, der Browser authentifiziert ihn mit seinen eigenen Cookies. Das Tool sieht,
  speichert oder exportiert keine Cookies/Tokens, fragt keine Telefonnummer/PIN ab und
  umgeht keine Sicherheitsmechanismen. Es werden ausschließlich lesende Abonnements
  (Timeline, Timeline-Details) verwendet – keine Orders, keine Kontoänderungen.
- Die Ergebnisse dienen als zweite Quelle und werden mit der sichtbaren Oberfläche
  abgeglichen. Ein Ausfall dieser Quelle beeinträchtigt den UI-Scan nicht.

Protokoll (laut pytr):
  ``connect 31 {json}`` → Antwort ``connected``
  ``sub <id> {json}``   → Antworten ``<id> A {json}`` (vollständig), ``<id> D <delta>``
                           (Änderung ggü. letzter Antwort), ``<id> C`` (beendet), ``<id> E {json}`` (Fehler)
  ``unsub <id>``
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Protocol

from .classifier import parse_date

log = logging.getLogger(__name__)

TR_WS_URL = "wss://api.traderepublic.com"
CONNECT_ID = 31
DEFAULT_CONNECT_PAYLOAD = {
    "locale": "de",
    "platformId": "webtrading",
    "platformVersion": "chrome - 120.0.0",
    "clientId": "app.traderepublic.com",
    "clientVersion": "5582",
}
# Nur lesende Abonnement-Typen sind erlaubt (Whitelist).
ALLOWED_SUB_TYPES = frozenset({"timelineTransactions", "timelineActivityLog", "timelineDetailV2"})


class TRProtocolError(Exception):
    pass


class TRSubscriptionError(TRProtocolError):
    def __init__(self, payload: Any):
        super().__init__(f"Fehlerantwort: {payload}")
        self.payload = payload


class Transport(Protocol):
    def open(self) -> None: ...
    def send(self, message: str) -> None: ...
    def recv(self, timeout_s: float) -> str | None: ...
    def close(self) -> None: ...


# --------------------------------------------------------------------------- #
# Protokoll (rein, ohne I/O – vollständig testbar)
# --------------------------------------------------------------------------- #


def build_connect(payload: dict[str, Any] | None = None) -> str:
    return f"connect {CONNECT_ID} {json.dumps(payload or DEFAULT_CONNECT_PAYLOAD)}"


def build_sub(sub_id: int, payload: dict[str, Any]) -> str:
    if payload.get("type") not in ALLOWED_SUB_TYPES:
        raise TRProtocolError(f"Abonnement-Typ nicht erlaubt (nur lesend): {payload.get('type')}")
    return f"sub {sub_id} {json.dumps(payload)}"


def build_unsub(sub_id: int) -> str:
    return f"unsub {sub_id}"


def parse_message(message: str) -> tuple[int | None, str, str]:
    """Zerlegt eine Servernachricht in (Abo-ID, Code, Nutzlast)."""
    if message == "connected":
        return None, "connected", ""
    parts = message.split(" ", 2)
    if len(parts) < 2:
        raise TRProtocolError(f"Unerwartete Nachricht: {message[:80]!r}")
    try:
        sub_id = int(parts[0])
    except ValueError as exc:
        raise TRProtocolError(f"Unerwartete Nachricht: {message[:80]!r}") from exc
    code = parts[1]
    payload = parts[2] if len(parts) > 2 else ""
    return sub_id, code, payload


def apply_delta(previous: str, delta: str) -> str:
    """Wendet ein Delta an: ``+text`` einfügen (URL-kodiert), ``=N`` N Zeichen übernehmen,
    ``-N`` N Zeichen überspringen. Felder sind durch Tabulatoren getrennt."""
    i = 0
    out: list[str] = []
    for diff in delta.split("\t"):
        if not diff:
            continue
        sign = diff[0]
        if sign == "+":
            out.append(urllib.parse.unquote_plus(diff[1:]).strip())
        elif sign in "=-":
            n = int(diff[1:])
            if sign == "=":
                out.append(previous[i:i + n])
            i += n
        else:
            raise TRProtocolError(f"Unbekanntes Delta-Feld: {diff[:20]!r}")
    return "".join(out)


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #


class TRClient:
    def __init__(self, transport: Transport, connect_payload: dict[str, Any] | None = None,
                 timeout_s: float = 20.0, delay_s: float = 0.15, sleep: Callable[[float], None] = time.sleep,
                 checkpoint: Callable[[], None] = lambda: None):
        self.transport = transport
        self.connect_payload = connect_payload
        self.timeout_s = timeout_s
        self.delay_s = delay_s
        self.sleep = sleep
        self.checkpoint = checkpoint
        self._next_id = 1
        self._previous: dict[int, str] = {}
        self.connected = False
        self.subscriptions_sent = 0

    def connect(self) -> None:
        self.transport.open()
        self.transport.send(build_connect(self.connect_payload))
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            msg = self.transport.recv(1.0)
            if msg is None:
                continue
            if msg == "connected":
                self.connected = True
                return
        raise TRProtocolError("Keine 'connected'-Antwort erhalten (Sitzung abgelaufen oder Protokoll geändert)")

    def close(self) -> None:
        try:
            self.transport.close()
        finally:
            self.connected = False

    def request(self, payload: dict[str, Any]) -> Any:
        """Abonniert, wartet auf die erste vollständige Antwort und beendet das Abo wieder."""
        self.checkpoint()
        sub_id = self._next_id
        self._next_id += 1
        self.transport.send(build_sub(sub_id, payload))
        self.subscriptions_sent += 1
        try:
            deadline = time.monotonic() + self.timeout_s
            while time.monotonic() < deadline:
                msg = self.transport.recv(1.0)
                if msg is None:
                    continue
                if msg == "connected":
                    continue
                mid, code, body = parse_message(msg)
                if mid != sub_id:
                    continue  # Nachricht eines früheren Abos
                if code == "A":
                    self._previous[sub_id] = body
                    return json.loads(body)
                if code == "D":
                    body = apply_delta(self._previous.get(sub_id, ""), body)
                    self._previous[sub_id] = body
                    return json.loads(body)
                if code == "E":
                    raise TRSubscriptionError(json.loads(body) if body.startswith(("{", "[")) else body)
                if code == "C":
                    raise TRProtocolError("Abonnement ohne Antwort beendet")
            raise TimeoutError(f"Keine Antwort auf {payload.get('type')}")
        finally:
            try:
                self.transport.send(build_unsub(sub_id))
            except Exception:
                pass
            self._previous.pop(sub_id, None)
            if self.delay_s:
                self.sleep(self.delay_s)

    def iterate_timeline(self, kind: str, max_pages: int = 1000) -> Iterator[dict[str, Any]]:
        """Alle Einträge einer Timeline (Cursor-Paginierung über ``after``)."""
        after: str | None = None
        seen_cursors: set[str] = set()
        for _ in range(max_pages):
            payload: dict[str, Any] = {"type": kind}
            if after:
                payload["after"] = after
            data = self.request(payload)
            items = data.get("items") or [] if isinstance(data, dict) else []
            for item in items:
                if isinstance(item, dict):
                    yield item
            cursors = data.get("cursors") or {} if isinstance(data, dict) else {}
            nxt = cursors.get("after")
            if not nxt or nxt in seen_cursors or not items:
                return
            seen_cursors.add(nxt)
            after = nxt

    def timeline_detail(self, item_id: str) -> Any:
        return self.request({"type": "timelineDetailV2", "id": item_id})


# --------------------------------------------------------------------------- #
# Dokumente aus Timeline-Details extrahieren
# --------------------------------------------------------------------------- #


@dataclass
class TRDocument:
    title: str
    url: str
    doc_id: str = ""
    event_id: str = ""
    event_title: str = ""
    date: str = ""
    postbox_type: str = ""
    detail: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


def _event_date(event: dict[str, Any]) -> str:
    ts = event.get("timestamp") or event.get("date") or ""
    if isinstance(ts, str) and len(ts) >= 10:
        return parse_date(ts[:10])
    return ""


def extract_documents(detail: Any, event: dict[str, Any]) -> tuple[list[TRDocument], list[dict[str, Any]]]:
    """Liefert (herunterladbare Dokumente, nicht nutzbare Einträge) aus einer timelineDetailV2-Antwort."""
    docs: list[TRDocument] = []
    unusable: list[dict[str, Any]] = []
    if not isinstance(detail, dict):
        return docs, unusable
    for section in detail.get("sections") or []:
        if not isinstance(section, dict) or section.get("type") != "documents":
            continue
        for doc in section.get("data") or []:
            if not isinstance(doc, dict):
                continue
            action = doc.get("action") or {}
            payload = action.get("payload") if isinstance(action, dict) else None
            title = str(doc.get("title") or "Dokument")
            # Datum: zuerst aus dem Dokument selbst (detail enthält oft das Dokumentdatum), sonst Ereignisdatum
            date = parse_date(str(doc.get("detail") or "")) or _event_date(event)
            if isinstance(payload, str) and payload.startswith("https://"):
                docs.append(TRDocument(
                    title=title, url=payload, doc_id=str(doc.get("id") or ""), event_id=str(event.get("id") or ""),
                    event_title=str(event.get("title") or ""), date=date,
                    postbox_type=str(doc.get("postboxType") or ""), detail=str(doc.get("detail") or ""),
                ))
            else:
                unusable.append({"title": title, "event_id": event.get("id"), "date": date,
                                 "reason": "Keine direkte Dokument-URL (Format unbekannt)"})
    return docs, unusable


# --------------------------------------------------------------------------- #
# Transport im angemeldeten Browser (Cookies bleiben im Browser)
# --------------------------------------------------------------------------- #

WS_INSTALL_JS = r"""
(url) => new Promise((resolve, reject) => {
  if (window.__bdcWs && window.__bdcWs.readyState === 1) { resolve(true); return; }
  window.__bdcInbox = [];
  const ws = new WebSocket(url);
  window.__bdcWs = ws;
  ws.onmessage = (ev) => { if (typeof ev.data === 'string') window.__bdcInbox.push(ev.data); };
  ws.onclose = () => { window.__bdcInbox.push('__closed__'); };
  ws.onopen = () => resolve(true);
  ws.onerror = () => reject(new Error('WebSocket-Verbindung fehlgeschlagen'));
  setTimeout(() => reject(new Error('WebSocket-Zeitlimit')), 15000);
})
"""
WS_SEND_JS = "(m) => { window.__bdcWs.send(m); return true; }"
WS_DRAIN_JS = "() => { const a = window.__bdcInbox || []; window.__bdcInbox = []; return a; }"
WS_CLOSE_JS = "() => { try { window.__bdcWs && window.__bdcWs.close(); } catch (e) {} window.__bdcWs = null; return true; }"


class BrowserWebSocketTransport:
    """Öffnet den WebSocket in der Seite von app.traderepublic.com (Origin der echten Webapp)."""

    def __init__(self, page: Any, url: str = TR_WS_URL):
        self.page = page
        self.url = url
        self._buffer: list[str] = []

    def open(self) -> None:
        self.page.evaluate(WS_INSTALL_JS, self.url)

    def send(self, message: str) -> None:
        self.page.evaluate(WS_SEND_JS, message)

    def recv(self, timeout_s: float) -> str | None:
        deadline = time.monotonic() + timeout_s
        while True:
            if self._buffer:
                msg = self._buffer.pop(0)
                if msg == "__closed__":
                    raise ConnectionError("WebSocket wurde geschlossen (Sitzung abgelaufen?)")
                return msg
            self._buffer.extend(self.page.evaluate(WS_DRAIN_JS))
            if self._buffer:
                continue
            if time.monotonic() >= deadline:
                return None
            self.page.wait_for_timeout(50)

    def close(self) -> None:
        try:
            self.page.evaluate(WS_CLOSE_JS)
        except Exception:
            pass


def capture_connect_payload(page: Any, wait_ms: int = 4000) -> dict[str, Any] | None:
    """Liest passiv die connect-Nachricht der echten Webapp mit, um denselben Handshake zu
    verwenden (statt veralteter Versionsangaben). Es werden nur Plattform-/Versionsfelder
    übernommen – keine Tokens."""
    found: dict[str, Any] = {}

    def on_ws(ws: Any) -> None:
        if not ws.url.startswith(TR_WS_URL):
            return

        def on_sent(frame: Any) -> None:
            text = frame if isinstance(frame, str) else getattr(frame, "payload", "")
            if isinstance(text, str) and text.startswith("connect ") and "payload" not in found:
                try:
                    data = json.loads(text.split(" ", 2)[2])
                    found["payload"] = {k: v for k, v in data.items()
                                        if k in ("locale", "platformId", "platformVersion", "clientId",
                                                 "clientVersion")}
                except Exception:
                    pass

        ws.on("framesent", on_sent)

    page.on("websocket", on_ws)
    try:
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(wait_ms)
    except Exception:
        pass
    finally:
        page.remove_listener("websocket", on_ws)
    return found.get("payload")
