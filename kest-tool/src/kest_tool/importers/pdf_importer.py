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

TRADE_DATE_LABELS = ["Schlusstag", "Handelstag", "Ausführungstag", "Ausführungsdatum", "Ausführung"]
INCOME_DATE_LABELS = ["Zahltag", "Zahlungstag", "Valuta", "Buchungsdatum", "Datum", "Abrechnungsdatum"]
GENERIC_DATE_LABELS = ["Buchungsdatum", "Datum", "Abrechnungsdatum", "Valuta"]
FEE_LABELS = ["Fremdkostenzuschlag", "Ordergebühr", "Ordergebuehr", "Orderentgelt", "Provision", "Transaktionsgebühr",
              "Transaktionskosten", "Handelsplatzgebühr", "Börsengebühr", "Gebühr", "Fremde Spesen", "Spesen"]
GROSS_LABELS_TRADE = ["Kurswert", "Ordervolumen", "Kaufpreis", "Verkaufspreis", "Gesamtkurswert"]
GROSS_LABELS_INCOME = ["Bruttobetrag", "Brutto", "Dividende brutto", "Ausschüttung brutto", "Bruttoertrag",
                       "Zinsbetrag brutto", "Ertrag", "Dividende", "Ausschüttung", "Zinsen"]
TOTAL_LABELS = ["Gesamt", "Endbetrag", "Zu Lasten", "Zu Gunsten", "Ausmachender Betrag", "Gutschrift", "Belastung", "Betrag zu Ihren Lasten",
                "Betrag zu Ihren Gunsten", "Total"]
WHT_LABELS = ["Quellensteuer", "Ausländische Quellensteuer", "US-Quellensteuer", "Withholding Tax",
              "Anrechenbare Quellensteuer"]
KEST_LABELS = ["Kapitalertragsteuer Österreich", "KESt Österreich", "KESt"]
GERMAN_TAX_LABELS = ["Kapitalertragsteuer", "Solidaritätszuschlag", "Kirchensteuer"]


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

    # Positionszeile (z. B. Trade Republic): "<Name> 1 Stk. 497,40 EUR 497,40 EUR"
    pos = re.search(rf"(?im)^(.*?)(?<![\w.,])({NUM})[ \t]*(?:Stk\.?|Stück)[ \t]+({NUM})[ \t]*({CUR})"
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
    name = re.sub(rf"(?<![\w.,])({NUM})\s*(Stk\.?|Stück)\b.*", "", name).strip()
    if 2 < len(name) < 120 and not re.search(r"position|anzahl|isin|nominale", name, re.I):
        f["security_name"] = Field(name, 0.6, "Positionszeile/Text neben ISIN")

    # Datum – je Dokumentart die passende Angabe (Handelstag bzw. Zahltag; Ex-Tag zuletzt)
    income_doc = ex.tx_type in (TxType.DIVIDEND.value, TxType.DISTRIBUTION.value, TxType.INTEREST.value,
                                TxType.CAPITAL_REPAYMENT.value)
    if ex.tx_type in (TxType.BUY.value, TxType.SELL.value):
        m = re.search(rf"(?i)\b(?:Kauf|Verkauf|Sparplanausführung|ausgeführt|Ausführung)\b[^\n\d]{{0,25}}\bam\s+({DATE})", text)
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
        f["price"] = Field(_num(pos.group(3)), 0.85, "Positionszeile")
        f["currency"] = Field(pos.group(4).replace("€", "EUR"), 0.85, "Positionszeile")
    elif stk and _num(stk.group(1)):
        f["quantity"] = Field(abs(_num(stk.group(1))), 0.9, "STK-Angabe")
    else:
        m = re.search(rf"(?i)(?<![\w.,])({NUM})[ \t]*(?:Stk\.?|Stück|Anteile|Shares)(?!\w)", text) or \
            re.search(rf"(?i)\b(?:Stück|Anzahl|Stückzahl)\b[: \t]*({NUM})", text)
        if m and _num(m.group(1)):
            f["quantity"] = Field(abs(_num(m.group(1))), 0.85, "Stück-Angabe")
    if "price" not in f:
        m = re.search(rf"(?im)\b(?:Kurs|Ausführungskurs|Preis|Durchschnittskurs)\b[ \t:]*(?:({CUR})[ \t]*)?({NUM})[ \t]*({CUR})?", text)
        if m and (m.group(1) or m.group(3)) and _num(m.group(2)):
            f["price"] = Field(_num(m.group(2)), 0.8, "Kurs-Angabe")
            f["currency"] = Field((m.group(3) or m.group(1)).replace("€", "EUR"), 0.8, "Währung beim Kurs")

    # Beträge
    income = ex.tx_type in (TxType.DIVIDEND.value, TxType.DISTRIBUTION.value, TxType.INTEREST.value,
                            TxType.CAPITAL_REPAYMENT.value)
    gross = _labeled_amount(text, GROSS_LABELS_INCOME if income else GROSS_LABELS_TRADE)
    if gross:
        f["amount"] = Field(abs(gross[0]), 0.85, f"Label „{gross[2]}“")
        if gross[1] and "currency" not in f:
            f["currency"] = Field(gross[1], 0.8, f"Währung bei „{gross[2]}“")
    elif pos and pos.group(5):
        f["amount"] = Field(abs(_num(pos.group(5)) or 0), 0.85, "Betrag in der Positionszeile")
        f["currency"] = Field(pos.group(6).replace("€", "EUR"), 0.85, "Positionszeile")
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
        f["kest_at_eur"] = Field(round(sum(abs(v) for v, _, _ in kest), 2), 0.7, ", ".join(l for *_, l in kest))

    m = re.search(rf"(?i)(?:Devisenkurs|Wechselkurs|Umrechnungskurs)[^\n\d]{{0,20}}(?:1\s*EUR\s*=\s*)?({NUM})", text) \
        or re.search(rf"(?<![\w.,])(\d+,\d{{2,6}}|\d+\.\d{{2,6}})[ \t]*EUR/[A-Z]{{3}}\b", text) \
        or re.search(rf"\bEUR/[A-Z]{{3}}[ \t:]*(\d+,\d{{2,6}}|\d+\.\d{{2,6}})", text)
    if m and _num(m.group(1)):
        f["fx_rate"] = Field(_num(m.group(1)), 0.75, "Devisenkurs (Fremdwährung je EUR)")
    if "currency" not in f:
        m = re.search(rf"\b({CUR})\b", text)
        if m:
            f["currency"] = Field(m.group(1).replace("€", "EUR"), 0.5, "erste Währungsangabe")

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
    (r"vorabpauschale", "Vorabpauschale (DE)", False, "info",
     "Deutsche Vorabpauschale – für die österreichische Besteuerung nicht relevant.",
     "Keine Buchung nötig. Für österreichische Fondserträge sind die OeKB-Meldungen maßgeblich."),
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

    # Endbetrag abgleichen
    tot, fx = ex.value("total"), ex.value("fx_rate")
    wht, kest = ex.value("withholding_tax") or 0, ex.value("kest_at_eur") or 0
    if a and tot:
        if ex.tx_type == TxType.BUY.value:
            exp, what = a + fees, "Kurswert + Gebühren"
        elif ex.tx_type == TxType.SELL.value:
            exp, what = a - fees - kest, "Kurswert − Gebühren − Steuern"
        elif ex.tx_type in (TxType.DIVIDEND.value, TxType.DISTRIBUTION.value, TxType.INTEREST.value):
            exp, what = a - wht, "Brutto − Quellensteuer"
            if fx and ex.value("currency") not in (None, "EUR"):
                exp, what = exp / fx - kest, "(Brutto − Quellensteuer) / Devisenkurs − KESt"
            else:
                exp -= kest
        else:
            exp = None
        if exp is not None:
            tol = max(0.02, 0.005 * tot)
            if abs(exp - tot) > tol:
                ex.check("Endbetrag stimmt", "warn", f"{what} = {exp:.2f}, Endbetrag laut Dokument {tot:.2f}.",
                         "Fehlende Gebühr/Steuer oder falsch erkannten Betrag im Original suchen.")
            else:
                ex.check("Endbetrag stimmt", "ok", f"{what} = {exp:.2f} ≈ {tot:.2f}")
    elif a and ex.tx_type in (TxType.BUY.value, TxType.SELL.value):
        ex.check("Endbetrag stimmt", "info", "Kein Endbetrag gefunden – Abgleich nicht möglich.")

    # Währung
    cur = ex.value("currency")
    if cur and cur != "EUR":
        if fx:
            ex.check("Devisenkurs", "ok", f"{cur}: {fx} je EUR laut Dokument")
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
    german = [g for g in _all_labeled_amounts(text, GERMAN_TAX_LABELS)
              if g[0] and not re.search(r"österreich", g[2], re.I)]
    german = [g for g in german if g[0] != 0]
    if german and not kest:
        names = ", ".join(sorted({g[2] for g in german}))
        ex.check("Deutsche Steuer", "error", f"Deutsche Abzugsteuer einbehalten ({names}: "
                 f"{sum(abs(g[0]) for g in german):.2f}). Sie ist keine österreichische KESt.",
                 "Beim Broker die österreichische Ansässigkeit prüfen; Erstattung beantragen. Betrag nicht als KESt "
                 "erfassen.")
    if kest:
        ex.check("Österreichische KESt", "ok", f"{kest:.2f} einbehalten")

    low = [c for c in ex.checks if c["result"] == "warn" and c["name"] in FIELD_LABELS.values()]
    errors = [c for c in ex.checks if c["result"] == "error"]
    ex.complete = bool(ex.tx_type and not ex.missing and not low and not errors)


def extract_pdf(data: bytes, engine: str = "auto") -> Extraction:
    text, used = extract_text(data, engine)
    ex = parse_text(text)
    ex.engine = used
    return ex
