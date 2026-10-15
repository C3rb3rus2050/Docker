"""Devisenkurse: Euro-Referenzkurse der Europäischen Zentralbank (EZB).

Quelle: https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip (öffentlich, ohne Anmeldung).
Die Datei enthält je Bankarbeitstag die Kurse „Fremdwährung je 1 EUR“ – dieselbe Notierung wie ``fx_rate``.

Datenschutz: Es wird nur diese öffentliche Datei heruntergeladen; es werden keine Buchungs- oder Depotdaten
übertragen. Der Abruf lässt sich in config.yaml (``fx.auto_fetch``) abschalten; dann kann die Datei manuell
importiert werden.

Steuerlicher Hinweis: Ob für die österreichische KESt der EZB-Referenzkurs oder ein anderer Kurs (z. B. der
Devisenmittelkurs der depotführenden Bank) maßgeblich ist, wurde nicht verifiziert (Regel FX_CONVERSION).
Kurse aus dem Beleg haben deshalb immer Vorrang; automatisch ergänzte Kurse werden gekennzeichnet und die
betroffenen Positionen bleiben „vorläufig“.
"""

from __future__ import annotations

import csv
import io
import logging
import math
import urllib.request
import zipfile
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
CACHE_NAME = "eurofxref-hist.csv"
MAX_BACKTRACK_DAYS = 7      # Wochenende/Feiertag: letzter verfügbarer Bankarbeitstag davor
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024


class FxError(RuntimeError):
    pass


@dataclass
class FxRates:
    rates: dict[str, dict[date, float]] = field(default_factory=dict)   # Währung -> Datum -> Kurs
    source: str = ""
    loaded_at: str = ""

    @property
    def currencies(self) -> list[str]:
        return sorted(self.rates)

    @property
    def last_date(self) -> date | None:
        return max((max(v) for v in self.rates.values() if v), default=None)

    def lookup(self, currency: str, on: date) -> tuple[float, date] | None:
        """Kurs (Währung je EUR) zum Datum; bei fehlendem Kurs der letzte Bankarbeitstag davor (max. 7 Tage)."""
        currency = currency.upper()
        if currency == "EUR":
            return 1.0, on
        series = self.rates.get(currency)
        if not series:
            return None
        if on in series:
            return series[on], on
        days = sorted(series)
        i = bisect_right(days, on)
        if i == 0:
            return None
        d = days[i - 1]
        if (on - d).days > MAX_BACKTRACK_DAYS:
            return None
        return series[d], d


def parse_ecb_csv(text: str, source: str = "EZB") -> FxRates:
    """Liest das EZB-Format: 'Date,USD,JPY,…' mit Werten oder 'N/A'."""
    reader = csv.reader(io.StringIO(text))
    try:
        header = [h.strip() for h in next(reader)]
    except StopIteration as exc:
        raise FxError("Kursdatei ist leer") from exc
    if not header or header[0].lower() != "date":
        raise FxError("Unbekanntes Format – erwartet wird die EZB-Datei eurofxref-hist.csv (erste Spalte 'Date')")
    out: dict[str, dict[date, float]] = {}
    for row in reader:
        if not row or not row[0].strip():
            continue
        try:
            d = date.fromisoformat(row[0].strip())
        except ValueError:
            continue
        for cur, val in zip(header[1:], row[1:]):
            cur, val = cur.strip().upper(), val.strip()
            if not cur or not val or val.upper() == "N/A":
                continue
            try:
                rate = float(val)
            except ValueError:
                continue
            if math.isfinite(rate) and rate > 0:
                out.setdefault(cur, {})[d] = rate
    if not out:
        raise FxError("Keine Kurse in der Datei gefunden")
    return FxRates(out, source=source, loaded_at=datetime.now().isoformat(timespec="seconds"))


def _csv_from_bytes(data: bytes) -> str:
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise FxError("Kursdatei ist zu groß")
    try:
        if data[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                entries = [i for i in zf.infolist() if i.filename.lower().endswith(".csv")]
                if len(entries) != 1:
                    raise FxError("Kurs-ZIP muss genau eine CSV-Datei enthalten")
                if entries[0].file_size > MAX_DOWNLOAD_BYTES:
                    raise FxError("Entpackte Kursdatei ist zu groß")
                return zf.read(entries[0]).decode("utf-8-sig")
        return data.decode("utf-8-sig")
    except FxError:
        raise
    except (zipfile.BadZipFile, UnicodeDecodeError, RuntimeError) as exc:
        raise FxError("Kursdatei ist beschädigt oder nicht als UTF-8 lesbar") from exc


class FxService:
    """Lädt, cached und liefert EZB-Referenzkurse. Cache: <Ablage>/fx/eurofxref-hist.csv"""

    def __init__(self, base_dir: Path, url: str = ECB_URL, timeout: int = 30):
        self.dir = Path(base_dir) / "fx"
        self.url = url
        self.timeout = timeout
        self._rates: FxRates | None = None
        self._download_attempted = False

    @property
    def cache_file(self) -> Path:
        return self.dir / CACHE_NAME

    def cache_info(self) -> dict:
        if not self.cache_file.exists():
            return {"vorhanden": False}
        rates = self.rates(allow_download=False)
        return {"vorhanden": True, "stand": rates.last_date.isoformat() if rates and rates.last_date else None,
                "geladen": datetime.fromtimestamp(self.cache_file.stat().st_mtime).isoformat(timespec="seconds"),
                "waehrungen": len(rates.currencies) if rates else 0}

    def import_bytes(self, data: bytes, source: str = "EZB (manueller Import)") -> FxRates:
        text = _csv_from_bytes(data)
        rates = parse_ecb_csv(text, source)      # validiert vor dem Speichern
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_file.with_suffix(".part")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(self.cache_file)
        self._rates = rates
        return rates

    def download(self) -> FxRates:
        req = urllib.request.Request(self.url, headers={"User-Agent": "KESt-Tool (lokal)"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 - feste HTTPS-URL
                data = resp.read(MAX_DOWNLOAD_BYTES + 1)
        except OSError as exc:
            raise FxError(f"EZB-Kurse konnten nicht geladen werden ({exc}). Internetverbindung prüfen oder die Datei "
                          f"{self.url} manuell herunterladen und unter Einstellungen importieren.") from exc
        if len(data) > MAX_DOWNLOAD_BYTES:
            raise FxError("Antwort der EZB unplausibel groß")
        rates = self.import_bytes(data, source=f"EZB-Referenzkurse ({self.url})")
        log.info("EZB-Referenzkurse geladen: %s Währungen, Stand %s", len(rates.currencies), rates.last_date)
        return rates

    def rates(self, allow_download: bool = True, needed_until: date | None = None) -> FxRates | None:
        """Kurse aus dem Cache; lädt neu, wenn kein Cache besteht oder er älter als ``needed_until`` ist."""
        if self._rates is None and self.cache_file.exists():
            try:
                self._rates = parse_ecb_csv(self.cache_file.read_text(encoding="utf-8"), "EZB-Referenzkurse (Cache)")
            except FxError as exc:
                log.warning("Kurs-Cache unbrauchbar: %s", exc)
        stale = (self._rates is None or (needed_until is not None and self._rates.last_date is not None
                                        and self._rates.last_date < min(needed_until, date.today() - timedelta(days=1))))
        if stale and allow_download and not self._download_attempted:
            self._download_attempted = True
            return self.download()
        return self._rates


@dataclass
class FillResult:
    tx_id: int
    currency: str
    trade_date: str
    status: str            # gesetzt | kein_kurs
    rate: float | None = None
    rate_date: str | None = None
    message: str = ""


def fill_missing_fx(repo, service: FxService, tax_year: int | None = None,
                    allow_download: bool = True) -> list[FillResult]:
    """Ergänzt fehlende Devisenkurse (nur Buchungen ohne Kurs). Belegkurse werden nie überschrieben."""
    sql = "SELECT * FROM transactions WHERE deleted=0 AND currency<>'EUR' AND (fx_rate IS NULL OR fx_rate<=0)"
    params: tuple = ()
    if tax_year:
        sql += " AND trade_date<=?"
        params = (f"{tax_year}-12-31",)
    txs = repo.db.query(sql + " ORDER BY trade_date", params)
    if not txs:
        return []
    needed = max(date.fromisoformat(t["trade_date"]) for t in txs)
    rates = service.rates(allow_download=allow_download, needed_until=needed)
    if rates is None:
        raise FxError("Keine Kursdaten vorhanden – automatischer Abruf deaktiviert oder fehlgeschlagen.")
    out = []
    for t in txs:
        hit = rates.lookup(t["currency"], date.fromisoformat(t["trade_date"]))
        if not hit:
            out.append(FillResult(t["id"], t["currency"], t["trade_date"], "kein_kurs",
                                  message=f"kein EZB-Kurs für {t['currency']} am {t['trade_date']}"))
            continue
        rate, rd = hit
        note = (f"EZB-Referenzkurs {t['currency']} {rate} vom {rd.isoformat()}"
                + (" (letzter Bankarbeitstag vor dem Buchungsdatum)" if rd.isoformat() != t["trade_date"] else ""))
        repo.update_transaction(t["id"], {"fx_rate": rate, "fx_source": note},
                                reason=f"Devisenkurs automatisch ergänzt: {note}")
        out.append(FillResult(t["id"], t["currency"], t["trade_date"], "gesetzt", rate, rd.isoformat(), note))
    return out
