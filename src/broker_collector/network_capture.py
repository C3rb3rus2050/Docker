"""Passive Auswertung der JSON-Antworten, die die Broker-Webapp selbst lädt.

Es werden KEINE eigenen Anfragen an interne Endpunkte gestellt und KEINE Endpunkte
erfunden. Während der normalen Navigation lädt die Webapp Dokumentlisten (z. B. per
REST oder GraphQL). Diese Antworten werden lokal im Browserprozess mitgelesen und auf
dokumentartige Einträge untersucht. So entsteht eine zweite, unabhängige Sicht auf die
Dokumente, die mit der sichtbaren Oberfläche abgeglichen werden kann.

Die Inhalte verlassen den Rechner nicht; Antworten werden nicht gespeichert, nur die
extrahierten Metadaten (Titel, Datum, Kennung, Download-URL).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from .classifier import parse_date
from .security import UrlPolicy, UrlValidationError, url_without_query, validate_url

log = logging.getLogger(__name__)

URL_KEYS = re.compile(r"(url|href|link|uri|payload|download|file|pdf|location|path)$", re.IGNORECASE)
DOC_URL_KEY_HINT = re.compile(r"(download|document|dokument|pdf|file|attachment|postbox|report|statement)",
                              re.IGNORECASE)
DOC_URL_PATH = re.compile(r"(\.(pdf|csv|zip)(\?|#|$)|/download|/documents?/|/dokumente?/|/postbox|/attachments?/"
                          r"|/files?/)", re.IGNORECASE)
TITLE_KEYS = ("title", "name", "fileName", "filename", "displayName", "documentName", "subject", "label",
              "documentTitle", "description", "type", "documentType", "category")
DATE_KEYS = ("documentDate", "date", "createdAt", "created", "creationDate", "publishedAt", "publicationDate",
             "postboxDate", "timestamp", "valueDate", "bookingDate", "issuedAt", "sentAt", "receivedAt")
ID_KEYS = ("documentId", "docId", "fileId", "id", "uuid", "documentUuid", "postboxId")
DOC_OBJECT_HINT = re.compile(r"(document|dokument|postbox|mailbox|attachment|statement|report|file)",
                             re.IGNORECASE)
MAX_BODY_BYTES = 5 * 1024 * 1024
MAX_DEPTH = 12


@dataclass
class NetworkDocument:
    title: str
    url: str = ""
    external_id: str = ""
    date: str = ""
    origin_url: str = ""  # URL der JSON-Antwort (redigiert gespeichert)
    raw_keys: list[str] = field(default_factory=list)

    @property
    def downloadable(self) -> bool:
        return bool(self.url)


def _to_iso_date(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:  # Millisekunden
            ts /= 1000.0
        if 946684800 <= ts <= 4102444800:  # 2000-01-01 .. 2100-01-01
            return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        return ""
    text = str(value)
    m = re.match(r"^((?:19|20)\d{2}-\d{2}-\d{2})", text)
    if m:
        return parse_date(m.group(1))
    return parse_date(text)


def _first(d: dict[str, Any], keys: Iterable[str]) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, "", [], {}):
            return d[k]
    return None


class NetworkDocumentExtractor:
    def __init__(self, policy: UrlPolicy | None = None):
        self.policy = policy

    def _valid_url(self, value: str) -> bool:
        try:
            validate_url(value, self.policy)
            return True
        except UrlValidationError:
            return False

    def _doc_url_in(self, obj: dict[str, Any]) -> str:
        for key, value in obj.items():
            if isinstance(value, str) and value.startswith("https://") and URL_KEYS.search(key):
                if (DOC_URL_KEY_HINT.search(key) or DOC_URL_PATH.search(value)) and self._valid_url(value):
                    return value
            if isinstance(value, dict) and key.lower() in ("action", "link", "links", "download", "file"):
                nested = self._doc_url_in(value)
                if nested:
                    return nested
        return ""

    def extract(self, payload: Any, origin_url: str = "") -> list[NetworkDocument]:
        results: list[NetworkDocument] = []
        self._walk(payload, origin_url, results, depth=0, parent_key="")
        uniq: dict[str, NetworkDocument] = {}
        for doc in results:
            k = doc.external_id or url_without_query(doc.url) or f"{doc.title}|{doc.date}"
            if k not in uniq:
                uniq[k] = doc
        return list(uniq.values())

    def _walk(self, node: Any, origin: str, out: list[NetworkDocument], depth: int, parent_key: str) -> None:
        if depth > MAX_DEPTH:
            return
        if isinstance(node, list):
            for item in node[:20000]:
                self._walk(item, origin, out, depth + 1, parent_key)
            return
        if not isinstance(node, dict):
            return
        url = self._doc_url_in(node)
        title_val = _first(node, TITLE_KEYS)
        title = str(title_val).strip()[:200] if isinstance(title_val, (str, int, float)) else ""
        context_hint = DOC_OBJECT_HINT.search(parent_key) or DOC_OBJECT_HINT.search(str(node.get("__typename", "")))
        if url:
            out.append(NetworkDocument(
                title=title or url_without_query(url).rsplit("/", 1)[-1], url=url,
                external_id=str(_first(node, ID_KEYS) or ""), date=_to_iso_date(_first(node, DATE_KEYS)),
                origin_url=origin, raw_keys=sorted(node.keys())[:30],
            ))
        elif context_hint and title and _first(node, ID_KEYS) is not None:
            # Dokument-Metadaten ohne direkte URL (z. B. Postfach-Liste) – wichtig für den Abgleich
            out.append(NetworkDocument(
                title=title, external_id=str(_first(node, ID_KEYS)), date=_to_iso_date(_first(node, DATE_KEYS)),
                origin_url=origin, raw_keys=sorted(node.keys())[:30],
            ))
        for key, value in node.items():
            if isinstance(value, (dict, list)):
                self._walk(value, origin, out, depth + 1, key)


class NetworkCapture:
    """Sammelt Response-Objekte im Event-Handler und wertet sie später sicher aus.

    (Im synchronen Playwright-API werden im Handler keine blockierenden Aufrufe gemacht.)
    """

    def __init__(self, policy: UrlPolicy, extractor: NetworkDocumentExtractor | None = None):
        self.policy = policy
        self.extractor = extractor or NetworkDocumentExtractor(policy)
        self._pending: list[Any] = []
        self.documents: dict[str, NetworkDocument] = {}
        self.responses_seen = 0
        self.attached = False

    def attach(self, context: Any) -> None:
        if self.attached:
            return
        context.on("response", self._on_response)
        self.attached = True

    def _on_response(self, response: Any) -> None:
        try:
            ctype = (response.headers or {}).get("content-type", "")
            if "json" not in ctype.lower():
                return
            if not self.policy.host_allowed(re.sub(r"^https?://([^/:]+).*$", r"\1", response.url)):
                return
            self._pending.append(response)
        except Exception:
            pass

    def process_pending(self) -> list[NetworkDocument]:
        """Liest die gesammelten Antworten und liefert neu entdeckte Dokumente."""
        new: list[NetworkDocument] = []
        pending, self._pending = self._pending, []
        for response in pending:
            try:
                body = response.body()
            except Exception:
                continue
            if len(body) > MAX_BODY_BYTES:
                continue
            try:
                payload = json.loads(body.decode("utf-8", errors="replace"))
            except ValueError:
                continue
            self.responses_seen += 1
            for doc in self.extractor.extract(payload, response.url):
                key = doc.external_id or url_without_query(doc.url) or f"{doc.title}|{doc.date}"
                if key not in self.documents:
                    self.documents[key] = doc
                    new.append(doc)
                elif doc.url and not self.documents[key].url:
                    self.documents[key] = doc  # URL nachträglich bekannt geworden
                    new.append(doc)
        return new
