"""Kommandozeile: Oberfläche starten, Sync für den Aufgabenplaner, Wartungsfunktionen."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import ConfigError, load_settings

log = logging.getLogger("broker_collector")

BROKER_ALIASES = {"tr": "trade_republic", "trade_republic": "trade_republic", "sc": "scalable_capital",
                  "scalable_capital": "scalable_capital"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="broker-collector", description="Broker Document Collector")
    p.add_argument("--config", type=Path, default=None, help="Pfad zur config.toml")
    p.add_argument("--no-browser-ui", action="store_true", help="Oberfläche nicht automatisch im Browser öffnen")
    p.add_argument("--headless", action="store_true", help="Browser unsichtbar (nur für Tests; Anmeldung unmöglich)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--sync", action="store_true", help="Inkrementelle Synchronisierung beider Broker (Aufgabenplaner)")
    g.add_argument("--scan", choices=sorted(BROKER_ALIASES) + ["all"], help="Scan ohne Oberfläche")
    g.add_argument("--report", type=int, metavar="LAUF", help="Bericht für einen Scanlauf erzeugen")
    g.add_argument("--delete-profile", nargs="?", const="all", metavar="BROKER", help="Browserprofil löschen")
    g.add_argument("--delete-database", action="store_true", help="Lokale Datenbank löschen")
    g.add_argument("--delete-downloads", nargs="?", const="all", metavar="BROKER", help="Downloads löschen")
    g.add_argument("--schedule-create", metavar="HH:MM", help="Täglichen Sync im Windows-Aufgabenplaner anlegen")
    g.add_argument("--schedule-delete", action="store_true", help="Aufgabenplaner-Eintrag entfernen")
    p.add_argument("--mode", choices=["full", "sync", "resume"], default="sync", help="Scanmodus für --scan")
    p.add_argument("--yes", action="store_true", help="Löschaktionen ohne Rückfrage ausführen")
    return p.parse_args(argv)


def _confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    try:
        return input(f"{question} [ja/NEIN]: ").strip().lower() in ("ja", "j", "yes", "y")
    except EOFError:
        return False


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        settings = load_settings(args.config)
    except ConfigError as exc:
        print(f"FEHLER in der Konfiguration: {exc}")
        return 2
    settings.ensure_dirs()

    from .logging_setup import setup_logging

    setup_logging(settings.logs_dir)
    config_path = args.config or Path("config.toml")

    # ---- Wartung (ohne Datenbankverbindung) ------------------------------ #
    from . import maintenance

    if args.delete_profile:
        broker = None if args.delete_profile == "all" else BROKER_ALIASES.get(args.delete_profile)
        if _confirm("Browserprofil wirklich löschen? Danach ist eine Neuanmeldung nötig.", args.yes):
            print("Gelöscht:", maintenance.delete_browser_profile(settings, broker) or "nichts vorhanden")
        return 0
    if args.delete_database:
        if _confirm("Lokale Datenbank (Downloadhistorie, Scanprotokolle) wirklich löschen?", args.yes):
            print("Gelöscht:", maintenance.delete_database(settings) or "nichts vorhanden")
        return 0
    if args.delete_downloads:
        broker = None if args.delete_downloads == "all" else BROKER_ALIASES.get(args.delete_downloads)
        if _confirm("Heruntergeladene Dokumente wirklich löschen?", args.yes):
            print("Gelöscht:", maintenance.delete_downloads(settings, broker) or "nichts vorhanden")
        return 0
    if args.schedule_create or args.schedule_delete:
        from .scheduler import SchedulerError, create_task, delete_task

        start_bat = Path(__file__).resolve().parents[2] / "start_collector.bat"
        try:
            print(create_task(start_bat, args.schedule_create) if args.schedule_create else delete_task())
        except SchedulerError as exc:
            print(f"FEHLER: {exc}")
            return 1
        return 0

    from .database import Database

    db = Database(settings.database_path)
    stale = db.mark_stale_runs_interrupted()
    if stale:
        log.info("%s unterbrochene(r) Lauf/Läufe gefunden – mit Modus 'Fortsetzen' weiterführbar", stale)

    if args.report:
        from .reporting import write_report

        print(write_report(db, args.report, settings.reports_dir))
        return 0

    if args.sync or args.scan:
        from .broker_adapter import ScanControl
        from .browser_manager import BrowserManager
        from .scanner import BROKERS, Collector, make_adapter

        brokers = list(BROKERS) if args.sync or args.scan == "all" else [BROKER_ALIASES[args.scan]]
        mode = "sync" if args.sync else args.mode
        control = ScanControl()
        browser = BrowserManager(settings.profile_dir, headless=args.headless, channel=settings.browser_channel,
                                 executable=settings.browser_executable,
                                 download_timeout_s=settings.download_timeout_s,
                                 max_bytes=settings.max_download_bytes)

        def on_event(kind: str, data: dict) -> None:
            if kind == "waiting_user":
                print(f"\n>>> AKTION ERFORDERLICH: {data.get('message')}\n")
            elif kind == "finished":
                print(f"{data['broker']}: {data['status']} – {data['message']}")
                for fmt, path in (data.get("report") or {}).items():
                    print(f"   Bericht ({fmt}): {path}")

        collector = Collector(settings, db, control, on_event)
        exit_code = 0
        try:
            for broker in brokers:
                run_id = collector.run_broker(make_adapter(broker, browser, settings, control), mode)
                run = db.get_run(run_id) or {}
                if run.get("status") not in ("finished",):
                    exit_code = 1
        except KeyboardInterrupt:
            control.cancel()
            exit_code = 130
        finally:
            browser.close_all()
            db.close()
        return exit_code

    from .scanner import ScanManager
    from .ui import serve

    manager = ScanManager(settings, db, headless=args.headless)
    serve(settings, db, manager, config_path, open_browser=settings.open_browser_ui and not args.no_browser_ui)
    db.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
