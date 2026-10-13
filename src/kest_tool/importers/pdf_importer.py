"""PDF-Extraktion für Broker-Abrechnungen (lokal, ohne externe Dienste).

Die Extraktion ist heuristisch. Jedes Feld erhält eine Konfidenz; fehlende oder unsichere Pflichtfelder
führen dazu, dass das Dokument zur manuellen Prüfung vorgelegt wird. Ein Dokument wird nie als
„vollständig verarbeitet“ gemeldet, wenn wesentliche Werte fehlen oder widersprüchlich sind.

Getestet ist die Extraktion ausschließlich mit synthetischen PDFs im Stil deutscher Broker-Abrechnungen
(siehe tests/kest). Echte Abrechnungen von Trade Republic/Scalable Capital können abweichen.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from ..models import TxType, isin_checksum_ok
from .parsing import parse_number

log = logging.getLogger(__name__)

MAX_PAGES = 30
MAX_PDF_BYTES = 50 * 1024 * 1024


class PdfError(ValueError):
    pass


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
                text = "\n".join((p.extract_text() or "") for p in pdf.pages[:MAX_PAGES])
            if text.strip():
                return text, "pdfplumber"
        except Exception as exc:  # beschädigte PDFs
            errors.append(f"pdfplumber: {exc}")
    if engine in ("auto", "pymupdf"):
        try:
            import pymupdf as fitz

            with fitz.open(stream=data, filetype="pdf") as doc:
                text = "\n".join(doc[i].get_text() for i in range(min(len(doc), MAX_PAGES)))
            if text.strip():
                return text, "pymupdf"
        except Exception as exc:
            errors.append(f"pymupdf: {exc}")
    if errors:
        log.info("PDF-Text nicht extrahierbar: %s", "; ".join(errors))
    return "", "keine"


# --------------------------------------------------------------------------- #
NUM = r"-?\d{1,3}(?:[.  ]\d{3})*(?:,\d+)?|-?\d+(?:,\d+)?|-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?"
CUR = r"EUR|USD|CHF|GBP|CAD|JPY|DKK|SEK|NOK|AUD|€|\$"
DATE = r"\d{1,2}\.\d{1,2}\.\d{4}|\d{4}-\d{2}-\d{2}"
ISIN_RX = re.compile(r"\b([A-Z]{2}[A-Z0-9]{9}[0-9])\b")

DATE_LABELS = ["Schlusstag", "Handelstag", "Ausführungstag", "Ausführung", "Buchungsdatum", "Zahltag", "Valuta",
               "Ex-Tag", "Datum", "Ausführungsdatum", "Abrechnungsdatum"]
FEE_LABELS = ["Fremdkostenzuschlag", "Ordergebühr", "Ordergebuehr", "Orderentgelt", "Provision", "Transaktionsgebühr",
              "Transaktionskosten", "Handelsplatzgebühr", "Börsengebühr", "Gebühr", "Fremde Spesen", "Spesen"]
GROSS_LABELS_TRADE = ["Kurswert", "Ordervolumen", "Kaufpreis", "Verkaufspreis", "Gesamtkurswert"]
GROSS_LABELS_INCOME = ["Bruttobetrag", "Brutto", "Dividende brutto", "Ausschüttung brutto", "Bruttoertrag",
                       "Zinsbetrag brutto", "Ertrag", "Dividende", "Ausschüttung", "Zinsen"]
TOTAL_LABELS = ["Gesamt", "Endbetrag", "Ausmachender Betrag", "Gutschrift", "Belastung", "Betrag zu Ihren Lasten",
                "Betrag zu Ihren Gunsten", "Total"]
WHT_LABELS = ["Quellensteuer", "Ausländische Quellensteuer", "US-Quellensteuer", "Withholding Tax"]
KEST_LABELS = ["Kapitalertragsteuer Österreich", "KESt Österreich", "KESt", "Kapitalertragsteuer"]


@dataclass
class Field:
    value: Any
    confidence: float
    source: str = ""


@dataclass
class Extraction:
    broker: str = "Unclassified"
    doc_type: str = "Unbekannt"
    tx_type: str | None = None
    fields: dict[str, Field] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    engine: str = ""
    text_excerpt: str = ""
    complete: bool = False
    creates_transaction: bool = True

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


def _num(s: str) -> float | None:
    s = s.strip()
    dec = "," if re.search(r",\d{1,}$", s) or ("," in s and "." in s and s.rfind(",") > s.rfind(".")) else "."
    if dec == "." and re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
        dec = ","
    try:
        return parse_number(s, dec)
    except ValueError:
        return None


def _date(s: str) -> date | None:
    m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
    try:
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return None


def _labeled_amount(text: str, labels: list[str]) -> tuple[float, str, str] | None:
    """Sucht 'Label ... Betrag Währung' in derselben Zeile; liefert (Betrag, Währung, Label)."""
    for label in labels:
        rx = re.compile(rf"(?im)^.*?\b{re.escape(label)}\b[^\n\d-]*?(?:\(?[^\n]*?\)?\s)?({NUM})\s*({CUR})?\s*$")
        for m in rx.finditer(text):
            v = _num(m.group(1))
            if v is not None:
                cur = (m.group(2) or "").replace("€", "EUR").replace("$", "USD")
                return v, cur, label
    return None


def _all_labeled_amounts(text: str, labels: list[str]) -> list[tuple[float, str, str]]:
    out = []
    for label in labels:
        rx = re.compile(rf"(?im)^\s*{re.escape(label)}\b[^\n\d-]*({NUM})\s*({CUR})?\s*$")
        for m in rx.finditer(text):
            v = _num(m.group(1))
            if v is not None:
                out.append((v, (m.group(2) or "").replace("€", "EUR"), label))
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
    if re.search(r"jahressteuerbescheinigung|steuerbescheinigung|jahressteuerbericht|steuerreport", t):
        return "Jahressteuerbescheinigung", None
    if re.search(r"steuerliche behandlung|ausschüttungsgleiche erträge|meldefonds|steuerdaten.*fonds", t) and \
            ("oekb" in t or "kontrollbank" in t or "meldung" in t):
        return "OeKB-Fondsmeldung", None
    if re.search(r"kapitalrückzahlung|einlagenrückzahlung|return of capital", t):
        return "Ertragsabrechnung", TxType.CAPITAL_REPAYMENT.value
    if re.search(r"\bausschüttung\b|ertragsausschüttung|distribution", t):
        return "Ausschüttungsabrechnung", TxType.DISTRIBUTION.value
    if re.search(r"dividende|dividend|bardividende", t):
        return "Dividendenabrechnung", TxType.DIVIDEND.value
    if re.search(r"zinsabrechnung|zinszahlung|kupon|\bzinsen\b", t) and not re.search(r"\bkauf\b|\bverkauf\b", t):
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
                "total": "Endbetrag"}


def parse_text(text: str) -> Extraction:
    ex = Extraction(text_excerpt=text[:4000])
    if not text.strip():
        ex.warnings.append("Kein Text extrahierbar (gescanntes PDF?). Lokale OCR ist nicht aktiviert – "
                           "bitte Werte manuell erfassen.")
        ex.missing = ["Text"]
        return ex
    ex.broker = detect_broker(text)
    ex.doc_type, ex.tx_type = detect_type(text)
    f = ex.fields

    # ISIN (mit Prüfziffer)
    isins = [m for m in ISIN_RX.findall(text) if isin_checksum_ok(m)]
    uniq = list(dict.fromkeys(isins))
    if len(uniq) == 1:
        f["isin"] = Field(uniq[0], 0.95, "ISIN mit gültiger Prüfziffer")
    elif len(uniq) > 1:
        f["isin"] = Field(uniq[0], 0.4, f"mehrere ISIN gefunden: {', '.join(uniq)}")
        ex.warnings.append(f"Mehrere ISIN im Dokument ({', '.join(uniq)}) – Zuordnung prüfen")

    # Wertpapiername: Zeile vor/nach ISIN
    if "isin" in f:
        m = re.search(rf"(?m)^(.*?){f['isin'].value}(.*)$", text)
        if m:
            name = re.sub(r"\bISIN\b[:\s]*", "", (m.group(1) or "").strip(" :|-")).strip()
            if len(name) < 3:
                lines = text[:m.start()].rstrip().splitlines()
                name = lines[-1].strip() if lines else ""
            name = re.sub(rf"\b({NUM})\s*(Stk\.?|Stück)\b.*", "", name).strip()
            if 2 < len(name) < 120 and not re.search(r"position|anzahl|isin", name, re.I):
                f["security_name"] = Field(name, 0.6, "Text neben ISIN")

    # Datum
    for label in DATE_LABELS:
        m = re.search(rf"(?i)\b{re.escape(label)}\b[^\n\d]{{0,30}}({DATE})", text)
        if m and _date(m.group(1)):
            f["trade_date"] = Field(_date(m.group(1)), 0.9, f"Label „{label}“")
            break
    if "trade_date" not in f:
        m = re.search(DATE, text)
        if m and _date(m.group(0)):
            f["trade_date"] = Field(_date(m.group(0)), 0.5, "erstes Datum im Dokument")
            ex.warnings.append("Buchungsdatum nur heuristisch ermittelt")

    # Stückzahl & Kurs
    m = re.search(rf"(?i)(?<![\w.,])({NUM})[ \t]*(?:Stk\.?|Stück|Anteile|Shares)(?!\w)", text) or \
        re.search(rf"(?i)\b(?:Stück|Anzahl|Stückzahl|Nominale)\b[: \t]*({NUM})", text)
    if m:
        q = _num(m.group(1))
        if q:
            f["quantity"] = Field(abs(q), 0.85, "Stück-Angabe")
    m = re.search(rf"(?i)\b(?:Kurs|Ausführungskurs|Preis|Durchschnittskurs)\b[^\n\d]{{0,20}}({NUM})\s*({CUR})", text)
    if m:
        f["price"] = Field(_num(m.group(1)), 0.8, "Kurs-Angabe")
        f["currency"] = Field(m.group(2).replace("€", "EUR"), 0.8, "Währung beim Kurs")
    elif "quantity" in f:
        m = re.search(rf"(?i)(?<![\w.,])({NUM})[ \t]*(?:Stk\.?|Stück)[ \t]+({NUM})[ \t]*({CUR})", text)
        if m:
            f["price"] = Field(_num(m.group(2)), 0.75, "Positionszeile")
            f["currency"] = Field(m.group(3).replace("€", "EUR"), 0.75, "Positionszeile")

    # Beträge
    income = ex.tx_type in (TxType.DIVIDEND.value, TxType.DISTRIBUTION.value, TxType.INTEREST.value,
                            TxType.CAPITAL_REPAYMENT.value)
    gross = _labeled_amount(text, GROSS_LABELS_INCOME if income else GROSS_LABELS_TRADE)
    if gross:
        f["amount"] = Field(abs(gross[0]), 0.85, f"Label „{gross[2]}“")
        if gross[1] and "currency" not in f:
            f["currency"] = Field(gross[1], 0.8, f"Währung bei „{gross[2]}“")
    elif not income and "quantity" in f and "price" in f and f["price"].value:
        f["amount"] = Field(round(f["quantity"].value * f["price"].value, 2), 0.6, "Stück × Kurs")
        ex.warnings.append("Kurswert aus Stück × Kurs berechnet – nicht im Dokument gefunden")
    total = _labeled_amount(text, TOTAL_LABELS)
    if total:
        f["total"] = Field(abs(total[0]), 0.8, f"Label „{total[2]}“")

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
        f["kest_at_eur"] = Field(round(sum(abs(v) for v, _, _ in kest), 2), 0.5, ", ".join(l for *_, l in kest))
        ex.warnings.append("Kapitalertragsteuer gefunden – prüfen, ob es sich um österreichische KESt handelt")

    m = re.search(rf"(?i)(?:Devisenkurs|Wechselkurs|Umrechnungskurs)[^\n\d]{{0,20}}(?:1\s*EUR\s*=\s*)?({NUM})", text)
    if m:
        f["fx_rate"] = Field(_num(m.group(1)), 0.7, "Devisenkurs")
    if "currency" not in f:
        m = re.search(rf"\b({CUR})\b", text)
        if m:
            f["currency"] = Field(m.group(1).replace("€", "EUR"), 0.5, "erste Währungsangabe")

    # Plausibilität
    if ex.doc_type in ("Jahressteuerbescheinigung", "OeKB-Fondsmeldung"):
        ex.creates_transaction = False
        ex.warnings.append(f"{ex.doc_type}: keine einzelne Buchung – Werte bitte manuell prüfen und als Beleg "
                           "verknüpfen bzw. im Bereich Fonds/OeKB erfassen")
    if ex.tx_type is None and ex.creates_transaction:
        ex.warnings.append("Buchungsart nicht erkannt")
    q, p, a = ex.value("quantity"), ex.value("price"), ex.value("amount")
    if q and p and a and ex.tx_type in (TxType.BUY.value, TxType.SELL.value):
        if abs(q * p - a) > max(0.02, 0.01 * a):
            ex.warnings.append(f"Stück × Kurs ({q * p:.2f}) weicht vom Kurswert ({a:.2f}) ab")
    tot = ex.value("total")
    if a and tot and ex.tx_type == TxType.BUY.value:
        exp = a + (ex.value("fees") or 0)
        if abs(exp - tot) > 0.02:
            ex.warnings.append(f"Kurswert + Gebühren ({exp:.2f}) ≠ Endbetrag ({tot:.2f})")
    if a and tot and ex.tx_type == TxType.SELL.value:
        exp = a - (ex.value("fees") or 0) - (ex.value("kest_at_eur") or 0)
        if abs(exp - tot) > 0.02:
            ex.warnings.append(f"Kurswert − Gebühren − Steuern ({exp:.2f}) ≠ Endbetrag ({tot:.2f})")
    if a and tot and ex.tx_type in (TxType.DIVIDEND.value, TxType.DISTRIBUTION.value):
        exp = a - (ex.value("withholding_tax") or 0) - (ex.value("kest_at_eur") or 0)
        if abs(exp - tot) > 0.02 and not ex.value("fx_rate"):
            ex.warnings.append(f"Brutto − Steuern ({exp:.2f}) ≠ Gutschrift ({tot:.2f}) – Währungsumrechnung?")
    cur = ex.value("currency")
    if cur and cur != "EUR" and not ex.value("fx_rate"):
        ex.warnings.append(f"Betrag in {cur} ohne Devisenkurs – EUR-Wert fehlt")

    req = REQUIRED.get(ex.tx_type or "", []) if ex.creates_transaction else []
    ex.missing = [FIELD_LABELS[r] for r in req if ex.value(r) is None]
    low = [FIELD_LABELS.get(r, r) for r in req if r in f and f[r].confidence < 0.8]
    if low:
        ex.warnings.append("Unsichere Werte: " + ", ".join(low))
    ex.complete = bool(ex.creates_transaction and ex.tx_type and not ex.missing and not low)
    return ex


def extract_pdf(data: bytes, engine: str = "auto") -> Extraction:
    text, used = extract_text(data, engine)
    ex = parse_text(text)
    ex.engine = used
    return ex
