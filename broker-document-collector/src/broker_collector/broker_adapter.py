"""Gemeinsames Interface und Datenmodelle für alle Brokeradapter."""

from __future__ import annotations

import abc
import hashlib
import re
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterator

from .security import url_without_query


# --------------------------------------------------------------------------- #
# Ausnahmen
# --------------------------------------------------------------------------- #


class CollectorError(Exception):
    """Basisklasse."""


class UserActionRequired(CollectorError):
    """Der Benutzer muss im Browser handeln (Login, 2FA, Captcha, erneute Bestätigung)."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason  # login | 2fa | captcha | reconfirm


class SessionExpired(UserActionRequired):
    def __init__(self, message: str = "Die Browsersitzung ist abgelaufen. Bitte im Browser neu anmelden."):
        super().__init__("login", message)


class ScanCancelled(CollectorError):
    """Der Benutzer hat den Scan abgebrochen."""


class DownloadError(CollectorError):
    def __init__(self, message: str, retryable: bool = False, status: str = "failed"):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


class SafetyViolation(CollectorError):
    """Eine Aktion wurde blockiert, weil sie eine Kontoaktion auslösen könnte."""


# --------------------------------------------------------------------------- #
# Datenmodelle
# --------------------------------------------------------------------------- #


class Source(str, Enum):
    UI = "ui"  # sichtbare Browseroberfläche (DOM)
    NETWORK = "network"  # von der Webapp selbst geladene JSON-Antworten (passiv mitgelesen)
    API = "api"  # inoffizielle Schnittstelle (Trade-Republic-WebSocket im Browserkontext)


class AreaStatus(str, Enum):
    PENDING = "pending"
    COMPLETE = "complete"  # vollständig untersucht
    PARTIAL = "partial"  # teilweise untersucht (Limit erreicht / Fehler)
    INACCESSIBLE = "inaccessible"  # nicht zugänglich


@dataclass
class DocumentArea:
    broker: str
    name: str
    url: str = ""
    kind: str = "nav"  # nav | tab | api | network | entry
    source: str = Source.UI.value
    status: str = AreaStatus.PENDING.value
    pages_visited: int = 0
    periods: list[str] = field(default_factory=list)
    note: str = ""
    hint: dict = field(default_factory=dict)  # adapterinterne Navigationshinweise (z. B. Klick-Label)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.name}:{url_without_query(self.url)}"


@dataclass
class DocumentRef:
    """Ein gefundenes Dokument (noch nicht heruntergeladen)."""

    broker: str
    title: str
    source: str = Source.UI.value
    area: str = ""
    url: str = ""  # direkte URL (https oder blob:) – falls bekannt
    external_id: str = ""  # stabile Kennung vom Broker, falls vorhanden
    date: str = ""  # ISO-Datum JJJJ-MM-TT, falls ermittelbar – niemals erfunden
    doc_type_hint: str = ""
    page_url: str = ""  # Quellseite
    # Klick-Download: Adapter merkt sich intern, wie das Element erneut zu finden ist
    locator_hint: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)
    downloadable: bool = True
    not_downloadable_reason: str = ""

    @property
    def key(self) -> str:
        """Stabile Dokumentkennung für Fortsetzung und inkrementelle Synchronisierung."""
        if self.external_id:
            basis = f"id:{self.external_id}"
        elif self.url and not self.url.startswith("blob:"):
            basis = f"url:{url_without_query(self.url)}"
        else:
            basis = f"meta:{self.area}|{normalize_title(self.title)}|{self.date}"
        return f"{self.broker}:{hashlib.sha256(basis.encode('utf-8')).hexdigest()[:32]}"


def normalize_title(title: str) -> str:
    t = (title or "").lower()
    t = re.sub(r"\.(pdf|csv|zip)$", "", t)
    t = re.sub(r"[^a-z0-9äöüß]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


@dataclass
class DownloadedFile:
    data: bytes
    original_name: str
    source_url: str = ""
    content_type: str = ""
    http_status: int | None = None


@dataclass
class ScanStatus:
    broker: str
    state: str = "idle"  # idle | running | paused | waiting_user | finished | failed | cancelled
    message: str = ""
    areas_total: int = 0
    areas_done: int = 0
    documents_found: int = 0
    downloaded: int = 0
    duplicates: int = 0
    failed: int = 0
    skipped_known: int = 0
    current_area: str = ""


# --------------------------------------------------------------------------- #
# Steuerung (Pause / Abbruch) – threadsicher
# --------------------------------------------------------------------------- #


class ScanControl:
    def __init__(self) -> None:
        self._running = threading.Event()
        self._running.set()
        self._cancelled = threading.Event()
        self.user_confirmed = threading.Event()

    def pause(self) -> None:
        self._running.clear()

    def resume(self) -> None:
        self._running.set()

    def cancel(self) -> None:
        self._cancelled.set()
        self._running.set()
        self.user_confirmed.set()

    def reset(self) -> None:
        self._cancelled.clear()
        self._running.set()
        self.user_confirmed.clear()

    @property
    def paused(self) -> bool:
        return not self._running.is_set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def checkpoint(self, on_pause: Callable[[], None] | None = None) -> None:
        """An sicheren Stellen aufrufen: blockiert bei Pause, wirft bei Abbruch."""
        if self._cancelled.is_set():
            raise ScanCancelled("Scan abgebrochen")
        if not self._running.is_set():
            if on_pause:
                on_pause()
            while not self._running.wait(0.25):
                pass
        if self._cancelled.is_set():
            raise ScanCancelled("Scan abgebrochen")


# --------------------------------------------------------------------------- #
# Interface
# --------------------------------------------------------------------------- #


class BrokerAdapter(abc.ABC):
    """Gemeinsames Interface. Jeder Adapter kapselt seine Selektoren und URLs selbst."""

    broker_id: str = ""
    display_name: str = ""

    @abc.abstractmethod
    def connect(self) -> None:
        """Browser/Seite öffnen und zur offiziellen Startseite navigieren."""

    @abc.abstractmethod
    def check_session(self) -> bool:
        """True, wenn eine gültige angemeldete Sitzung erkannt wird.
        Wirft ``UserActionRequired`` bei Captcha/2FA/erneuter Bestätigung."""

    @abc.abstractmethod
    def discover_document_areas(self) -> list[DocumentArea]:
        """Erreichbare Dokumentenbereiche automatisch ermitteln."""

    @abc.abstractmethod
    def discover_documents(self, area: DocumentArea) -> Iterator[DocumentRef]:
        """Alle Dokumente eines Bereichs liefern (inkl. Paginierung/Historie)."""

    @abc.abstractmethod
    def download_document(self, ref: DocumentRef) -> DownloadedFile:
        """Ein Dokument über die angemeldete Browsersitzung laden (Bytes, unverändert)."""

    @abc.abstractmethod
    def paginate_history(self, area: DocumentArea) -> Iterator[int]:
        """Ältere Einträge nachladen; liefert die laufende Seitennummer, bis nichts mehr kommt."""

    @abc.abstractmethod
    def get_scan_status(self) -> ScanStatus:
        ...

    @abc.abstractmethod
    def close(self) -> None:
        ...
