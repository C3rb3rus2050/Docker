"""Vollständiges Backup (Datenbank, Dokumente, Importe, Exporte, Berichte, Konfiguration) und Wiederherstellung.

- Die Datenbank wird über die SQLite-Backup-API konsistent kopiert.
- Das ZIP enthält ein Manifest mit SHA-256 je Datei; bei der Wiederherstellung wird jede Datei geprüft.
- Wiederherstellung nur in einen leeren Zielordner oder nach Sicherung des bestehenden Ordners;
  ZIP-Einträge mit absoluten Pfaden oder ``..`` werden abgelehnt (Zip-Slip-Schutz).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from .db import Database
from .storage import DocumentStore

BACKUP_DIRS = ["documents", "imports", "exports", "reports", "config"]
MANIFEST = "manifest.json"
MAX_RESTORE_BYTES = 20 * 1024 ** 3


class BackupError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def create_backup(db: Database, store: DocumentStore, target_dir: Path | None = None) -> Path:
    target_dir = Path(target_dir or store.base / "backups")
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    target = store.unique_target(target_dir, f"KESt-Tool_Backup_{stamp}.zip")
    manifest = {"created_at": datetime.now().isoformat(timespec="seconds"), "app": "KESt-Tool", "files": {}}
    with tempfile.TemporaryDirectory() as tmpd:
        db_copy = Path(tmpd) / "kest_tool.db"
        db.backup_to(db_copy)
        tmp_zip = target.with_suffix(".part")
        with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(db_copy, "database/kest_tool.db")
            manifest["files"]["database/kest_tool.db"] = _sha(db_copy)
            for sub in BACKUP_DIRS:
                base = store.base / sub
                if not base.exists():
                    continue
                for f in sorted(base.rglob("*")):
                    if f.is_file() and not f.name.endswith(".part"):
                        arc = f.relative_to(store.base).as_posix()
                        zf.write(f, arc)
                        manifest["files"][arc] = _sha(f)
            zf.writestr(MANIFEST, json.dumps(manifest, indent=2, ensure_ascii=False))
        tmp_zip.replace(target)
    return target


def _safe_member(name: str) -> PurePosixPath:
    p = PurePosixPath(name.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts or (p.parts and ":" in p.parts[0]):
        raise BackupError(f"Unzulässiger Pfad im Backup: {name}")
    return p


def verify_backup(zip_path: Path) -> dict:
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if MANIFEST not in names:
            raise BackupError("Kein KESt-Tool-Backup (manifest.json fehlt)")
        manifest = json.loads(zf.read(MANIFEST))
        total = sum(i.file_size for i in zf.infolist())
        if total > MAX_RESTORE_BYTES:
            raise BackupError("Backup ist unplausibel groß")
        for n in names:
            _safe_member(n)
        for name, sha in manifest["files"].items():
            _safe_member(name)
            if name not in names:
                raise BackupError(f"Datei fehlt im Backup: {name}")
            h = hashlib.sha256()
            with zf.open(name) as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    h.update(chunk)
            if h.hexdigest() != sha:
                raise BackupError(f"Prüfsumme stimmt nicht: {name}")
    return manifest


def restore_backup(zip_path: Path, target_base: Path, *, move_existing: bool = False) -> dict:
    """Stellt ein Backup in ``target_base`` wieder her.

    Ist der Zielordner nicht leer, wird nur mit ``move_existing=True`` fortgefahren; der bestehende Ordner wird
    dann unter ``<Ziel>/backups/vor_Wiederherstellung_*`` gesichert. Der Zielordner selbst bleibt bestehen;
    vorhandene Backups und API-Schlüssel bleiben erhalten.
    Die Anwendung muss danach neu gestartet bzw. der Kontext neu erzeugt werden.
    """
    manifest = verify_backup(zip_path)
    target_base = Path(target_base)
    if target_base.exists() and any(target_base.iterdir()) and not move_existing:
        raise BackupError(f"Zielordner {target_base} ist nicht leer. Bestehende Daten zuerst sichern lassen.")
    allowed = set(BACKUP_DIRS) | {"database"}
    for name in manifest["files"]:
        rel = _safe_member(name)
        if len(rel.parts) < 2 or rel.parts[0] not in allowed:
            raise BackupError(f"Unzulässiger Datenbereich im Backup: {name}")
    target_base.mkdir(parents=True, exist_ok=True)
    moved = None
    # Stage and verify everything before touching live data. Never rename the mount point.
    with tempfile.TemporaryDirectory(prefix=".restore-", dir=target_base) as staging:
        stage = Path(staging)
        with zipfile.ZipFile(zip_path) as zf:
            for name, checksum in manifest["files"].items():
                rel = _safe_member(name)
                dest = stage.joinpath(*rel.parts).resolve()
                dest.relative_to(stage.resolve())
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
                if _sha(dest) != checksum:
                    raise BackupError(f"Prüfsumme nach Wiederherstellung falsch: {name}")
        existing = [sub for sub in sorted(allowed) if (target_base / sub).exists()]
        if existing:
            recovery = target_base / "backups"
            recovery.mkdir(exist_ok=True)
            moved = Path(tempfile.mkdtemp(prefix="vor_Wiederherstellung_", dir=recovery))
        saved, installed = [], []
        try:
            for sub in existing:
                shutil.move(str(target_base / sub), str(moved / sub))
                saved.append(sub)
            for sub in sorted(allowed):
                if (stage / sub).exists():
                    shutil.move(str(stage / sub), str(target_base / sub))
                    installed.append(sub)
        except OSError:
            # Keep the old data usable if installing the prepared restore fails.
            for sub in installed:
                shutil.move(str(target_base / sub), str(stage / sub))
            for sub in saved:
                shutil.move(str(moved / sub), str(target_base / sub))
            raise
    return {"files": len(manifest["files"]), "created_at": manifest["created_at"],
            "moved_existing_to": str(moved) if moved else None}
