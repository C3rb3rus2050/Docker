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
    dann vollständig nach ``<Ziel>_vor_Wiederherstellung_<Zeit>`` verschoben (nichts wird gelöscht).
    Die Anwendung muss danach neu gestartet bzw. der Kontext neu erzeugt werden.
    """
    manifest = verify_backup(zip_path)
    target_base = Path(target_base)
    moved = None
    if target_base.exists() and any(target_base.iterdir()):
        if not move_existing:
            raise BackupError(f"Zielordner {target_base} ist nicht leer. Bestehende Daten zuerst sichern lassen "
                              "(Option „bestehende Daten verschieben“).")
        moved = target_base.with_name(f"{target_base.name}_vor_Wiederherstellung_"
                                      f"{datetime.now():%Y%m%d_%H%M%S}")
        shutil.move(str(target_base), str(moved))
    target_base.mkdir(parents=True, exist_ok=True)
    resolved = target_base.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for name in manifest["files"]:
            rel = _safe_member(name)
            dest = (target_base / Path(*rel.parts)).resolve()
            dest.relative_to(resolved)  # Zip-Slip-Schutz
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            if _sha(dest) != manifest["files"][name]:
                raise BackupError(f"Prüfsumme nach Wiederherstellung falsch: {name}")
    return {"files": len(manifest["files"]), "created_at": manifest["created_at"],
            "moved_existing_to": str(moved) if moved else None}
