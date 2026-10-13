"""Robuste Erkennung von Zahlen-, Datums- und Buchungsartformaten."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Iterable

from ..models import TxType

_NUM_CLEAN = re.compile(r"[^\d,.\-+()]")


def detect_decimal_separator(values: Iterable[str]) -> str:
    """Ermittelt das Dezimaltrennzeichen einer ganzen Spalte (',' oder '.')."""
    comma_votes = dot_votes = 0
    for raw in values:
        s = _NUM_CLEAN.sub("", str(raw or ""))
        if not s:
            continue
        has_c, has_d = "," in s, "." in s
        if has_c and has_d:
            if s.rfind(",") > s.rfind("."):
                comma_votes += 3
            else:
                dot_votes += 3
        elif has_c:
            tail = s.split(",")[-1]
            # "1,234" (genau 3 Stellen) ist mehrdeutig; "12,5" oder "0,25" eindeutig deutsch
            if len(tail) != 3 or s.count(",") == 1 and s.startswith(("0,", "-0,")):
                comma_votes += 2
            elif s.count(",") > 1:
                dot_votes += 2
            else:
                comma_votes += 1  # leichte Präferenz für deutsche Exporte
        elif has_d:
            tail = s.split(".")[-1]
            if s.count(".") > 1:
                comma_votes += 2  # Tausenderpunkte: 1.234.567
            elif len(tail) != 3:
                dot_votes += 2
            else:
                dot_votes += 1
    return "," if comma_votes >= dot_votes and comma_votes > 0 else "."


def parse_number(raw, decimal: str = ",") -> float | None:
    """Wandelt '1.234,56', '-12,5 €', '(12.50)', '1 234,00' in float um. Leere Werte -> None."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        if raw != raw:  # NaN
            return None
        return float(raw)
    s = unicodedata.normalize("NFKC", str(raw)).strip()
    if not s or s.lower() in {"nan", "none", "-", "—", "n/a"}:
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    s = s.replace("−", "-").replace("'", "").replace(" ", "")
    if s.endswith("-") and not s.startswith("-"):  # "12,50-"
        negative, s = True, s[:-1]
    s = _NUM_CLEAN.sub("", s)
    if s.startswith("-"):
        negative, s = not negative, s[1:]
    s = s.lstrip("+")
    if decimal == ",":
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    if not s or s.count(".") > 1:
        raise ValueError(f"Zahl nicht lesbar: '{raw}'")
    value = float(s)
    return -value if negative else value


def detect_date_format(values: Iterable[str], candidates: list[str]) -> str | None:
    vals = [str(v).strip() for v in values if str(v or "").strip() and str(v).strip().lower() != "nan"]
    if not vals:
        return None
    best, best_ok = None, 0
    for fmt in candidates:
        ok = 0
        for v in vals:
            try:
                datetime.strptime(_trim_time(v, fmt), fmt)
                ok += 1
            except ValueError:
                pass
        if ok == len(vals):
            return fmt
        if ok > best_ok:
            best, best_ok = fmt, ok
    return best if best_ok else None


def _trim_time(v: str, fmt: str) -> str:
    # Uhrzeiten abschneiden, wenn das Format keine enthält ("2024-03-01 10:00:00", "2024-03-01T10:00:00Z")
    if "%H" not in fmt:
        v = re.split(r"[ T]", v, maxsplit=1)[0]
    else:
        v = v.replace("Z", "").split(".")[0].split("+")[0]
    return v


def parse_date(raw, fmt: str | None, candidates: list[str] | None = None) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    s = str(raw).strip()
    if not s or s.lower() in {"nan", "nat", "none"}:
        return None
    for f in ([fmt] if fmt else []) + (candidates or []):
        try:
            return datetime.strptime(_trim_time(s, f), f).date()
        except ValueError:
            continue
    raise ValueError(f"Datum nicht lesbar: '{raw}'")


# Buchungsarten-Synonyme (Kleinschreibung, ohne Umlaute-Varianten)
TYPE_SYNONYMS: list[tuple[TxType, tuple[str, ...]]] = [
    (TxType.SPLIT, ("split", "aktiensplit")),
    (TxType.CAPITAL_REPAYMENT, ("kapitalrückzahlung", "kapitalrueckzahlung", "einlagenrückzahlung",
                                "einlagenrueckzahlung", "return of capital", "capital repayment")),
    (TxType.AGE, ("ausschüttungsgleich", "ausschuettungsgleich", "age", "thesaurierung", "deemed distribution")),
    (TxType.DISTRIBUTION, ("ausschüttung", "ausschuettung", "distribution", "ertragsausschüttung", "fondsausschüttung")),
    (TxType.DIVIDEND, ("dividende", "dividend", "bardividende", "cash dividend")),
    (TxType.INTEREST, ("zinsen", "zins", "interest", "zinszahlung", "kupon", "coupon")),
    (TxType.TAX_REFUND, ("steuererstattung", "tax refund", "steuerkorrektur gutschrift")),
    (TxType.TAX, ("steuer", "tax", "kest", "quellensteuer", "withholding")),
    (TxType.FEE, ("gebühr", "gebuehr", "fee", "entgelt", "kosten", "provision")),
    (TxType.SELL, ("verkauf", "sell", "sale", "veräußerung", "veraeusserung", "tilgung")),
    (TxType.BUY, ("kauf", "buy", "purchase", "sparplan", "savings plan", "ankauf", "zeichnung", "erwerb")),
    (TxType.TRANSFER_IN, ("depoteingang", "einlieferung", "übertrag eingang", "transfer in")),
    (TxType.TRANSFER_OUT, ("depotausgang", "auslieferung", "übertrag ausgang", "transfer out")),
    (TxType.DEPOSIT, ("einzahlung", "deposit", "überweisung eingang", "gutschrift")),
    (TxType.WITHDRAWAL, ("auszahlung", "withdrawal", "überweisung ausgang")),
    (TxType.CORPORATE_ACTION, ("kapitalmaßnahme", "kapitalmassnahme", "corporate action", "spin-off", "spinoff",
                               "fusion", "umtausch")),
]


def parse_tx_type(raw) -> TxType | None:
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s or s == "nan":
        return None
    for t in TxType:
        if s == t.value.lower() or s == t.name.lower():
            return t
    for t, syns in TYPE_SYNONYMS:
        if any(syn == s for syn in syns):
            return t
    for t, syns in TYPE_SYNONYMS:
        if any(syn in s for syn in syns):
            return t
    return None
