"""Scan-Orchestrierung: Bereiche → Dokumente → Download → Speicherung → Bericht.

``Collector`` ist synchron und ohne Threads testbar (mit Fake-Adaptern).
``ScanManager`` führt alle Browseraktionen in genau einem Worker-Thread aus, damit die
Oberfläche während laufender Scans bedienbar bleibt.

Modi:
- ``full``:   alle Bereiche, auch bekannte Dokumente erneut laden (Duplikate per SHA-256 erkannt)
- ``sync``:   inkrementell – bekannte Dokumente überspringen, fehlgeschlagene erneut versuchen
- ``resume``: wie ``sync``, zusätzlich werden Bereiche übersprungen, die im unterbrochenen Lauf
              bereits vollständig untersucht wurden
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any, Callable

from .broker_adapter import (
    AreaStatus,
    BrokerAdapter,
    DocumentRef,
    DownloadError,
    ScanCancelled,
    ScanControl,
    ScanStatus,
    UserActionRequired,
)
from .classifier import Classifier
from .config import Settings
from .database import ITEM_FINAL_OK, Database
from .downloader import DocumentStore, FileValidationError, retry_call
from .reporting import write_report
from .security import redact, url_without_query

log = logging.getLogger(__name__)

MODES = ("full", "sync", "resume")
BROKERS = ("trade_republic", "scalable_capital")


class Collector:
    def __init__(self, settings: Settings, db: Database, control: ScanControl | None = None,
                 on_event: Callable[[str, dict[str, Any]], None] | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.settings = settings
        self.db = db
        self.control = control or ScanControl()
        self.on_event = on_event or (lambda kind, data: None)
        self.sleep = sleep
        self.classifier = Classifier(settings.pdf_text_extraction, settings.ocr_enabled, settings.tesseract_cmd)
        self.store = DocumentStore(settings.output_dir, db, self.classifier, settings.max_download_bytes)
        self.status: ScanStatus | None = None
        self.last_report: dict[str, str] = {}

    # ------------------------------------------------------------------ #
    def _emit(self, kind: str, **data: Any) -> None:
        try:
            self.on_event(kind, data)
        except Exception:  # pragma: no cover - UI-Fehler dürfen den Scan nicht stören
            log.debug("Event-Handler-Fehler", exc_info=True)

    def _interruptible_sleep(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.control.checkpoint()
            self.sleep(min(0.25, max(0.0, end - time.monotonic())))

    def wait_for_user(self, adapter: BrokerAdapter, exc: UserActionRequired) -> None:
        """Hält an und wartet, bis der Benutzer im Browser gehandelt hat. Keine Umgehung."""
        assert self.status is not None
        self.status.state = "waiting_user"
        self.status.message = str(exc)
        self._emit("waiting_user", broker=adapter.broker_id, reason=exc.reason, message=str(exc))
        log.warning("Benutzeraktion erforderlich (%s): %s", exc.reason, exc)
        waiter = getattr(adapter, "wait_for_login", None)
        ok = waiter(self.settings.login_wait_timeout_s, lambda m: self._emit("waiting_user", broker=adapter.broker_id,
                                                                             reason=exc.reason, message=m)) \
            if waiter else False
        if not ok:
            raise UserActionRequired(exc.reason, "Zeitlimit für die Anmeldung/Bestätigung überschritten. "
                                                 "Scan angehalten – bitte erneut starten.")
        self.status.state = "running"
        self.status.message = "Weiter nach Benutzeraktion"
        self._emit("status", **self.status.__dict__)

    # ------------------------------------------------------------------ #
    def process_ref(self, run_id: int, adapter: BrokerAdapter, ref: DocumentRef, mode: str) -> str:
        assert self.status is not None
        self.status.documents_found += 1
        url_base = url_without_query(ref.url) if ref.url and not ref.url.startswith("blob:") else ""
        self.db.record_source(run_id, ref, url_base)
        existing = self.db.get_item(ref.broker, ref.key)
        if existing and existing["status"] in ITEM_FINAL_OK and mode != "full":
            doc = self.db.find_document_by_key(ref.key) or {}
            from pathlib import Path

            if not doc.get("local_path") or Path(doc["local_path"]).exists():
                self.db.record_item(run_id, ref, "skipped_known", document_id=existing.get("document_id"))
                self.status.skipped_known += 1
                return "skipped_known"
        if not ref.downloadable:
            reason = ref.not_downloadable_reason or "Nicht herunterladbar"
            self.db.record_item(run_id, ref, "not_downloadable", error=reason)
            self.db.upsert_failed_document(ref.broker, ref.key, ref.title, "not_downloadable", reason,
                                           page_url=ref.page_url, doc_date=ref.date)
            self.status.failed += 1
            return "not_downloadable"
        expected = "pdf" if ref.url.lower().split("?")[0].endswith(".pdf") else None
        try:
            file = retry_call(
                lambda: adapter.download_document(ref), attempts=self.settings.retry_attempts,
                backoff_s=self.settings.retry_backoff_s, sleep=self._interruptible_sleep,
                on_retry=lambda n, e: log.info("Wiederhole Download (%s): %s – %s", n, ref.title, redact(e)),
            )
            self.control.checkpoint()
            result = self.store.store(ref, file, expected)
        except (ScanCancelled, UserActionRequired):
            raise
        except DownloadError as exc:
            status = exc.status if exc.status in ("failed", "invalid", "not_downloadable") else "failed"
            if isinstance(exc, FileValidationError):
                status = "invalid"
            self.db.record_item(run_id, ref, status, error=str(exc), count_attempt=True)
            self.db.upsert_failed_document(ref.broker, ref.key, ref.title, status, str(exc), ref.url, ref.page_url,
                                           ref.date)
            self.status.failed += 1
            log.warning("Download fehlgeschlagen: %s – %s", ref.title, redact(exc))
            return status
        except Exception as exc:  # noqa: BLE001 - ein Dokument darf den Scan nie abbrechen
            self.db.record_item(run_id, ref, "failed", error=f"{type(exc).__name__}: {exc}", count_attempt=True)
            self.db.upsert_failed_document(ref.broker, ref.key, ref.title, "failed", str(exc), ref.url,
                                           ref.page_url, ref.date)
            self.status.failed += 1
            log.exception("Unerwarteter Fehler bei %s", ref.title)
            return "failed"
        self.db.record_item(run_id, ref, result.status, document_id=result.document_id, count_attempt=True)
        if result.status == "duplicate":
            self.status.duplicates += 1
        else:
            self.status.downloaded += 1
        self._emit("document", broker=ref.broker, title=ref.title, status=result.status)
        return result.status

    # ------------------------------------------------------------------ #
    def run_broker(self, adapter: BrokerAdapter, mode: str = "sync") -> int:
        if mode not in MODES:
            raise ValueError(f"Unbekannter Modus: {mode}")
        broker = adapter.broker_id
        resumed = self.db.interrupted_run(broker) if mode == "resume" else None
        run_id = self.db.start_run(broker, mode, resumed["id"] if resumed else None)
        skip_areas = self.db.completed_area_keys(resumed["id"]) if resumed else set()
        self.status = ScanStatus(broker, state="running", message="Scan gestartet")
        self._emit("status", **self.status.__dict__)
        final_status, message = "failed", ""
        inaccessible: list[str] = []
        extra_notes: list[str] = []
        try:
            adapter.connect()
            try:
                ok = adapter.check_session()
            except UserActionRequired as exc:
                self.wait_for_user(adapter, exc)
                ok = True
            if not ok:
                self.wait_for_user(adapter, UserActionRequired("login", "Bitte im Browser anmelden."))

            if hasattr(adapter, "api_known_events"):
                adapter.api_known_events = self.db.markers(broker, "tr_event") if mode != "full" else set()

            self.status.message = "Suche Dokumentenbereiche …"
            self._emit("status", **self.status.__dict__)
            for attempt in range(3):
                try:
                    areas = adapter.discover_document_areas()
                    break
                except UserActionRequired as exc:
                    if attempt == 2:
                        raise
                    self.wait_for_user(adapter, exc)
            self.status.areas_total = len(areas)
            for area in areas:
                self.control.checkpoint(lambda: self._emit("paused", broker=broker))
                self.status.current_area = area.name
                self._emit("status", **self.status.__dict__)
                if area.key in skip_areas:
                    area.status = AreaStatus.COMPLETE.value
                    area.note = f"Im unterbrochenen Lauf {resumed['id']} bereits vollständig untersucht."
                    self.db.upsert_area(run_id, broker, area)
                    self.status.areas_done += 1
                    continue
                if area.status == AreaStatus.INACCESSIBLE.value:
                    self.db.upsert_area(run_id, broker, area)
                    inaccessible.append(area.name)
                    self.status.areas_done += 1
                    continue
                self.db.upsert_area(run_id, broker, area)
                user_waits = 0
                while True:
                    try:
                        for ref in adapter.discover_documents(area):
                            self.control.checkpoint(lambda: self._emit("paused", broker=broker))
                            self.process_ref(run_id, adapter, ref, mode)
                            self._emit("status", **self.status.__dict__)
                        break
                    except UserActionRequired as exc:
                        user_waits += 1
                        if user_waits > 2:
                            area.status = AreaStatus.PARTIAL.value
                            area.note += " Abgebrochen: wiederholte Sicherheitsabfragen."
                            break
                        self.wait_for_user(adapter, exc)
                        area.note += " Nach Benutzeraktion erneut untersucht."
                    except ScanCancelled:
                        area.status = AreaStatus.PARTIAL.value
                        area.note += " Scan abgebrochen."
                        self.db.upsert_area(run_id, broker, area)
                        raise
                    except Exception as exc:  # noqa: BLE001 - Bereichsfehler protokollieren, weiter
                        log.exception("Fehler im Bereich %s", area.name)
                        area.status = (AreaStatus.INACCESSIBLE.value if not area.pages_visited
                                       else AreaStatus.PARTIAL.value)
                        area.note += f" Fehler: {redact(exc)}"
                        break
                if area.status == AreaStatus.PENDING.value:
                    area.status = AreaStatus.PARTIAL.value
                if area.status == AreaStatus.INACCESSIBLE.value:
                    inaccessible.append(area.name)
                self.db.upsert_area(run_id, broker, area)
                self.db.recompute_run_counters(run_id)
                self.status.areas_done += 1
            known = getattr(adapter, "api_known_events", None)
            if known:
                self.db.add_markers(broker, "tr_event", known)
            legacy = getattr(adapter, "LEGACY_NOTE", "")
            if legacy:
                extra_notes.append(legacy)
            counters = self.db.recompute_run_counters(run_id)
            final_status = "finished_with_errors" if counters["failed"] or inaccessible else "finished"
            message = "Scan abgeschlossen"
        except ScanCancelled:
            final_status, message = "cancelled", "Scan vom Benutzer abgebrochen – kann fortgesetzt werden."
        except UserActionRequired as exc:
            final_status, message = "waiting_user", str(exc)
        except Exception as exc:  # noqa: BLE001
            log.exception("Scan für %s fehlgeschlagen", broker)
            final_status, message = "failed", f"{type(exc).__name__}: {redact(exc)}"
        finally:
            self.db.recompute_run_counters(run_id)
            self.db.update_run(run_id, inaccessible_areas=inaccessible)
            self.db.finish_run(run_id, final_status, message)
            try:
                self.last_report = write_report(self.db, run_id, self.settings.reports_dir, extra_notes)
            except Exception:  # pragma: no cover
                log.exception("Bericht konnte nicht erstellt werden")
            self.status.state = {"finished": "finished", "finished_with_errors": "finished",
                                 "cancelled": "cancelled"}.get(final_status, "failed")
            self.status.message = message
            self._emit("finished", broker=broker, run_id=run_id, status=final_status, message=message,
                       report=self.last_report)
            log.info("Lauf %s (%s) beendet: %s – %s", run_id, broker, final_status, message)
        return run_id


# --------------------------------------------------------------------------- #
# ScanManager (Hintergrund-Worker für die UI)
# --------------------------------------------------------------------------- #


def make_adapter(broker: str, browser: Any, settings: Settings, control: ScanControl) -> BrokerAdapter:
    if broker == "trade_republic":
        from .trade_republic import TradeRepublicAdapter

        return TradeRepublicAdapter(browser, settings, control)
    if broker == "scalable_capital":
        from .scalable_capital import ScalableCapitalAdapter

        return ScalableCapitalAdapter(browser, settings, control)
    raise ValueError(f"Unbekannter Broker: {broker}")


class ScanManager:
    def __init__(self, settings: Settings, db: Database, headless: bool = False,
                 adapter_factory: Callable[..., BrokerAdapter] = make_adapter):
        self.settings = settings
        self.db = db
        self.headless = headless
        self.adapter_factory = adapter_factory
        self.control = ScanControl()
        self._queue: queue.Queue[tuple[str, tuple, dict]] = queue.Queue()
        self._lock = threading.Lock()
        self.busy = False
        self.current_task = ""
        self.status: dict[str, Any] = {}
        self.login_state: dict[str, str] = {b: "unbekannt" for b in BROKERS}
        self.messages: deque[dict[str, str]] = deque(maxlen=200)
        self.last_command: tuple[list[str], str] | None = None
        self.last_reports: dict[str, dict[str, str]] = {}
        self.waiting_login: str | None = None
        self._browser: Any = None
        self._adapters: dict[str, BrokerAdapter] = {}
        self._thread = threading.Thread(target=self._worker, name="bdc-browser-worker", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------ #
    def _msg(self, text: str, level: str = "info") -> None:
        self.messages.appendleft({"time": datetime.now().strftime("%H:%M:%S"), "level": level, "text": redact(text)})

    def _on_event(self, kind: str, data: dict[str, Any]) -> None:
        with self._lock:
            if kind == "status":
                self.status = dict(data)
            elif kind == "waiting_user":
                self.status["state"] = "waiting_user"
                self.status["message"] = data.get("message", "")
                self.login_state[data["broker"]] = "Aktion erforderlich"
                self._msg(data.get("message", ""), "warn")
            elif kind == "paused":
                self.status["state"] = "paused"
            elif kind == "finished":
                self.status.update(state="finished", message=data.get("message", ""))
                self.last_reports[data["broker"]] = data.get("report") or {}
                self._msg(f"{data['broker']}: {data.get('status')} – {data.get('message')}")

    def _get_browser(self) -> Any:
        if self._browser is None:
            from .browser_manager import BrowserManager

            self._browser = BrowserManager(
                self.settings.profile_dir, headless=self.headless, channel=self.settings.browser_channel,
                executable=self.settings.browser_executable, download_timeout_s=self.settings.download_timeout_s,
                max_bytes=self.settings.max_download_bytes,
            )
        return self._browser

    def _adapter(self, broker: str) -> BrokerAdapter:
        if broker not in self._adapters:
            self._adapters[broker] = self.adapter_factory(broker, self._get_browser(), self.settings, self.control)
        return self._adapters[broker]

    def _worker(self) -> None:
        while True:
            name, args, kwargs = self._queue.get()
            if name == "__stop__":
                break
            self.busy = True
            self.current_task = name
            try:
                getattr(self, f"_do_{name}")(*args, **kwargs)
            except ScanCancelled:
                self._msg("Vorgang abgebrochen", "warn")
            except Exception as exc:  # noqa: BLE001
                log.exception("Worker-Fehler bei %s", name)
                self._msg(f"Fehler: {exc}", "error")
            finally:
                self.busy = False
                self.current_task = ""
                self._queue.task_done()
        if self._browser is not None:
            self._browser.close_all()

    def submit(self, name: str, *args: Any, **kwargs: Any) -> bool:
        if self.busy or not self._queue.empty():
            return False
        self.control.reset()
        self._queue.put((name, args, kwargs))
        return True

    # ------------------------------------------------------------------ #
    # Befehle (laufen im Worker-Thread)
    # ------------------------------------------------------------------ #
    def _do_login(self, broker: str, auto_scan: bool = True, mode: str = "sync") -> None:
        adapter = self._adapter(broker)
        adapter.connect()
        self.waiting_login = broker
        self.login_state[broker] = "Anmeldung läuft – bitte im Browser anmelden"
        self._msg(f"Browser für {adapter.display_name} geöffnet. Bitte selbst anmelden (inkl. 2FA). Falls die "
                  "Anmeldung nicht automatisch erkannt wird: „Ich bin angemeldet – weiter“ klicken.")

        def on_wait(m: str) -> None:
            self.login_state[broker] = m

        try:
            ok = adapter.wait_for_login(self.settings.login_wait_timeout_s, on_wait)  # type: ignore[attr-defined]
        finally:
            self.waiting_login = None
        self.login_state[broker] = "angemeldet" if ok else "nicht angemeldet (Zeitlimit)"
        self._msg(f"{adapter.display_name}: {self.login_state[broker]}")
        if ok and auto_scan:
            self._msg(f"Anmeldung erkannt – starte automatisch den Dokumenten-Scan für {adapter.display_name}.")
            self._do_scan([broker], mode)

    def _do_check(self, broker: str) -> None:
        adapter = self._adapter(broker)
        if getattr(adapter, "page", None) is None:
            adapter.connect()
        try:
            self.login_state[broker] = "angemeldet" if adapter.check_session() else "nicht angemeldet"
        except UserActionRequired as exc:
            self.login_state[broker] = f"Aktion erforderlich: {exc}"

    def _do_scan(self, brokers: list[str], mode: str) -> None:
        self.last_command = (brokers, mode)
        collector = Collector(self.settings, self.db, self.control, self._on_event)
        for broker in brokers:
            self.control.checkpoint()
            adapter = self._adapter(broker)
            self._msg(f"Starte Scan {adapter.display_name} (Modus: {mode})")
            collector.run_broker(adapter, mode)
            self.login_state[broker] = "angemeldet" if collector.status and collector.status.state == "finished" \
                else self.login_state[broker]
            if self.control.cancelled:
                break

    def _do_close_browsers(self) -> None:
        for adapter in self._adapters.values():
            adapter.close()
        self._adapters.clear()

    # ------------------------------------------------------------------ #
    def login(self, broker: str, auto_scan: bool = True, mode: str = "sync") -> bool:
        return self.submit("login", broker, auto_scan=auto_scan, mode=mode if mode in MODES else "sync")

    def confirm_login(self) -> None:
        """Benutzer bestätigt in der Oberfläche, dass die Anmeldung im Browser abgeschlossen ist."""
        self.control.user_confirmed.set()

    def check(self, broker: str) -> bool:
        return self.submit("check", broker)

    def scan(self, brokers: list[str], mode: str = "sync") -> bool:
        brokers = [b for b in brokers if b in BROKERS]
        if not brokers or mode not in MODES:
            return False
        return self.submit("scan", brokers, mode)

    def rerun_last(self) -> bool:
        if not self.last_command:
            last = self.db.last_run()
            if not last:
                return False
            return self.scan([last["broker"]], "resume" if last["status"] != "finished" else "sync")
        return self.scan(*self.last_command)

    def close_browsers(self) -> bool:
        return self.submit("close_browsers")

    def pause(self) -> None:
        self.control.pause()
        self.status["state"] = "paused"

    def resume(self) -> None:
        self.control.resume()
        if self.status.get("state") == "paused":
            self.status["state"] = "running"

    def cancel(self) -> None:
        self.control.cancel()

    def shutdown(self) -> None:
        self.control.cancel()
        self._queue.put(("__stop__", (), {}))
        self._thread.join(timeout=15)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "busy": self.busy, "task": self.current_task, "status": dict(self.status),
                "paused": self.control.paused, "login": dict(self.login_state),
                "waiting_login": self.waiting_login or (self.status.get("broker")
                                                        if self.status.get("state") == "waiting_user" else None), "messages": list(self.messages)[:50],
                "last_reports": dict(self.last_reports),
            }
