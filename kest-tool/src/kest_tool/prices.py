"""Wertpapierkurse: automatischer Abruf (EODHD) und manueller CSV-Import.

Verwendung im Tool:
- Nichtmeldefonds: erster und letzter Kurs des Kalenderjahres (``nmf_prices``) – nur für Jahre, in denen die
  Pauschalregel verifiziert ist, wird damit gerechnet.
- Bewertung der Bestände zum 31.12. (Information, nicht steuerrelevant).

Kursquelle: EODHD (https://eodhd.com) – dokumentierte API mit Suche per ISIN. Benötigt einen persönlichen
API-Schlüssel (Umgebungsvariable ``EODHD_API_KEY``, z. B. in ``.env``). Der kostenlose Zugang ist laut Anbieter auf
20 Abrufe pro Tag und Kurse des letzten Jahres beschränkt. Übertragen werden nur ISIN bzw. Börsenkürzel und der
Zeitraum – keine Bestände, Beträge oder sonstigen Depotdaten.

Steuerlicher Hinweis: Die Pauschalregel für Nichtmeldefonds verlangt Rücknahmepreise. Börsenschlusskurse sind kein
Rücknahmepreis; automatisch geladene Kurse werden deshalb als „ungeprüft“ und mit diesem Hinweis gespeichert.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from .db import now_iso
from .importers.parsing import detect_date_format, detect_decimal_separator, parse_date, parse_number
from .models import FundStatus

log = logging.getLogger(__name__)

EODHD_BASE = "https://eodhd.com/api"
ENV_KEY = "EODHD_API_KEY"
DEFAULT_EXCHANGES = ["XETRA", "F", "VI", "LSE", "AS", "PA", "SW", "MI", "US"]
MAX_BACK_DAYS = 10
NOT_REDEMPTION = "Börsenschlusskurs, kein Rücknahmepreis – prüfen"
NAV_MARKER = "Rücknahmepreis"           # Quellenkennzeichen für echte Rücknahmepreise (NAV)
NAV_EXCHANGE = "EUFUND"                 # EODHD: europäische Fonds, Ticker = ISIN.EUFUND (kostenpflichtiges Paket)


class PriceError(RuntimeError):
    pass


@dataclass
class SymbolInfo:
    symbol: str          # z. B. "EUNL.XETRA"
    name: str
    exchange: str
    currency: str


def _http_json(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers={"User-Agent": "KESt-Tool (lokal)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - feste HTTPS-Basis-URL
        data = resp.read(5 * 1024 * 1024)
    return json.loads(data.decode("utf-8"))


class EodhdProvider:
    name = "EODHD"

    def __init__(self, api_key: str | None = None, exchanges: list[str] | None = None,
                 fetch: Callable[[str], object] | None = None):
        self.api_key = api_key if api_key is not None else os.environ.get(ENV_KEY, "")
        self.exchanges = exchanges or DEFAULT_EXCHANGES
        self._fetch = fetch or _http_json

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _get(self, path: str, **params):
        if not self.api_key:
            raise PriceError(f"Kein API-Schlüssel: Umgebungsvariable {ENV_KEY} setzen (Einstellungen → Wertpapierkurse).")
        q = urllib.parse.urlencode({**params, "api_token": self.api_key, "fmt": "json"})
        url = f"{EODHD_BASE}/{path}?{q}"
        try:
            return self._fetch(url)
        except PriceError:
            raise
        except Exception as exc:  # noqa: BLE001 – Netzwerk/HTTP/JSON
            msg = str(exc).replace(self.api_key, "***")
            raise PriceError(f"Kursabruf fehlgeschlagen ({msg}). Internetverbindung, API-Schlüssel und Tageslimit "
                             "prüfen oder Kurse als CSV importieren.") from None

    def find_symbol(self, isin: str, prefer_currency: str | None = None) -> SymbolInfo | None:
        rows = self._get(f"search/{urllib.parse.quote(isin)}") or []
        rows = [r for r in rows if isinstance(r, dict) and (r.get("ISIN") or "").upper() == isin.upper()] or \
            [r for r in rows if isinstance(r, dict)]
        if not rows:
            return None
        rank = {ex: i for i, ex in enumerate(self.exchanges)}

        def score(r):
            return (0 if prefer_currency and r.get("Currency") == prefer_currency else 1,
                    rank.get(r.get("Exchange"), 99))

        best = sorted(rows, key=score)[0]
        return SymbolInfo(f"{best['Code']}.{best['Exchange']}", best.get("Name") or "", best["Exchange"],
                          (best.get("Currency") or "EUR").upper())

    def nav_history(self, isin: str, start: date, end: date) -> list[tuple[date, float]]:
        """Rücknahmepreise (NAV) europäischer Fonds über EODHD „EUFUND“ (Ticker = ISIN.EUFUND).

        Laut Anbieter erst ab dem Paket „All World Extended“ verfügbar – mit kleinerem Zugang meldet die API einen
        Fehler, der hier verständlich weitergegeben wird.
        """
        try:
            return self.history(f"{isin}.{NAV_EXCHANGE}", start, end)
        except PriceError as exc:
            raise PriceError(f"Rücknahmepreise (EODHD {NAV_EXCHANGE}) nicht abrufbar – laut Anbieter erst ab Paket "
                             f"„All World Extended“. Details: {exc}") from None

    def nav_currency(self, isin: str) -> str | None:
        rows = self._get(f"search/{urllib.parse.quote(isin)}") or []
        for r in rows:
            if isinstance(r, dict) and r.get("Exchange") == NAV_EXCHANGE:
                return (r.get("Currency") or "").upper() or None
        return None

    def history(self, symbol: str, start: date, end: date) -> list[tuple[date, float]]:
        rows = self._get(f"eod/{urllib.parse.quote(symbol)}", **{"from": start.isoformat(), "to": end.isoformat()})
        out = []
        for r in rows or []:
            try:
                d, close = date.fromisoformat(r["date"]), float(r["close"])
            except (KeyError, TypeError, ValueError):
                continue
            if close > 0:
                out.append((d, close))
        return sorted(out)


# --------------------------------------------------------------------------- #
class PriceService:
    def __init__(self, repo, provider: EodhdProvider | None = None):
        self.repo = repo
        self.db = repo.db
        self.provider = provider or EodhdProvider()

    # Kursreihen in der Datenbank -----------------------------------------
    def store(self, isin: str, rows: list[tuple[date, float]], currency: str, source: str) -> int:
        n = 0
        for d, close in rows:
            self.db.execute(
                "INSERT INTO security_prices(isin, price_date, close, currency, source, fetched_at) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(isin, price_date, source) DO UPDATE SET close=excluded.close, currency=excluded.currency, "
                "fetched_at=excluded.fetched_at", (isin, d.isoformat(), close, currency, source, now_iso()))
            n += 1
        return n

    def series(self, isin: str, start: date, end: date) -> list[dict]:
        return self.db.query("SELECT * FROM security_prices WHERE isin=? AND price_date BETWEEN ? AND ? "
                             "ORDER BY price_date", (isin, start.isoformat(), end.isoformat()))

    def price_on(self, isin: str, on: date) -> dict | None:
        return self.db.one("SELECT * FROM security_prices WHERE isin=? AND price_date<=? AND price_date>=? "
                           "ORDER BY price_date DESC LIMIT 1",
                           (isin, on.isoformat(), (on - timedelta(days=MAX_BACK_DAYS)).isoformat()))

    # Abruf -------------------------------------------------------------------
    def ensure_symbol(self, isin: str) -> SymbolInfo | None:
        sec = self.repo.security_by_isin(isin) or {}
        if sec.get("price_symbol"):
            return SymbolInfo(sec["price_symbol"], sec.get("name") or "", sec["price_symbol"].split(".")[-1],
                              (sec.get("price_currency") or sec.get("currency") or "EUR").upper())
        info = self.provider.find_symbol(isin, prefer_currency="EUR")
        if info:
            self.repo.ensure_security(isin, info.name)
            self.db.execute("UPDATE securities SET price_symbol=?, price_currency=? WHERE isin=?",
                            (info.symbol, info.currency, isin))
            self.repo.audit("security", isin, "Kurssymbol zugeordnet",
                            {"symbol": info.symbol, "börse": info.exchange, "währung": info.currency,
                             "quelle": self.provider.name})
        return info

    def nav_series(self, isin: str, start: date, end: date) -> list[dict]:
        """Gespeicherte Rücknahmepreise (manuell importiert oder EUFUND) im Zeitraum."""
        return self.db.query("SELECT * FROM security_prices WHERE isin=? AND price_date BETWEEN ? AND ? AND source LIKE ? "
                             "ORDER BY price_date", (isin, start.isoformat(), end.isoformat(), f"%{NAV_MARKER}%"))

    def fetch_nav(self, isin: str, start: date, end: date) -> list[dict]:
        rows = self.provider.nav_history(isin, start, end)
        if rows:
            try:
                fund_cur = self.provider.nav_currency(isin)
            except PriceError:
                fund_cur = None
            fund_cur = fund_cur or ((self.repo.security_by_isin(isin) or {}).get("currency") or "EUR").upper()
            self.store(isin, rows, fund_cur, f"EODHD {isin}.{NAV_EXCHANGE} ({NAV_MARKER}/NAV)")
        return self.nav_series(isin, start, end)

    def fetch(self, isin: str, start: date, end: date) -> tuple[SymbolInfo | None, list[dict]]:
        existing = self.series(isin, start, end)
        info = self.ensure_symbol(isin)
        if info is None:
            return None, existing
        have_start = existing and existing[0]["price_date"] <= (start + timedelta(days=MAX_BACK_DAYS)).isoformat()
        have_end = existing and existing[-1]["price_date"] >= min(end, date.today() - timedelta(days=1)).isoformat() \
            if existing else False
        if not (have_start and have_end):
            rows = self.provider.history(info.symbol, start - timedelta(days=MAX_BACK_DAYS), end)
            self.store(isin, rows, info.currency, f"{self.provider.name} {info.symbol}")
        return info, self.series(isin, start - timedelta(days=MAX_BACK_DAYS), end)


@dataclass
class PriceResult:
    isin: str
    purpose: str
    status: str          # gesetzt | identisch | konflikt | kein_kurs | fehler
    message: str


def _held_isins(repo, year: int, fund_status: str | None = None) -> list[str]:
    rows = repo.db.query("SELECT DISTINCT t.isin FROM transactions t JOIN securities s ON s.isin=t.isin "
                         "WHERE t.deleted=0 AND t.isin IS NOT NULL AND t.trade_date<=?"
                         + (" AND s.fund_status=?" if fund_status else ""),
                         (f"{year}-12-31", fund_status) if fund_status else (f"{year}-12-31",))
    return [r["isin"] for r in rows]


def fill_nmf_prices(repo, service: PriceService, year: int, allow_exchange_fallback: bool = True) -> list[PriceResult]:
    """Erster/letzter Preis des Jahres für Nichtmeldefonds. Bestehende Werte werden nie überschrieben (Konflikt).

    Reihenfolge: 1. bereits gespeicherte Rücknahmepreise (z. B. CSV der Fondsgesellschaft), 2. Rücknahmepreise über
    EODHD EUFUND, 3. (optional) Börsenschlusskurse – mit Hinweis „kein Rücknahmepreis“.
    """
    out = []
    start, end = date(year, 1, 1), date(year, 12, 31)
    for isin in _held_isins(repo, year, FundStatus.NICHTMELDEFONDS.value):
        existing = repo.db.one("SELECT * FROM nmf_prices WHERE isin=? AND tax_year=?", (isin, year))
        if existing and existing.get("first_price") and existing.get("last_price"):
            out.append(PriceResult(isin, "Nichtmeldefonds", "identisch", "Preise bereits erfasst"))
            continue
        rows, kind, notes = service.nav_series(isin, start, end), "Rücknahmepreis", []
        if not rows and service.provider.available:
            try:
                rows = service.fetch_nav(isin, start, end)
            except PriceError as exc:
                notes.append(str(exc))
        if not rows and allow_exchange_fallback:
            try:
                info, all_rows = service.fetch(isin, start, end)
                rows = [r for r in all_rows if r["price_date"][:4] == str(year) and NAV_MARKER not in r["source"]]
                kind = "Börsenkurs"
            except PriceError as exc:
                notes.append(str(exc))
        rows = [r for r in rows if r["price_date"][:4] == str(year)]
        if not rows:
            out.append(PriceResult(isin, "Nichtmeldefonds", "fehler" if notes else "kein_kurs",
                                   "; ".join(notes) or f"keine Preise für {year} gefunden"))
            continue
        first, last = rows[0], rows[-1]
        src = first["source"] if kind == "Rücknahmepreis" else f"{first['source']} – {NOT_REDEMPTION}"
        fx_last = None
        if first["currency"] != "EUR":
            fx_last = _ecb_rate(repo, first["currency"], date.fromisoformat(last["price_date"]))
            if fx_last is None:
                notes.append(f"EZB-Kurs {first['currency']} zum {last['price_date']} fehlt – Devisenkurs nachtragen")
        res = repo.upsert_nmf_price(isin, year, first["close"], first["price_date"], last["close"], last["price_date"],
                                    first["currency"], fx_last, src)
        msg = (f"{kind}: erster {first['close']} ({first['price_date']}), letzter {last['close']} "
               f"({last['price_date']}) {first['currency']}")
        if kind == "Börsenkurs" and notes:
            msg += " – Rücknahmepreise nicht verfügbar: " + "; ".join(notes)
        out.append(PriceResult(isin, "Nichtmeldefonds", "gesetzt" if res["status"] == "neu" else res["status"], msg))
    return out


def _ecb_rate(repo, currency: str, on: date) -> float | None:
    from .fx import FxError, FxService

    try:
        rates = FxService(repo.store.base).rates(allow_download=True, needed_until=on)
    except FxError:
        return None
    hit = rates.lookup(currency, on) if rates else None
    return hit[0] if hit else None


def fill_year_end_prices(repo, service: PriceService, year: int) -> list[PriceResult]:
    """Kurse zum 31.12. für alle bis dahin gebuchten Wertpapiere (Bestandsbewertung)."""
    out = []
    end = date(year, 12, 31)
    for isin in _held_isins(repo, year):
        if service.price_on(isin, end):
            out.append(PriceResult(isin, "Bewertung 31.12.", "identisch", "Kurs vorhanden"))
            continue
        try:
            info, rows = service.fetch(isin, end - timedelta(days=MAX_BACK_DAYS), end)
        except PriceError as exc:
            out.append(PriceResult(isin, "Bewertung 31.12.", "fehler", str(exc)))
            continue
        p = service.price_on(isin, end)
        out.append(PriceResult(isin, "Bewertung 31.12.", "gesetzt" if p else "kein_kurs",
                               f"{p['close']} {p['currency']} vom {p['price_date']}" if p else "kein Kurs gefunden"))
    return out


def import_price_csv(repo, service: PriceService, data: bytes, filename: str, isin: str | None = None,
                     currency: str = "EUR", redemption: bool = False) -> int:
    """CSV mit Spalten Datum;Kurs (optional ISIN;Währung). ``redemption=True``: Rücknahmepreise (NAV),
    z. B. von der Fondsgesellschaft – werden für Nichtmeldefonds bevorzugt verwendet."""
    from .importers.csv_importer import read_table

    df, _ = read_table(data, filename)
    cols = {c.lower().strip(): c for c in df.columns}
    dcol = next((cols[c] for c in cols if c in ("datum", "date", "kursdatum")), None)
    pcol = next((cols[c] for c in cols if c in ("kurs", "close", "schlusskurs", "preis", "rücknahmepreis",
                                                    "ruecknahmepreis", "nav", "price")), None)
    icol = next((cols[c] for c in cols if c == "isin"), None)
    ccol = next((cols[c] for c in cols if c in ("währung", "waehrung", "currency")), None)
    if not dcol or not pcol or (not icol and not isin):
        raise PriceError("CSV benötigt die Spalten Datum und Kurs (sowie ISIN, falls keine ISIN gewählt ist)")
    fmt = detect_date_format(df[dcol].tolist(), ["%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"])
    dec = detect_decimal_separator(df[pcol].tolist())
    n = 0
    by_isin: dict[tuple[str, str], list[tuple[date, float]]] = {}
    for _, r in df.iterrows():
        try:
            d = parse_date(r[dcol], fmt)
            v = parse_number(r[pcol], dec)
        except ValueError:
            continue
        if d is None or not v or v <= 0:
            continue
        key = ((str(r[icol]).strip().upper() if icol else isin), (str(r[ccol]).strip().upper() if ccol else currency))
        by_isin.setdefault(key, []).append((d, v))
    for (i, cur), rows in by_isin.items():
        kind = f"{NAV_MARKER} (manueller Import" if redemption else "Kurs (manueller Import"
        n += service.store(i, rows, cur or "EUR", f"{kind} {Path(filename).name})")
    repo.audit("security_prices", None, "Kurse importiert", {"datei": filename, "anzahl": n})
    return n


def price_csv_template() -> str:
    return "ISIN;Datum;Kurs;Währung\nLU0274208692;02.01.2024;100,00;EUR\nLU0274208692;31.12.2024;110,00;EUR\n"
