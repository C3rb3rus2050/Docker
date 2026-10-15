"""PDF-Extraktion für Broker-Abrechnungen (lokal, ohne externe Dienste).

Die Extraktion ist heuristisch. Jedes Feld erhält eine Konfidenz; fehlende oder unsichere Pflichtfelder
führen dazu, dass das Dokument zur manuellen Prüfung vorgelegt wird. Ein Dokument wird nie als
„vollständig verarbeitet“ gemeldet, wenn wesentliche Werte fehlen oder widersprüchlich sind.

Regressionstests verwenden synthetische PDFs; öffentliche Broker-Textextrakte ergänzen den
Layoutabgleich (docs/BROKER-MUSTER.md). Originale und OCR-Ergebnisse können abweichen.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from ..models import TxType, isin_checksum_ok
from .parsing import parse_number

log = logging.getLogger(__name__)

PARSER_VERSION = 6
MAX_PAGES = 30
MAX_FUND_PAGES = 250
MAX_PDF_BYTES = 50 * 1024 * 1024


class PdfError(ValueError):
    pass


def _page_limit(count: int, first_page: str) -> None:
    if count <= MAX_PAGES:
        return
    fund = re.search(r'oekb|kontrollbank', first_page, re.I) and re.search(
        r'Kennzahlen ESt|Ertragsteuerliche Behandlung|BASISINFORMATION.*Anteilsgattung', first_page, re.I)
    from .broker_documents import document_profile
    profile = document_profile(first_page)
    summary = re.search(r'trade republic|scalable capital|baader bank', first_page, re.I) and profile and \
        profile.doc_type in ('Kontoauszug', 'Depotauszug', 'Jahressteuerbescheinigung', 'Kosteninformation')
    if (fund or summary) and count <= MAX_FUND_PAGES:
        return
    raise PdfError(f'PDF hat mehr als {MAX_FUND_PAGES if fund or summary else MAX_PAGES} Seiten; bitte aufteilen.')


def extract_text(data: bytes, engine: str = "auto") -> tuple[str, str]:
    """Liefert (Text, verwendete Engine). Es wird ausschließlich Text gelesen – keine Skripte, keine Formulare."""
    if not data.startswith(b"%PDF-"):
        raise PdfError("Keine PDF-Datei (Signatur %PDF- fehlt)")
    if len(data) > MAX_PDF_BYTES:
        raise PdfError("PDF ist zu groß")
    errors = []
    if engine in ("auto", "pdfplumber"):
        try:
            import pdfplumber

            with pdfplumber.open(io.BytesIO(data)) as pdf:
                _page_limit(len(pdf.pages), (pdf.pages[0].extract_text() or '') if pdf.pages else '')
                text = "\n".join((p.extract_text() or "") for p in pdf.pages)
            if text.strip():
                return text, "pdfplumber"
        except PdfError:
            raise
        except Exception as exc:  # beschädigte PDFs
            errors.append(f"pdfplumber: {exc}")
    if engine in ("auto", "pymupdf"):
        try:
            import pymupdf as fitz

            with fitz.open(stream=data, filetype="pdf") as doc:
                _page_limit(len(doc), doc[0].get_text() if len(doc) else '')
                text = "\n".join(page.get_text(sort=True) for page in doc)
            if text.strip():
                return text, "pymupdf"
        except PdfError:
            raise
        except Exception as exc:
            errors.append(f"pymupdf: {exc}")
    if errors:
        log.info("PDF-Text nicht extrahierbar: %s", "; ".join(errors))
    return "", "keine"


# --------------------------------------------------------------------------- #
NUM = r"[+-]?(?:\d{1,3}(?:[.,' ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)-?(?![\d.,])"
CUR = r"EUR|USD|CHF|GBP|CAD|JPY|DKK|SEK|NOK|AUD|NZD|HKD|SGD|PLN|CZK|HUF|CNY|ZAR|€|\$"
DATE = r"\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}[./]\d{4}"
UNIT = r"(?:Stk\.?|Stück(?:e)?|Pcs?\.?|Shares?|Units?|Anteile?)"
ISIN_RX = re.compile(r"\b([A-Z]{2}[A-Z0-9]{9}[0-9])\b")

TRADE_DATE_LABELS = ["Schlusstag", "Handelstag", "Ausführungstag", "Ausführungsdatum", "Ausführung", "Trade Date", "Execution Date", "Execution"]
INCOME_DATE_LABELS = ["Zahltag", "Zahlungstag", "Payment Date", "Pay Date", "Value Date", "Valuta", "Buchungsdatum", "Datum", "Abrechnungsdatum"]
GENERIC_DATE_LABELS = ["Buchungsdatum", "Datum", "Abrechnungsdatum", "Valuta"]
FEE_LABELS = ["Fremdkostenzuschlag", "Fremdkostenpauschale", "Abwicklungskostenpauschale", "Abwicklungsgebühr", "Ordergebühr", "Ordergebuehr", "Orderentgelt", "Provision", "Transaktionsgebühr",
              "Transaktionskosten", "Handelsplatzgebühr", "Börsengebühr", "Gebühr", "Fremde Spesen", "Spesen", "Commission", "Transaction Fee", "Gesamtgebühren", "Gebühren gesamt", "Total Fees", "Gebühren", "Fees", "Ordergebühren", "External cost surcharge"]
GROSS_LABELS_TRADE = ["Kurswert", "Ordervolumen", "Kaufpreis", "Verkaufspreis", "Gesamtkurswert", "Gross Amount", "Trade Value", "Market Value", "Consideration"]
GROSS_LABELS_INCOME = ["Bruttobetrag", "Brutto", "Dividende brutto", "Ausschüttung brutto", "Bruttoertrag",
                       "Zinsbetrag brutto", "Gross Dividend", "Gross Amount", "Gross Income", "Ertrag", "Dividende", "Ausschüttung", "Zinsen"]
TOTAL_LABELS = ["Endbetrag", "Ausmachender Betrag", "Zu Lasten", "Zu Gunsten", "Amount debited to account", "Amount credited to account", "Debit", "Credit", "Betrag zu Ihren Lasten",
                "Betrag zu Ihren Gunsten", "Settlement Amount", "Net Amount", "Nettobetrag", "Netto",
                "Gesamtbetrag", "Gesamt", "Total", "Gutschrift", "Belastung"]
WHT_LABELS = ["Quellensteuer", "Ausländische Quellensteuer", "US-Quellensteuer", "Withholding Tax",
              "Withholding Tax Amount"]
KEST_LABELS = ["Kapitalertragsteuer Österreich", "KESt Österreich", "KESt"]
GERMAN_TAX_LABELS = ["Kapitalertragsteuer", "Kapitalertragssteuer", "Solidaritätszuschlag", "Kirchensteuer", "Capital gains tax", "Solidarity surcharge"]


@dataclass
class Field:
    value: Any
    confidence: float
    source: str = ""


@dataclass
class Extraction:
    parser_version: int = PARSER_VERSION
    broker: str = "Unclassified"
    doc_type: str = "Unbekannt"
    tx_type: str | None = None
    fields: dict[str, Field] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    components: list[dict] = field(default_factory=list)
    classification: dict = field(default_factory=dict)
    engine: str = ""
    text_excerpt: str = ""
    complete: bool = False
    creates_transaction: bool = True
    checks: list[dict] = field(default_factory=list)   # Prüfbericht: name, result (ok|info|warn|error), detail, action

    def check(self, name: str, result: str, detail: str = "", action: str = "") -> None:
        self.checks.append({"name": name, "result": result, "detail": detail, "action": action})
        if result in ("warn", "error") and detail:
            self.warnings.append(detail)

    def value(self, name: str, default=None):
        f = self.fields.get(name)
        return f.value if f and f.value is not None else default

    def to_dict(self) -> dict:
        d = asdict(self)
        for k, f in d["fields"].items():
            if isinstance(f["value"], date):
                f["value"] = f["value"].isoformat()
        return d

    @property
    def status(self) -> str:
        if not self.creates_transaction:
            return "pruefen"
        if self.complete and not self.warnings:
            return "vollstaendig"
        if self.fields:
            return "unvollstaendig"
        return "fehlgeschlagen"


def _num(s: str, *, rate: bool = False) -> float | None:
    s = s.strip().rstrip("-") if not s.strip().endswith("-") else "-" + s.strip()[:-1]
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
    elif "," in s:
        dec = ","
    elif not rate and not s.lstrip("+-").startswith("0.") and re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
        dec = ","
    else:
        dec = "."
    try:
        return parse_number(s, dec)
    except ValueError:
        return None


def _date(s: str) -> date | None:
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _amount_line(label: str) -> re.Pattern:
    """Zeile 'Label … [WÄHRUNG] Betrag [WÄHRUNG]' – der letzte Betrag der Zeile zählt."""
    return re.compile(rf"(?im)^[ \t]*{re.escape(label)}\b[^\n]*?(?:^|[ \t:])(?:({CUR})[ \t]*)?({NUM})[ \t]*({CUR})?[ \t]*$")


def _match_amount(m: re.Match) -> tuple[float, str] | None:
    v = _num(m.group(2))
    if v is None:
        return None
    cur = (m.group(3) or m.group(1) or "").replace("€", "EUR").replace("$", "USD")
    return v, cur


def _labeled_amount(text: str, labels: list[str]) -> tuple[float, str, str] | None:
    """Sucht 'Label … Betrag Währung' (oder 'Währung Betrag'); liefert (Betrag, Währung, Label)."""
    for label in labels:
        for m in _amount_line(label).finditer(text):
            if re.search(r"(?i)\b(?:je|per|pro)\s+(?:anteil|aktie|stück|share|unit)|%", m.group(0)):
                continue
            r = _match_amount(m)
            if r:
                return r[0], r[1], label
    return None


def _all_labeled_amounts(text: str, labels: list[str]) -> list[tuple[float, str, str]]:
    out, seen = [], set()
    for label in labels:
        for m in _amount_line(label).finditer(text):
            if m.start() in seen:
                continue
            r = _match_amount(m)
            if r:
                seen.add(m.start())
                out.append((r[0], r[1], label))
    return out


def detect_broker(text: str) -> str:
    t = text.lower()
    if "trade republic" in t:
        return "TradeRepublic"
    if "scalable capital" in t or "scalable" in t and "baader" in t:
        return "ScalableCapital"
    if "kontrollbank" in t or "oekb" in t or "öekb" in t:
        return "OeKB"
    return "Unclassified"


def detect_type(text: str) -> tuple[str, str | None]:
    """Liefert (Dokumenttyp, Buchungsart)."""
    t = text.lower()
    from .broker_documents import document_profile
    profile = document_profile(text)
    if profile:
        return profile.doc_type, TxType.INTEREST.value if profile.policy == 'transaction' else None
    if re.search(r'(?im)^(?:WERTPAPIERABRECHNUNG|SECURITIES SETTLEMENT)\s+(?:ROUND UP|SAVEBACK)\s*$', text):
        return 'Kaufabrechnung', TxType.BUY.value
    if re.search(r'(?im)^Ausführung der Zeichnungsorder am\s+\d', text):
        return 'Kaufabrechnung', TxType.BUY.value
    # Scalable tables put the transaction type at the start of the position row.
    # This must precede words such as "Dividend" inside a security's name.
    if re.search(r'(?im)^(?:Wertpapierabrechnung|Contract note)\s*$', text) and re.search(
            r'(?im)^(?:Typ Wertpapier Anzahl Kurs Betrag|Type Security Quantity Price Amount)\s*$', text):
        types = {v.casefold() for v in re.findall(r'(?im)^(Kauf|Verkauf|Buy|Sell)\s+.+?\s+[\d.,]+\s+(?:Stk\.?|Pcs?\.?)\s', text)}
        if len(types) == 1:
            return ('Kaufabrechnung', TxType.BUY.value) if types & {'kauf', 'buy'} else ('Verkaufsabrechnung', TxType.SELL.value)
    execution = re.search(r"(?im)^(?:(?:Market|Limit|Stop)[ -]Order\s+)?(Buy|Sell|Kauf|Verkauf)\s+(?:on|am)\s+\d", text)
    savings = re.search(r"(?im)^\s*(?:Savings plan execution|Sparplanausführung)\s+(?:on|am)\s+\d", text)
    if execution:
        sell = execution.group(1).lower() in {"sell", "verkauf"}
        return ("Verkaufsabrechnung", TxType.SELL.value) if sell else ("Kaufabrechnung", TxType.BUY.value)
    if savings:
        return "Kaufabrechnung", TxType.BUY.value
    title = re.search(r"(?im)^\s*(?:wertpapierabrechnung\s*[:–-]?\s*|trade confirmation\s*[:–-]?\s*|transaction statement\s*[:–-]?\s*)(kauf|verkauf|buy|sell|purchase|sale)\b", text)
    if title and not re.search(r"jahressteuerbescheinigung|steuerbescheinigung|jahressteuerbericht|steuerreport", t):
        sell = title.group(1).lower() in {"verkauf", "sell", "sale"}
        return ("Verkaufsabrechnung", TxType.SELL.value) if sell else ("Kaufabrechnung", TxType.BUY.value)
    if re.search(r"jahressteuerbescheinigung|steuerbescheinigung|jahressteuerbericht|steuerreport", t):
        return "Jahressteuerbescheinigung", None
    if re.search(r"steuerliche behandlung|ausschüttungsgleiche erträge|meldefonds|steuerdaten.*fonds", t) and \
            ("oekb" in t or "kontrollbank" in t or "meldung" in t):
        return "OeKB-Fondsmeldung", None
    if re.search(r"kapitalrückzahlung|einlagenrückzahlung|return of capital", t):
        return "Ertragsabrechnung", TxType.CAPITAL_REPAYMENT.value
    if re.search(r'(?im)^(?:Fondsausschüttung|Fund Distribution)\s*$', text):
        return 'Ausschüttungsabrechnung', TxType.DISTRIBUTION.value
    if re.search(r"\bausschüttung\b|barausschüttung|ertragsausschüttung|distribution", t):
        return "Ausschüttungsabrechnung", TxType.DISTRIBUTION.value
    if re.search(r"dividende|dividend|bardividende", t):
        return "Dividendenabrechnung", TxType.DIVIDEND.value
    if re.search(r"zinsabrechnung|zinszahlung|kupon|\bzinsen\b|interest payment|coupon payment", t) and not re.search(r"\bkauf\b|\bverkauf\b", t):
        return "Ertragsabrechnung", TxType.INTEREST.value
    if re.search(r"\bverkauf\b|\bsell\b|veräußerung", t):
        return "Verkaufsabrechnung", TxType.SELL.value
    if re.search(r"\bkauf\b|\bbuy\b|sparplan|savings plan|sparplanausführung", t):
        return "Kaufabrechnung", TxType.BUY.value
    return "Unbekannt", None


REQUIRED = {
    TxType.BUY.value: ["trade_date", "isin", "quantity", "amount"],
    TxType.SELL.value: ["trade_date", "isin", "quantity", "amount"],
    TxType.DIVIDEND.value: ["trade_date", "isin", "amount"],
    TxType.DISTRIBUTION.value: ["trade_date", "isin", "amount"],
    TxType.CAPITAL_REPAYMENT.value: ["trade_date", "isin", "amount"],
    TxType.INTEREST.value: ["trade_date", "amount"],
}
FIELD_LABELS = {"trade_date": "Buchungsdatum", "isin": "ISIN", "quantity": "Stückzahl", "amount": "Bruttobetrag",
                "price": "Kurs", "fees": "Gebühren", "withholding_tax": "Quellensteuer", "currency": "Währung",
                "security_name": "Wertpapiername", "fx_rate": "Devisenkurs", "kest_at_eur": "österr. KESt",
                "total": "Endbetrag", "value_date": "Valuta / Wertstellung", "amount_eur": "Bruttobetrag in EUR",
                "fx_source": "Kursquelle", "price_currency": "Währung des Stückkurses", "total_currency": "Währung des Endbetrags",
                "income_per_unit": "Ertrag je Anteil", "fees_original": "Gebühren im Original",
                "withholding_tax_original": "Quellensteuer im Original", "kest_at_eur_original": "KESt im Original",
                "price_original": "Stückkurs im Original", "income_per_unit_currency": "Währung des Ertrags je Anteil",
                "document_fx_quote": "Umrechnung im Beleg", "withholding_country": "Quellenstaat"}


def _currency(value: str) -> str:
    return value.upper().replace("€", "EUR").replace("$", "USD")


def _normalize_text(text: str) -> str:
    from .text_patterns import normalize_document_text
    text = normalize_document_text(text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    amount_labels = FEE_LABELS + GROSS_LABELS_TRADE + GROSS_LABELS_INCOME + TOTAL_LABELS + WHT_LABELS + KEST_LABELS
    date_labels = TRADE_DATE_LABELS + INCOME_DATE_LABELS + GENERIC_DATE_LABELS + ["Ex-Tag", "Settlement Date"]
    labels = {label.casefold() for label in amount_labels + date_labels +
              ["ISIN", "Stückzahl", "Quantity", "Anzahl", "Kurs", "Price", "Wertpapierbezeichnung", "Security Name"]}
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if line.rstrip(":").casefold() in labels and i + 1 < len(lines) and lines[i + 1]:
            following = lines[i + 1]
            # Join only a standalone label with its immediate value, not entire tables.
            key = line.rstrip(":").casefold()
            is_amount = key in {label.casefold() for label in amount_labels}
            is_date = key in {label.casefold() for label in date_labels}
            valid_value = True
            if is_amount:
                valid_value = bool(re.fullmatch(rf"(?:{CUR})|(?:{CUR})?\s*{NUM}\s*(?:{CUR})?", following, re.I))
            elif is_date:
                valid_value = bool(re.match(DATE, following))
            elif key == "isin":
                valid_value = bool(ISIN_RX.fullmatch(following))
            if valid_value and following.rstrip(":").casefold() not in labels:
                line += " " + following
                i += 1
                if re.fullmatch(CUR, following, re.I) and i + 1 < len(lines) and re.fullmatch(NUM, lines[i + 1]):
                    line += " " + lines[i + 1]
                    i += 1
        out.append(line)
        i += 1
    normalized = "\n".join(out)
    split_position = re.compile(rf"(?im)^([^\n]+?)[ \t]+({NUM})[ \t]+({CUR})[ \t]*\n[ \t]*({NUM})[ \t]*{UNIT}[ \t]+({NUM})[ \t]+({CUR})[ \t]*$")
    def join_position(match):
        if _currency(match.group(3)) != _currency(match.group(6)):
            return match.group(0)
        return f"{match.group(1)} {match.group(4)} Stück {match.group(5)} {match.group(6)} {match.group(2)} {match.group(3)}"
    return split_position.sub(join_position, normalized)


def _document_fx(text: str, currency: str) -> tuple[Field | None, str | None]:
    """Normalize explicit currency equations and pairs to foreign currency per EUR."""
    if currency == "EUR":
        return None, None
    candidates = []
    for m in re.finditer(rf"(?i)(?<![\w.,])(1(?:[.,]0+)?)\s*([A-Z]{{3}})\s*=\s*({NUM})\s*([A-Z]{{3}})\b", text):
        left, right, rate = m.group(2).upper(), m.group(4).upper(), _num(m.group(3), rate=True)
        if rate and rate > 0 and {left, right} == {"EUR", currency}:
            candidates.append((rate if left == "EUR" else 1 / rate, m.group(0)))
    pair = rf"(?:EUR\s*/\s*{currency}|{currency}\s*/\s*EUR)"
    # Pair notation follows the existing broker convention: EUR/USD means USD per EUR.
    for pattern in (rf"(?i)({pair})[ \t:]*({NUM})(?![ \t]*(?:{CUR})(?!\w))", rf"(?i)(?<![\w.,])({NUM})[ \t]+({pair})\b"):
        for m in re.finditer(pattern, text):
            rate_text, pair_text = (m.group(2), m.group(1)) if "/" in m.group(1) else (m.group(1), m.group(2))
            rate = _num(rate_text, rate=True)
            if rate and rate > 0:
                candidates.append((rate if pair_text.upper().startswith("EUR") else 1 / rate, m.group(0)))
    if candidates:
        first = candidates[0][0]
        if any(abs(r - first) > max(0.000001, first * 0.0001) for r, _ in candidates[1:]):
            return None, "Widersprüchliche Devisenkurse im Dokument – Umrechnung manuell prüfen."
        return Field(first, 0.95, f"Belegkurs: {candidates[0][1]} → {currency} je EUR"), None
    m = re.search(rf"(?im)^\s*(?:Devisenkurs|Wechselkurs|Umrechnungskurs|Exchange Rate|FX Rate)\s*[: ]+({NUM})\s*$", text)
    if m and (rate := _num(m.group(1), rate=True)) and rate > 0:
        return Field(rate, 0.5, "Kurs ohne erkennbare Notierungsrichtung"), "Devisenkurs ohne Währungspaar – Notierungsrichtung prüfen."
    return None, None


def _convert(value: float, source: str, target: str, rate: float | None, main: str) -> float | None:
    if source == target:
        return value
    if not rate or {source, target} != {"EUR", main}:
        return None
    return value * rate if source == "EUR" else value / rate


def _apply_broker_tables(ex: Extraction, text: str) -> None:
    """Read explicit booking table columns; never treat a net payment as gross income."""
    f = ex.fields
    _apply_interest_layout(ex, text)
    english_positions = re.search(r'(?im)^(?:Type Security Quantity Price Amount|POSITION QUANTITY (?:AVERAGE RATE|PRICE|RATE) AMOUNT)\s*$', text)
    if english_positions and ex.tx_type in (TxType.BUY.value, TxType.SELL.value):
        rows = list(re.finditer(rf'(?im)^(.+?)\s+({NUM})\s+{UNIT}\s+({NUM})\s+({CUR})\s+({NUM})\s+({CUR})\s*$', text))
        if len(rows) == 1:
            row = rows[0]
            f['quantity'] = Field(abs(parse_number(row.group(2), '.')), .95, 'Quantity in English position table')
            f['price'] = Field(abs(parse_number(row.group(3), '.')), .95, 'Price in English position table')
            f['price_currency'] = Field(_currency(row.group(4)), .95, 'English position table')
            f['amount'] = Field(abs(parse_number(row.group(5), '.')), .95, 'Gross amount in English position table')
            f['currency'] = Field(_currency(row.group(6)), .95, 'English position table')
            f['security_name'] = Field(re.sub(r'^(?:Buy|Sell)\s+', '', row.group(1), flags=re.I), .9, 'English position table')
        elif len(rows) > 1:
            ex.check('Positionen eindeutig', 'warn', 'Mehrere Ausführungszeilen erkannt; keine einzelne Gesamtbuchung bestätigt.',
                     'Ausführungen im Original einzeln prüfen.')
    units = re.search(rf'(?im)^Units\s+({NUM})\s+(.+?)\s+({CUR})\s+({NUM})\s*$', text)
    if units and re.search(r'(?im)^Transaction Statement:', text):
        f['quantity'] = Field(abs(parse_number(units.group(1), '.')), .95, 'Units in Baader transaction statement')
        f['security_name'] = Field(units.group(2), .9, 'Baader transaction statement')
        f['price'] = Field(abs(parse_number(units.group(4), '.')), .95, 'Price in Baader transaction statement')
        f['price_currency'] = Field(_currency(units.group(3)), .95, 'Baader transaction statement')
    # Trade Republic booking row supplies the final settlement after the earlier overview total.
    booking = re.search(rf"(?im)^(?:VERRECHNUNGSKONTO|CLEARING ACCOUNT)[^\n]*(?:BETRAG|AMOUNT)\s*\n"
                        rf"[A-Z]{{2}}[A-Z0-9]+[ \t]+({DATE})[ \t]+({NUM})[ \t]+({CUR})[ \t]*$", text)
    if booking:
        day = _date(booking.group(1))
        bank_total = abs(_num(booking.group(2)))
        billing = re.search(r"(?ims)^(?:ABRECHNUNG|BILLING)\s*\n(.*?)(?=^(?:BUCHUNG|BOOKING)\s*$|\Z)", text)
        summary = _labeled_amount(billing.group(1), TOTAL_LABELS) if billing else None
        if summary and (summary[1] or _currency(booking.group(3))) == _currency(booking.group(3)) and abs(abs(summary[0]) - bank_total) > .02:
            ex.check("Endbetrag stimmt", "warn", "Endbetrag der Abrechnung weicht von der Buchungstabelle ab.",
                     "Beide Endbeträge im Original vergleichen.")
        f["total"] = Field(abs(_num(booking.group(2))), 0.95, "Endbetrag in der Buchungstabelle")
        f["total_currency"] = Field(_currency(booking.group(3)), 0.95, "Buchungstabelle")
        if day:
            f["value_date"] = Field(day, 0.95, "Wertstellung in der Buchungstabelle")
            if ex.tx_type in (TxType.DIVIDEND.value, TxType.DISTRIBUTION.value, TxType.INTEREST.value):
                f["trade_date"] = Field(day, 0.95, "Zahlungstag in der Buchungstabelle")
                ex.warnings = [w for w in ex.warnings if w != "Buchungsdatum nur heuristisch ermittelt"]
    # Older Baader PDFs put trade date and time on the row after the column headings.
    if ex.tx_type in (TxType.BUY.value, TxType.SELL.value):
        trade = re.search(rf"(?im)^(?:Handelsdatum[ \t]+Handelsuhrzeit|Trade Date[ \t]+Trade Time)[^\n]*\n[ \t]*({DATE})\b", text)
        if trade:
            f["trade_date"] = Field(_date(trade.group(1)), 0.95, "Handelsdatum in der Ausführungstabelle")
            ex.warnings = [w for w in ex.warnings if w != "Buchungsdatum nur heuristisch ermittelt"]
    if ex.broker != "ScalableCapital" or ex.tx_type not in (TxType.DIVIDEND.value, TxType.DISTRIBUTION.value, TxType.INTEREST.value):
        return
    header = re.search(r"(?im)^(?:Buchung Wertstellung Typ Betrag / Stk\. Berechtigte Anzahl Gesamt|"
                       r"Booking Value date Type Amount / pcs\. Entitled quantity Total amount)\s*$", text)
    if not header:
        return
    tail = text[header.end():]
    row_pattern = rf"(?im)^[ \t]*({DATE})[ \t]+({DATE})[ \t]+(?:Gutschrift|Credit)[ \t]+({NUM})[ \t]+({CUR})[ \t]+({NUM})[ \t]+({NUM})[ \t]+({CUR})[ \t]*$"
    rows = list(re.finditer(row_pattern, tail))
    if len(rows) != 1:
        ex.check("Ertragstabelle", "warn", "Ertragstabelle enthält keine eindeutige Einzelbuchung.", "Buchungszeilen einzeln prüfen.")
        return
    row = rows[0]
    f["trade_date"] = Field(_date(row.group(1)), 0.95, "Buchungsdatum in der Scalable-Ertragstabelle")
    f["value_date"] = Field(_date(row.group(2)), 0.95, "Wertstellung in der Scalable-Ertragstabelle")
    f["income_per_unit"] = Field(_num(row.group(3), rate=True), 0.95, "Betrag je Stück in der Ertragstabelle")
    f["income_per_unit_currency"] = Field(_currency(row.group(4)), 0.95, "Ertragstabelle")
    f["quantity"] = Field(_num(row.group(5)), 0.95, "Berechtigte Anzahl in der Ertragstabelle")
    f["amount"] = Field(abs(_num(row.group(6))), 0.95, "Brutto-Gutschrift vor den separat ausgewiesenen Steuern")
    f["currency"] = Field(_currency(row.group(7)), 0.95, "Währung der Brutto-Gutschrift")
    name = re.search(r"(?im)^(?:Berechtigtes Wertpapier|Entitled security)[ \t]+(.+)$", text)
    if name:
        f["security_name"] = Field(name.group(1).strip(), 0.95, "Berechtigtes Wertpapier")
    fx = re.search(rf"(?im)^([A-Z]{{3}}[ \t]*/[ \t]*[A-Z]{{3}})[ \t]+({NUM})[ \t]*$", tail)
    if fx:
        f["document_fx_quote"] = Field(fx.group(0).strip(), 0.95, "Umrechnung im Beleg; Bruttobetrag bereits in Abrechnungswährung")
    ex.warnings = [w for w in ex.warnings if w != "Buchungsdatum nur heuristisch ermittelt"]


def _apply_interest_layout(ex: Extraction, text: str) -> None:
    if ex.doc_type not in ('Zinsabrechnung', 'Sammelabrechnung'):
        return
    f = ex.fields
    # Preserve separate cash / money-market components rather than booking the sum.
    for m in re.finditer(rf'(?im)^(Cash|Geldmarkt)\s+(Zinsen|Interest|Dividende)\s+[^\n]*?({NUM})\s+({CUR})\s*$', text):
        ex.components.append({'Bestandteil': m.group(1), 'Art': m.group(2),
                              'Brutto': _num(m.group(3)), 'Währung': _currency(m.group(4))})
    if ex.doc_type == 'Sammelabrechnung':
        return
    gross = _labeled_amount(text, ['Besteuerungsgrundlage', 'Habenzinsen (HZ) (brutto)', 'Credit Interest (gross)', 'Habenzinsen', 'Gross interest', 'Zwischensumme'])
    if gross:
        f['amount'] = Field(abs(gross[0]), .95, f'Ausgewiesene Guthabenzinsen: {gross[2]}')
        if gross[1]:
            f['currency'] = Field(_currency(gross[1]), .95, 'Währung des Zinsbetrags')
        else:
            currency = re.search(r'(?im)^(?:Zinsberechnung: Betrag in|Calculation of Interest: Amount in)\s+([A-Z]{3})', text)
            if currency:
                f['currency'] = Field(currency.group(1), .95, 'Währungsangabe zur Zinsberechnung')
    elif ex.components and all(c['Bestandteil'] == 'Cash' for c in ex.components) and len(
            {c['Währung'] for c in ex.components}) == 1:
        f['amount'] = Field(round(sum(c['Brutto'] for c in ex.components), 8), .95, 'Summe der ausgewiesenen Cash-Zinsperioden')
        f['currency'] = Field(ex.components[0]['Währung'], .95, 'Cash-Zinsen')
    booking = re.search(rf'(?im)^[A-Z]{{2}}[A-Z0-9]{{8,}}\s+({DATE})\s+({NUM})\s+({CUR})\s*$', text)
    if booking:
        f['trade_date'] = Field(_date(booking.group(1)), .95, 'Zuflussdatum aus der Zins-Buchungstabelle')
        f['value_date'] = f['trade_date']
        f['total'] = Field(abs(_num(booking.group(2))), .95, 'Zinsgutschrift nach Steuern')
        f['total_currency'] = Field(_currency(booking.group(3)), .95, 'Zinsgutschrift')
        ex.warnings = [w for w in ex.warnings if w != 'Buchungsdatum nur heuristisch ermittelt']
    elif re.search(r'(?im)^Abschlussbuchung vom\s+', text):
        closing = re.search(rf'(?im)^Abschlussbuchung vom\s+({DATE})', text)
        if closing:
            f['trade_date'] = Field(_date(closing.group(1)), .95, 'Datum der Abschlussbuchung')
            ex.warnings = [w for w in ex.warnings if w != 'Buchungsdatum nur heuristisch ermittelt']
    elif ex.broker == 'ScalableCapital':
        paid = re.search(rf'(?i)Der Betrag wurde am\s+({DATE}).{{0,80}}gebucht', text)
        if paid:
            f['trade_date'] = Field(_date(paid.group(1)), .95, 'Ausdrücklich bestätigter Buchungstag')
        else:
            period = re.search(rf'(?im)^Zeitraum\s+({DATE})\s*[-–]\s*({DATE})', text)
            if period:
                f['trade_date'] = Field(_date(period.group(2)), .65, 'Periodenende; Zuflussdatum nicht separat bestätigt')
            ex.check('Zuflussdatum', 'warn', 'Rechnungsabschluss nennt keinen eindeutigen Buchungstag der Zinsen.',
                     'Zinsgutschrift mit dem Kontoauszug abgleichen.')


def _finish_fields(ex: Extraction, text: str, reference_fx: Field | None) -> None:
    f = ex.fields
    unit_amount = re.search(rf"(?im)^\s*(?:Dividende|Ausschüttung|Ertrag|Dividend|Distribution)\s+(?:je|pro|per)\s+(?:Aktie|Anteil|Stück|Share|Unit)\s*[: ]*(?:({CUR})\s*)?({NUM})\s*({CUR})?\s*$", text)
    if "currency" not in f and unit_amount and (unit_amount.group(1) or unit_amount.group(3)):
        f["currency"] = Field(_currency(unit_amount.group(1) or unit_amount.group(3)), 0.9, "Währung des Ertrags je Anteil")
    # Explicit labels are preferable to the nearby line heuristics.
    name = re.search(r"(?im)^\s*(?:Wertpapierbezeichnung|Wertpapiername|Security Name|Instrument Name)\s*[: ]+(.+)$", text)
    if name:
        value = ISIN_RX.sub("", name.group(1)).strip(" :|-")
        if 2 < len(value) < 120:
            f["security_name"] = Field(value, 0.9, name.group(0).strip())
    for label in ["Valuta", "Wertstellung", "Settlement Date", "Value Date"]:
        m = re.search(rf"(?i)\b{re.escape(label)}\b[^\n\d]{{0,20}}({DATE})", text)
        if m and (day := _date(m.group(1))):
            f["value_date"] = Field(day, 0.9, f"Label „{label}“")
            break
    if "currency" not in f:
        candidates = {_currency(m) for m in re.findall(rf"(?<!\w)({CUR})(?!\w)", text, re.I)}
        if len(candidates) == 1:
            f["currency"] = Field(candidates.pop(), 0.85, "einheitliche Währung im Dokument")
        elif candidates:
            ex.check("Währung eindeutig", "warn", "Mehrere Währungen ohne eindeutige Brutto-Zuordnung.", "Währung des Bruttobetrags auswählen.")
    cur = ex.value("currency")
    if not cur:
        ex.check("Währung", "error", "Währung nicht im Dokument gefunden.", "Währung aus dem Original ergänzen.")
        return
    fx, problem = _document_fx(text, cur)
    if fx:
        f["fx_rate"] = fx
        f["fx_source"] = Field(fx.source, fx.confidence, "Dokument")
    if problem:
        ex.check("Devisenkurs eindeutig", "warn", problem, "Kurs und Notierungsrichtung mit dem Original vergleichen.")
    if not fx and not problem and reference_fx and cur != "EUR":
        f["fx_rate"] = reference_fx
        f["fx_source"] = Field(reference_fx.source, reference_fx.confidence, "EZB")
        ex.check("Online-Umrechnung", "info", reference_fx.source, "Referenzkurs ist vorläufig; Bankkurs prüfen.")
    rate = ex.value("fx_rate")
    for key, labels, target in (("fees", FEE_LABELS, cur), ("withholding_tax", WHT_LABELS, cur),
                                ("kest_at_eur", KEST_LABELS, "EUR")):
        entries = _all_labeled_amounts(text, labels)
        if not entries:
            continue
        f.pop(key, None)
        values, descriptions = [], []
        missing_units = False
        for amount, source, label in entries:
            if not source and ex.value("total_currency", cur) != cur:
                missing_units = True
                ex.check(FIELD_LABELS[key], "warn", f"Währung bei „{label}“ fehlt in einer Abrechnung mit mehreren Währungen.",
                         "Währung der Gebühr bzw. Steuer im Original prüfen.")
            source = source or cur
            result = _convert(abs(amount), source, target, rate, cur)
            descriptions.append(f"{label}: {abs(amount):g} {source}")
            if result is None:
                ex.check(FIELD_LABELS[key], "warn", f"{label} in {source} kann noch nicht nach {target} umgerechnet werden.",
                         "Fehlenden Devisenkurs ergänzen oder Betrag manuell in die Buchungswährung umrechnen.")
            else:
                values.append(result)
        f[key + "_original"] = Field("; ".join(descriptions), 0.9, "Originalbeträge und Währungen")
        if len(values) == len(entries) and not missing_units:
            if key == "fees":
                summaries = [i for i, entry in enumerate(entries) if entry[2] in {"Fees", "Gebühren", "Gesamtgebühren", "Gebühren gesamt", "Total Fees"}]
                details = [i for i in range(len(entries)) if i not in summaries]
                if summaries and details:
                    summary = values[summaries[0]]
                    if abs(summary - sum(values[i] for i in details)) > 0.02 or len(summaries) > 1:
                        ex.check("Gebühren eindeutig", "warn", "Gebührensumme und einzelne Gebühren sind nicht eindeutig abgleichbar.",
                                 "Gebührensumme im Original prüfen.")
                    values = [summary]
            f[key] = Field(round(sum(values), 8), 0.9, "; ".join(descriptions) + f" → {target}")
    # Explicit country fields are stronger evidence than an ISIN prefix.
    countries = {"USA": "US", "UNITED STATES": "US", "DEUTSCHLAND": "DE", "GERMANY": "DE",
                 "SCHWEIZ": "CH", "SWITZERLAND": "CH", "FRANKREICH": "FR", "FRANCE": "FR",
                 "KANADA": "CA", "CANADA": "CA", "IRLAND": "IE", "IRELAND": "IE"}
    country = re.search(r"(?im)^\s*(?:Quellenstaat|Quellenland|Withholding Country|Tax Country)\s*[: ]+([A-ZÄÖÜ ]+)\s*$", text)
    if country:
        value = country.group(1).strip().upper()
        value = countries.get(value, value)
        if re.fullmatch(r"[A-Z]{2}", value):
            f["withholding_country"] = Field(value, 0.95, country.group(0).strip())
            ex.warnings = [w for w in ex.warnings if not w.startswith("Quellenstaat nur aus ISIN")]
    # Preserve contradictory gross totals instead of silently accepting the first one.
    labels = GROSS_LABELS_INCOME if ex.tx_type in (TxType.DIVIDEND.value, TxType.DISTRIBUTION.value, TxType.INTEREST.value) else GROSS_LABELS_TRADE
    candidates = _all_labeled_amounts(text, labels)
    direct_values = {round(abs(value), 8) for value, currency, label in candidates
                     if currency == cur and label not in {"Ertrag", "Dividende", "Ausschüttung", "Zinsen"}}
    if len(direct_values) > 1:
        ex.check("Bruttobetrag eindeutig", "warn", "Mehrere unterschiedliche Bruttobeträge in derselben Währung erkannt.",
                 "Einzelpositionen bzw. mehrfache Abrechnungen im Original prüfen.")
    if not ex.value("quantity"):
        quantity = re.search(rf"(?im)^\s*(?:Nominale|Stückzahl|Anzahl|Quantity|Units)\s*[: ]*(?:STK\.?\s*)?({NUM})", text)
        if quantity and (value := _num(quantity.group(1))) and value > 0:
            f["quantity"] = Field(value, 0.9, quantity.group(0).strip())
    if ex.tx_type in (TxType.DIVIDEND.value, TxType.DISTRIBUTION.value, TxType.INTEREST.value):
        per_unit = re.search(rf"(?im)^\s*(?:Dividende|Ausschüttung|Ertrag|Dividend|Distribution)\s+(?:je|pro|per)\s+(?:Aktie|Anteil|Stück|Share|Unit)\s*[: ]*(?:({CUR})\s*)?({NUM})\s*({CUR})?\s*$", text)
        if per_unit:
            f["income_per_unit"] = Field(_num(per_unit.group(2)), 0.9, per_unit.group(0).strip())
            unit_cur = _currency(per_unit.group(1) or per_unit.group(3) or cur)
            if not ex.value("amount") and ex.value("quantity") and unit_cur == cur:
                f["amount"] = Field(round(ex.value("quantity") * ex.value("income_per_unit"), 8), 0.65,
                                    "aus Stückzahl × Ertrag je Anteil berechnet")
    # Offer mathematical reconstructions, always visibly marked for review.
    a, q, price = ex.value("amount"), ex.value("quantity"), ex.value("price")
    if ex.tx_type in (TxType.BUY.value, TxType.SELL.value):
        if a and price and not q and ex.value("price_currency", cur) == cur:
            f["quantity"] = Field(a / price, 0.65, "aus Kurswert / Stückkurs berechnet")
        if a and q and not price:
            f["price"] = Field(a / q, 0.65, "aus Kurswert / Stückzahl berechnet")
        if not a and ex.value("total") is not None and "fees" in f:
            total_cur = ex.value("total_currency", cur)
            gross = _convert(ex.value("total"), total_cur, cur, rate, cur)
            # Sales may include additional tax deductions, so don't reconstruct them here.
            if gross is not None and ex.tx_type == TxType.BUY.value and gross > ex.value("fees"):
                f["amount"] = Field(gross - ex.value("fees"), 0.65, "aus Endbetrag minus ausgewiesenen Gebühren berechnet")
    if ex.value("currency") and ex.value("currency") != "EUR" and ex.value("fx_rate"):
        f["amount_eur"] = Field(ex.value("amount") / ex.value("fx_rate"), 0.8, ex.value("fx_source", "Belegkurs")) if ex.value("amount") is not None else Field(None, 0, "Brutto fehlt")
    # Different original currencies for price and amount must be reconciled before q × price checks.
    if price and ex.value("price_currency", cur) != cur:
        converted = _convert(price, ex.value("price_currency"), cur, rate, cur)
        if converted is not None:
            f["price_original"] = Field(f"{price:g} {ex.value('price_currency')}", 0.9, "Originalkurs")
            f["price"] = Field(converted, 0.85, f"Stückkurs umgerechnet nach {cur}")
        else:
            ex.check("Kurswährung", "warn", "Stückkurs und Bruttobetrag haben unterschiedliche Währungen ohne passenden Kurs.", "Umrechnung ergänzen.")


def parse_text(text: str, *, reference_fx: Field | None = None) -> Extraction:
    text = _normalize_text(text)
    ex = Extraction(text_excerpt=text[:4000])
    if not text.strip():
        ex.warnings.append("Kein Text extrahierbar (gescanntes PDF?). Lokale OCR ist nicht aktiviert – "
                           "bitte Werte manuell erfassen.")
        ex.missing = ["Text"]
        return ex
    ex.broker = detect_broker(text)
    ex.doc_type, ex.tx_type = detect_type(text)
    from .broker_documents import document_profile
    from .text_patterns import text_fingerprint
    profile = document_profile(text)
    explicit = re.search(r'(?im)^(?:Wertpapierabrechnung|Contract note|Transaction Statement|Trade confirmation|'
                         r'Dividendenabrechnung|Dividende|Dividend Statement|Fund Distribution|'
                         r'(?:Bar|Fonds)?ausschüttung|Ertragsabrechnung|Zinszahlung)\b', text)
    inferred = text_fingerprint(text) if not profile and not explicit else None
    if inferred:
        ex.classification = inferred
        ex.doc_type, ex.tx_type = inferred['doc_type'], inferred['tx_type']
        if ex.tx_type is None:
            ex.creates_transaction = False
        ex.check('Textmuster-Zuordnung', 'warn',
                 'Vorläufige Dokumentart ' + ex.doc_type + ': ' + '; '.join(inferred['evidence']),
                 'Überschrift fehlt oder ist nicht eindeutig. Dokumentart und Werte mit dem Original vergleichen.')
    else:
        ex.classification = {'doc_type': ex.doc_type, 'method': 'Überschrift/Abrechnung' if profile or explicit else 'Schlüsselwörter',
                             'confidence': .95 if profile or explicit else .5,
                             'evidence': [profile.explanation] if profile else ([explicit[0]] if explicit else [])}
    f = ex.fields

    # ISIN (mit Prüfziffer)
    isins = [m for m in ISIN_RX.findall(text) if isin_checksum_ok(m)]
    uniq = list(dict.fromkeys(isins))
    if len(uniq) == 1:
        f["isin"] = Field(uniq[0], 0.95, "ISIN mit gültiger Prüfziffer")
    elif len(uniq) > 1:
        f["isin"] = Field(uniq[0], 0.4, f"mehrere ISIN gefunden: {', '.join(uniq)}")
        ex.warnings.append(f"Mehrere ISIN im Dokument ({', '.join(uniq)}) – Zuordnung prüfen")

    # Positionszeile (z. B. Trade Republic): "<Name> 1 Stk. 497,40 EUR 497,40 EUR"
    pos = re.search(rf"(?im)^(.*?)(?<![\w.,])({NUM})[ \t]*{UNIT}[ \t]+({NUM})[ \t]*({CUR})"
                    rf"(?:[ \t]+({NUM})[ \t]*({CUR}))?[ \t]*$", text)
    # Baader/Scalable: "STK 2,000 <Name> <ISIN>"
    stk = re.search(rf"(?im)^[ \t]*STK\.?[ \t]+({NUM})[ \t]*(.*)$", text)

    # Wertpapiername
    name = ""
    if pos and len(pos.group(1).strip()) > 2:
        name = pos.group(1).strip()
    elif stk:
        name = ISIN_RX.sub("", stk.group(2)).strip()
    elif "isin" in f:
        m = re.search(rf"(?m)^(.*?){f['isin'].value}(.*)$", text)
        if m:
            name = re.sub(r"\bISIN\b[:\s]*", "", (m.group(1) or "").strip(" :|-")).strip()
            if len(name) < 3:
                lines = text[:m.start()].rstrip().splitlines()
                name = lines[-1].strip() if lines else ""
    name = re.sub(rf"(?<![\w.,])({NUM})\s*{UNIT}(?!\w).*", "", name).strip()
    if 2 < len(name) < 120 and not re.search(r"position|anzahl|isin|nominale", name, re.I):
        f["security_name"] = Field(name, 0.6, "Positionszeile/Text neben ISIN")

    # Datum – je Dokumentart die passende Angabe (Handelstag bzw. Zahltag; Ex-Tag zuletzt)
    income_doc = ex.tx_type in (TxType.DIVIDEND.value, TxType.DISTRIBUTION.value, TxType.INTEREST.value,
                                TxType.CAPITAL_REPAYMENT.value)
    if ex.tx_type in (TxType.BUY.value, TxType.SELL.value):
        m = re.search(rf"(?i)\b(?:Kauf|Verkauf|Buy|Sell|Savings plan execution|Sparplanausführung|ausgeführt|Ausführung)\b[^\n\d]{{0,25}}\b(?:am|on)\s+({DATE})", text)
        if m and _date(m.group(1)):
            f["trade_date"] = Field(_date(m.group(1)), 0.9, "Ausführung am …")
    labels = INCOME_DATE_LABELS if income_doc else TRADE_DATE_LABELS + GENERIC_DATE_LABELS
    for label in labels + ["Ex-Tag"]:
        if "trade_date" in f:
            break
        m = re.search(rf"(?i)\b{re.escape(label)}\b[^\n\d]{{0,30}}({DATE})", text)
        if m and _date(m.group(1)):
            conf = 0.6 if label == "Ex-Tag" else 0.9
            f["trade_date"] = Field(_date(m.group(1)), conf, f"Label „{label}“")
            if label == "Ex-Tag":
                ex.warnings.append("Nur Ex-Tag gefunden – Zahltag (Zufluss) prüfen")
    if "trade_date" not in f:
        m = re.search(DATE, text)
        if m and _date(m.group(0)):
            f["trade_date"] = Field(_date(m.group(0)), 0.5, "erstes Datum im Dokument")
            ex.warnings.append("Buchungsdatum nur heuristisch ermittelt")

    # Stückzahl & Kurs
    if pos:
        f["quantity"] = Field(abs(_num(pos.group(2)) or 0), 0.9, "Positionszeile")
        f["price"] = Field(_num(pos.group(3), rate=True), 0.85, "Positionszeile")
        f["currency"] = Field(_currency(pos.group(4)), 0.85, "Positionszeile")
        f["price_currency"] = Field(_currency(pos.group(4)), 0.85, "Positionszeile")
    elif stk and _num(stk.group(1)):
        f["quantity"] = Field(abs(_num(stk.group(1))), 0.9, "STK-Angabe")
    else:
        m = re.search(rf"(?i)(?<![\w.,])({NUM})[ \t]*{UNIT}(?!\w)", text) or \
            re.search(rf"(?i)\b(?:Stück|Anzahl|Stückzahl|Quantity|Units)\b[: \t]*({NUM})", text)
        if m and _num(m.group(1)):
            f["quantity"] = Field(abs(_num(m.group(1))), 0.85, "Stück-Angabe")
    if "price" not in f:
        m = re.search(rf"(?im)\b(?:Kurs|Ausführungskurs|Preis|Durchschnittskurs|Price|Unit Price)\b[ \t:]*(?:({CUR})[ \t]*)?({NUM})[ \t]*({CUR})?", text)
        if m and (m.group(1) or m.group(3)) and _num(m.group(2), rate=True):
            f["price"] = Field(_num(m.group(2), rate=True), 0.8, "Kurs-Angabe")
            f["currency"] = Field(_currency(m.group(3) or m.group(1)), 0.8, "Währung beim Kurs")
            f["price_currency"] = f["currency"]

    # Beträge
    income = ex.tx_type in (TxType.DIVIDEND.value, TxType.DISTRIBUTION.value, TxType.INTEREST.value,
                            TxType.CAPITAL_REPAYMENT.value)
    gross = _labeled_amount(text, GROSS_LABELS_INCOME if income else GROSS_LABELS_TRADE)
    if gross:
        f["amount"] = Field(abs(gross[0]), 0.85, f"Label „{gross[2]}“")
        if gross[1]:
            f["currency"] = Field(gross[1], 0.8, f"Währung bei „{gross[2]}“")
    elif pos and pos.group(5):
        f["amount"] = Field(abs(_num(pos.group(5)) or 0), 0.85, "Betrag in der Positionszeile")
        f["currency"] = Field(_currency(pos.group(6)), 0.85, "Positionszeile")
    elif not income and "quantity" in f and "price" in f and f["price"].value:
        f["amount"] = Field(round(f["quantity"].value * f["price"].value, 2), 0.6, "Stück × Kurs")
        ex.warnings.append("Kurswert aus Stück × Kurs berechnet – nicht im Dokument gefunden")
    total = _labeled_amount(text, TOTAL_LABELS)
    if total:
        f["total"] = Field(abs(total[0]), 0.8, f"Label „{total[2]}“")
        if total[1]:
            f["total_currency"] = Field(total[1], 0.9, f"Währung bei „{total[2]}“")

    fees = _all_labeled_amounts(text, FEE_LABELS)
    if fees:
        f["fees"] = Field(round(sum(abs(v) for v, _, _ in fees), 2), 0.8, ", ".join(lbl for _, _, lbl in fees))
    wht = _all_labeled_amounts(text, WHT_LABELS)
    if wht:
        f["withholding_tax"] = Field(round(sum(abs(v) for v, _, _ in wht), 2), 0.8, ", ".join(l for *_, l in wht))
        m = re.search(r"(?i)quellensteuer[^\n]*?\b(USA|US|Deutschland|DE|Schweiz|CH|Frankreich|FR|Niederlande|NL|"
                      r"Kanada|CA|Vereinigtes Königreich|GB|Irland|IE|Japan|JP)\b", text)
        country_map = {"USA": "US", "DEUTSCHLAND": "DE", "SCHWEIZ": "CH", "FRANKREICH": "FR", "NIEDERLANDE": "NL",
                       "KANADA": "CA", "VEREINIGTES KÖNIGREICH": "GB", "IRLAND": "IE", "JAPAN": "JP"}
        if m:
            c = m.group(1).upper()
            f["withholding_country"] = Field(country_map.get(c, c), 0.7, "Text bei Quellensteuer")
        elif "isin" in f:
            f["withholding_country"] = Field(f["isin"].value[:2], 0.4, "aus ISIN-Länderpräfix abgeleitet")
            ex.warnings.append("Quellenstaat nur aus ISIN-Präfix abgeleitet – Sitzstaat prüfen")
    kest = _all_labeled_amounts(text, KEST_LABELS)
    if kest:
        f["kest_at_eur"] = Field(round(sum(abs(v) for v, _, _ in kest), 2), 0.7, ", ".join(l for *_, l in kest))

    _apply_broker_tables(ex, text)
    _finish_fields(ex, text, reference_fx)
    _run_checks(ex, text)
    return ex


SPECIAL_DOCS = [
    # (Muster, Dokumenttyp, erzeugt Buchung?, Ergebnis, Erklärung, Was tun)
    (r"\bstorno\b|stornierung|stornobuchung|\bcancellation\b", "Storno", False, "error",
     "Storno-Abrechnung: hebt eine frühere Buchung auf.",
     "Ursprüngliche Buchung unter „Transaktionen“ suchen und löschen bzw. korrigieren (mit Begründung)."),
    (r"aktiensplit|\bsplit\b|spin-?off|abspaltung|fusion|verschmelzung|umtausch|bezugsrecht|kapitalerhöhung"
     r"|kapitalmaßnahme|reverse split|zusammenlegung", "Kapitalmaßnahme", False, "error",
     "Kapitalmaßnahme (Split, Abspaltung, Umtausch …): verändert Bestand bzw. Anschaffungskosten.",
     "Unter „Transaktionen“ als Split (mit Verhältnis) oder Kapitalmaßnahme erfassen; steuerliche Folgen prüfen."),
    (r"steuerkorrektur|steuerausgleich|steuerliche korrektur|nachträgliche steuer", "Steuerkorrektur", False, "warn",
     "Steuerkorrektur: ändert früher einbehaltene Steuern.",
     "Betroffene Buchung suchen und Steuerbeträge (Quellensteuer/KESt) manuell anpassen."),
    (r"depotauszug|kontoauszug|vermögensübersicht|kosteninformation|ex-ante|ex-post|basisinformationsblatt"
     r"|kundeninformation|wesentliche anlegerinformation", "Informationsdokument", False, "info",
     "Informations- bzw. Übersichtsdokument ohne einzelne Buchung.",
     "Keine Aktion nötig – Dokument bleibt als Beleg abgelegt."),
]


def _run_checks(ex: Extraction, text: str) -> None:
    """Prüfbericht: Vollständigkeit, Plausibilität und Sonderfälle. Fehler/Warnungen verhindern die
    automatische Übernahme – das Dokument wird dann zur manuellen Prüfung vorgelegt."""
    t = text.lower()
    f = ex.fields
    from .broker_documents import document_profile
    profile = document_profile(text)
    if profile and profile.policy != 'transaction':
        ex.doc_type = profile.doc_type
        ex.tx_type = None
        ex.creates_transaction = False
        severity = 'info' if profile.policy == 'info' else ('error' if profile.doc_type in ('Storno', 'Kapitalmaßnahme') else 'warn')
        ex.check('Dokumentart', severity, profile.explanation, profile.action)
        ex.missing = []
        ex.complete = False
        return
    # Sonderdokumente zuerst
    head = t[:600]  # Dokumentkopf: Titel/Betreff
    for rx, dtype, creates, result, detail, action in SPECIAL_DOCS:
        # Informationsdokumente nur anhand des Dokumentkopfs (sie enthalten oft Wörter wie „Kauf“)
        hit = re.search(rx, head) if dtype == "Informationsdokument" else re.search(rx, t)
        if hit:
            ex.doc_type = dtype
            ex.creates_transaction = creates
            ex.check("Dokumentart", result, detail, action)
            break
    if ex.doc_type in ("Jahressteuerbescheinigung", "OeKB-Fondsmeldung"):
        ex.creates_transaction = False
        ex.check("Dokumentart", "info", f"{ex.doc_type}: keine einzelne Buchung.",
                 "Als Beleg verknüpfen (Seite Dokumente) bzw. Werte unter „Fonds & OeKB“ erfassen.")
    if not ex.creates_transaction:
        ex.missing = []
        ex.complete = False
        return
    if ex.tx_type is None:
        ex.check("Buchungsart", "error", "Buchungsart (Kauf, Verkauf, Dividende …) nicht erkannt.",
                 "Im Prüfformular die richtige Buchungsart auswählen.")
    else:
        ex.check("Buchungsart", "ok", f"{ex.tx_type} ({ex.doc_type})")

    # Pflichtfelder
    req = REQUIRED.get(ex.tx_type or "", [])
    ex.missing = [FIELD_LABELS[r] for r in req if ex.value(r) is None]
    for r in req:
        label = FIELD_LABELS[r]
        fld = f.get(r)
        if fld is None or fld.value is None:
            ex.check(label, "error", f"{label} nicht im Dokument gefunden.",
                     f"{label} aus dem Original ablesen und im Prüfformular eintragen.")
        elif fld.confidence < 0.8:
            ex.check(label, "warn", f"{label} nur unsicher erkannt ({fld.source}).",
                     f"{label} mit dem Original vergleichen.")
        else:
            ex.check(label, "ok", f"{fld.value} ({fld.source})")

    # ISIN-Eindeutigkeit (Prüfziffer wird bereits bei der Erkennung verlangt)
    if "isin" in f and f["isin"].confidence < 0.8:
        ex.check("ISIN eindeutig", "error", f["isin"].source, "Richtige ISIN im Prüfformular wählen.")

    # Datum plausibel
    d = ex.value("trade_date")
    if d:
        if d > date.today():
            ex.check("Datum plausibel", "error", f"Datum {d.isoformat()} liegt in der Zukunft.",
                     "Datum im Original prüfen (Lesefehler?).")
        elif d.year < 2000:
            ex.check("Datum plausibel", "warn", f"Datum {d.isoformat()} ungewöhnlich alt.", "Datum prüfen.")

    a, q, p = ex.value("amount"), ex.value("quantity"), ex.value("price")
    if a is not None and a <= 0:
        ex.check("Betrag", "error", "Betrag ist 0 oder negativ.", "Bruttobetrag im Original prüfen.")
    if ex.tx_type in (TxType.BUY.value, TxType.SELL.value):
        if q is not None and q <= 0:
            ex.check("Stückzahl", "error", "Stückzahl ist 0.", "Stückzahl im Original prüfen.")
        if q and p and a:
            if abs(q * p - a) > max(0.02, 0.01 * a):
                ex.check("Stück × Kurs = Kurswert", "warn", f"Stück × Kurs ({q * p:.2f}) weicht vom Kurswert "
                         f"({a:.2f}) ab.", "Stückzahl, Kurs und Kurswert im Original vergleichen.")
            else:
                ex.check("Stück × Kurs = Kurswert", "ok", f"{q:g} × {p:g} ≈ {a:.2f}")
    fees = ex.value("fees") or 0
    if a and fees > max(5.0, 0.05 * a):
        ex.check("Gebühren plausibel", "warn", f"Gebühren {fees:.2f} sind hoch im Verhältnis zum Betrag {a:.2f}.",
                 "Prüfen, ob eine Steuer oder ein anderer Betrag als Gebühr erkannt wurde.")

    # Reconcile all operands in the transaction currency first, then the settlement currency.
    tot, fx, cur = ex.value("total"), ex.value("fx_rate"), ex.value("currency")
    wht, kest = ex.value("withholding_tax") or 0, ex.value("kest_at_eur") or 0
    if a is not None and tot is not None:
        total_cur = ex.value("total_currency", cur)
        reference = str(ex.value("fx_source", "")).startswith("EZB-Referenzkurs")
        kest_cur = _convert(kest, "EUR", cur, fx, cur) if kest else 0
        expected = None
        if kest_cur is not None:
            if ex.tx_type == TxType.BUY.value:
                expected = a + fees
            elif ex.tx_type == TxType.SELL.value:
                expected = a - fees - kest_cur
            elif ex.tx_type in (TxType.DIVIDEND.value, TxType.DISTRIBUTION.value, TxType.INTEREST.value, TxType.CAPITAL_REPAYMENT.value):
                expected = a - wht - fees - kest_cur
        exp = _convert(expected, cur, total_cur, fx, cur) if expected is not None else None
        if exp is None or (reference and total_cur != cur):
            ex.check("Endbetrag stimmt", "info", "Währungsübergreifender Abgleich benötigt den Bankkurs; ein EZB-Referenzkurs ersetzt ihn nicht.")
        elif abs(exp - tot) > max(0.02, 0.005 * tot):
            ex.check("Endbetrag stimmt", "warn", f"Berechneter Endbetrag {exp:.2f} {total_cur}, laut Dokument {tot:.2f} {total_cur}.",
                     "Gebühren, Steuern und Beträge im Original prüfen.")
        else:
            ex.check("Endbetrag stimmt", "ok", f"Berechneter Endbetrag {exp:.2f} ≈ {tot:.2f} {total_cur}")
    elif a and ex.tx_type in (TxType.BUY.value, TxType.SELL.value):
        ex.check("Endbetrag stimmt", "info", "Kein Endbetrag gefunden – Abgleich nicht möglich.")

    # Währung
    cur = ex.value("currency")
    if cur and cur != "EUR":
        if fx:
            ex.check("Devisenkurs", "info" if str(ex.value("fx_source", "")).startswith("EZB-Referenzkurs") else "ok",
                     f"{cur}: {fx} je EUR – {ex.value('fx_source', 'laut Dokument')}")
        else:
            ex.check("Devisenkurs", "info", f"Betrag in {cur} ohne Devisenkurs im Dokument.",
                     "Wird automatisch mit dem EZB-Referenzkurs ergänzt (abschaltbar).")

    # Quellensteuer
    if wht:
        if a and wht > a:
            ex.check("Quellensteuer plausibel", "error", f"Quellensteuer {wht:.2f} größer als Bruttobetrag {a:.2f}.",
                     "Beträge im Original prüfen.")
        elif a and wht / a > 0.355:
            ex.check("Quellensteuer plausibel", "warn", f"Quellensteuersatz {wht / a:.1%} ungewöhnlich hoch.",
                     "Prüfen; nicht anrechenbare Teile ggf. im Quellenstaat zurückfordern.")
        elif a:
            ex.check("Quellensteuer plausibel", "ok", f"{wht / a:.1%} vom Bruttobetrag")
        if not ex.value("withholding_country"):
            ex.check("Quellenstaat", "warn", "Quellenstaat nicht erkannt.", "Land (ISO-2, z. B. US) eintragen.")

    # Deutsche Abzugsteuern (bei österreichischer Ansässigkeit nicht vorgesehen)
    german_text = "\n".join(line for line in text.splitlines() if not re.search(r"österreich|austria", line, re.I))
    german = [g for g in _all_labeled_amounts(german_text, GERMAN_TAX_LABELS) if g[0]]
    german = [g for g in german if g[0] != 0]
    if german:
        names = ", ".join(sorted({g[2] for g in german}))
        ex.check("Deutsche Steuer", "error", f"Deutsche Abzugsteuer einbehalten ({names}: "
                 f"{sum(abs(g[0]) for g in german):.2f}). Sie ist keine österreichische KESt.",
                 "Beim Broker die österreichische Ansässigkeit prüfen; Erstattung beantragen. Betrag nicht als KESt "
                 "erfassen.")
    if kest:
        ex.check("Österreichische KESt", "ok", f"{kest:.2f} einbehalten")

    errors = [c for c in ex.checks if c["result"] == "error"]
    ex.complete = bool(ex.tx_type and not ex.missing and not ex.warnings and not errors)


def _ocr_text(data: bytes) -> str:
    import pymupdf
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            if len(doc) > 8:
                raise PdfError("Lokale OCR ist auf 8 Seiten je Dokument begrenzt; bitte PDF aufteilen.")
            pages = []
            for page in doc:
                if page.rect.width * page.rect.height > 2_000_000:
                    raise PdfError("PDF-Seite für lokale OCR zu groß.")
                tp = page.get_textpage_ocr(language="deu+eng", dpi=200, full=True)
                pages.append(page.get_text(textpage=tp, sort=True))
            return "\n".join(pages)
    except PdfError:
        raise
    except Exception as exc:
        raise PdfError("Lokale OCR nicht verfügbar oder fehlgeschlagen. Tesseract mit deutschen und englischen Sprachdaten prüfen.") from exc


def extract_pdf(data: bytes, engine: str = "auto", *, fx_service=None, allow_download: bool = False,
                ocr_enabled: bool = False) -> Extraction:
    text, used = extract_text(data, engine)
    ex = parse_text(text)
    if engine == "auto" and ex.missing and text.strip():
        alternative, alt_used = extract_text(data, "pymupdf")
        other = parse_text(alternative)
        # Choose a whole extraction; never combine conflicting readings across engines.
        if len(other.missing) < len(ex.missing) and not any(c["result"] == "error" and c["name"] != "Bruttobetrag" for c in other.checks):
            ex, text, used = other, alternative, alt_used
    if ocr_enabled and (not text.strip() or (ex.creates_transaction and ex.missing)):
        try:
            ocr_text = _ocr_text(data)
            other = parse_text(ocr_text)
            if not text.strip() or len(other.missing) < len(ex.missing):
                text, ex, used = ocr_text, other, "Tesseract (lokal)"
        except PdfError as exc:
            ex.check("Lokale OCR", "info", str(exc), "Original prüfen bzw. Werte manuell erfassen.")
    cur, day = ex.value("currency"), ex.value("trade_date")
    if (fx_service is not None and cur and cur != "EUR" and day and day <= date.today() and not ex.value("fx_rate")
            and ex.creates_transaction and ex.tx_type and ex.fields["trade_date"].confidence >= 0.8
            and ex.fields["currency"].confidence >= 0.8
            and not any(c["name"] == "Devisenkurs eindeutig" for c in ex.checks)):
        from ..fx import FxError
        try:
            rates = fx_service.rates(allow_download=allow_download, needed_until=day)
            hit = rates.lookup(cur, day) if rates else None
            if hit:
                rate, rate_day = hit
                source = (f"EZB-Referenzkurs {cur} {rate} vom {rate_day.isoformat()} "
                          f"(Buchungsdatum {day.isoformat()}; {fx_service.url})")
                ex = parse_text(text, reference_fx=Field(rate, 0.8, source))
            else:
                ex.check("Online-Umrechnung", "info", f"Kein EZB-Referenzkurs für {cur} am {day.isoformat()} verfügbar.")
        except FxError as exc:
            ex.check("Online-Umrechnung", "info", str(exc), "Kurs später erneut abrufen oder manuell ergänzen.")
    if used == "Tesseract (lokal)":
        ex.check("Lokale OCR", "warn", "Werte aus gescanntem Dokument erkannt; mögliche Zeichenfehler mit dem Original vergleichen.",
                 "ISIN, Datum und sämtliche Beträge vor Übernahme kontrollieren.")
        ex.complete = False
    ex.engine = used
    return ex
