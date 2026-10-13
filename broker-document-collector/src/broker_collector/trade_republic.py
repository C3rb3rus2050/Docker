"""Trade-Republic-Adapter.

Quellen:
1. **UI** (Hauptquelle): sichtbare Webanwendung https://app.traderepublic.com – automatische
   Erkennung von Profil/Dokumente/Aktivität/Transaktionen, Paginierung, Detailansichten.
2. **API** (zweite Quelle, abschaltbar): inoffizielle WebSocket-Schnittstelle der Webapp,
   ausgeführt im angemeldeten Browser (siehe ``tr_api.py``). Liefert Timeline-Einträge und
   deren Dokumente vollständig über Cursor-Paginierung.
3. **Netzwerk** (passiv): von der Webapp selbst geladene JSON-Antworten.

Alle Ergebnisse werden im Scanner per SHA-256, URL-Basis, Kennung und Titel/Datum abgeglichen.

Live-Verifikation: Die Selektor-Heuristiken und das WebSocket-Protokoll konnten ohne
Zugangsdaten nicht gegen das echte Konto geprüft werden (siehe README „Offene Punkte“).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterator

from .broker_adapter import AreaStatus, DocumentArea, DocumentRef, Source
from .security import UrlPolicy, url_without_query
from .tr_api import (
    BrowserWebSocketTransport,
    TRClient,
    TRProtocolError,
    TRSubscriptionError,
    capture_connect_payload,
    extract_documents,
)
from .web_adapter import WebBrokerAdapter

log = logging.getLogger(__name__)


class TradeRepublicAdapter(WebBrokerAdapter):
    broker_id = "trade_republic"
    display_name = "Trade Republic"
    start_url = "https://app.traderepublic.com/"
    app_hosts = ("app.traderepublic.com",)
    # Dokumente liegen laut pytr auf vorab signierten Links eines Trade-Republic-eigenen
    # Speichers (AWS S3). Nur Hosts, deren Name "traderepublic" enthält, werden zugelassen.
    url_policy = UrlPolicy(
        allowed_suffixes=("traderepublic.com",),
        allowed_patterns=(r"[a-z0-9.-]*traderepublic[a-z0-9.-]*\.amazonaws\.com",
                          r"[a-z0-9.-]*traderepublic[a-z0-9.-]*\.cloudfront\.net"),
    )
    login_path_pattern = re.compile(r"^/(login|signin|anmelden)", re.I)
    # In Timeline/Aktivität öffnen Einträge eine Detailansicht mit den zugehörigen Dokumenten.
    expand_area_pattern = re.compile(r"(transaktion|aktivit|timeline|verlauf|historie)", re.I)

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.api_known_events: set[str] = set()  # vom Scanner befüllt (inkrementeller Lauf)
        self.api_stats: dict[str, Any] = {}

    def extra_areas(self) -> list[DocumentArea]:
        areas = []
        if self.settings.trade_republic_websocket:
            areas.append(DocumentArea(self.broker_id, "WebSocket: Transaktionen (timelineTransactions)",
                                      url="wss://api.traderepublic.com#timelineTransactions", kind="api",
                                      source=Source.API.value, hint={"timeline": "timelineTransactions"}))
            areas.append(DocumentArea(self.broker_id, "WebSocket: Aktivitäten/Postfach (timelineActivityLog)",
                                      url="wss://api.traderepublic.com#timelineActivityLog", kind="api",
                                      source=Source.API.value, hint={"timeline": "timelineActivityLog"}))
        return areas

    # ------------------------------------------------------------------ #
    def _client(self) -> TRClient:
        if getattr(self, "_tr_client", None) is not None and self._tr_client.connected:
            return self._tr_client
        if self._host() not in self.app_hosts:
            self._goto(self.start_url)
        payload = capture_connect_payload(self.page)
        self.ensure_session()
        client = TRClient(BrowserWebSocketTransport(self.page), connect_payload=payload,
                          checkpoint=self.control.checkpoint)
        client.connect()
        self._tr_client = client
        return client

    def discover_api_documents(self, area: DocumentArea) -> Iterator[DocumentRef]:
        kind = area.hint.get("timeline", "")
        try:
            client = self._client()
        except (TRProtocolError, ConnectionError, TimeoutError, Exception) as exc:  # noqa: BLE001
            area.status = AreaStatus.INACCESSIBLE.value
            area.note = (f"WebSocket-Quelle nicht verfügbar: {exc}. Der UI-Scan ist davon nicht betroffen. "
                         "Mögliche Ursache: Protokolländerung oder abgelaufene Sitzung.")
            log.warning("Trade-Republic-WebSocket nicht verfügbar: %s", exc)
            return
        events = 0
        details_ok = 0
        details_failed = 0
        complete = True
        try:
            for event in client.iterate_timeline(kind, max_pages=self.settings.max_pages_per_area * 10):
                self.control.checkpoint()
                events += 1
                area.pages_visited = events
                event_id = str(event.get("id") or "")
                if not event_id:
                    continue
                if event_id in self.api_known_events and not self.settings.recheck_old_areas:
                    continue
                try:
                    detail = client.timeline_detail(event_id)
                    details_ok += 1
                except (TRSubscriptionError, TimeoutError) as exc:
                    details_failed += 1
                    log.debug("Detail %s nicht abrufbar: %s", event_id, exc)
                    continue
                docs, unusable = extract_documents(detail, event)
                for d in docs:
                    yield DocumentRef(
                        broker=self.broker_id, title=d.title, source=Source.API.value, area=area.name, url=d.url,
                        external_id=d.doc_id or url_without_query(d.url), date=d.date,
                        doc_type_hint=f"{d.title} {d.event_title} {d.postbox_type}",
                        page_url=self.start_url, extra={"event_id": event_id, "event_title": d.event_title},
                    )
                for u in unusable:
                    yield DocumentRef(broker=self.broker_id, title=u["title"], source=Source.API.value,
                                      area=area.name, date=u.get("date") or "", downloadable=False,
                                      external_id=f"{event_id}:{u['title']}",
                                      not_downloadable_reason=u["reason"], page_url=self.start_url)
                self.api_known_events.add(event_id)
        except (TRProtocolError, ConnectionError, TimeoutError) as exc:
            complete = False
            area.note = f"WebSocket-Abfrage abgebrochen: {exc}"
            self._tr_client = None
        area.status = AreaStatus.COMPLETE.value if complete and not details_failed else AreaStatus.PARTIAL.value
        area.note = (area.note + f" {events} Timeline-Einträge, {details_ok} Details geladen, "
                     f"{details_failed} Details fehlgeschlagen.").strip()
        self.api_stats[kind] = {"events": events, "details_ok": details_ok, "details_failed": details_failed}

    def close(self) -> None:
        client = getattr(self, "_tr_client", None)
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
            self._tr_client = None
        super().close()
