"""Heuristische, lokale Dokumentklassifizierung.

Grundsätze:
- Die Originaldatei wird nie verändert (es wird nur gelesen).
- Es werden keine Dokumentdaten erfunden: ein Datum wird nur übernommen, wenn es in der
  Dokumentliste, im Titel/Dateinamen oder als beschriftetes Datum im PDF-Text steht.
- Bei fehlender Evidenz: Kategorie "Unbekannt"; bei widersprüchlicher Evidenz: "Zu prüfen".
- OCR ist optional, lokal (Tesseract) und standardmäßig deaktiviert.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date

log = logging.getLogger(__name__)

# Kategorie -> Zielordner
CATEGORY_FOLDERS: dict[str, str] = {
    "Jahressteuerbescheinigung": "Steuer",
    "Steuer": "Steuer",
    "Kontoauszug": "Kontoauszuege",
    "Depotauszug": "Depotauszuege",
    "Kaufabrechnung": "Wertpapierabrechnungen",
    "Verkaufsabrechnung": "Wertpapierabrechnungen",
    "Sparplan": "Wertpapierabrechnungen",
    "Dividende": "Dividenden",
    "Zinsen": "Zinsen",
    "Gebühren": "Gebuehren",
    "Einzahlung": "Ein-Auszahlungen",
    "Auszahlung": "Ein-Auszahlungen",
    "Vertrag": "Vertraege",
    "Sonstige": "Sonstige",
    "Unbekannt": "Sonstige",
    "Zu prüfen": "Zu_pruefen",
}

# (Kategorie, Regex, Gewicht) – Reihenfolge egal, Gewichte entscheiden.
RULES: list[tuple[str, str, float]] = [
    ("Jahressteuerbescheinigung", r"jahres\s*steuer\s*bescheinigung|steuerbescheinigung\s+(für\s+)?(das\s+)?(jahr\s+)?\d{4}"
                                  r"|annual\s+tax\s+(certificate|statement)|jahressteuerbericht|steuerreport", 6),
    ("Steuer", r"steuer|vorabpauschale|verlustbescheinigung|freistellungsauftrag|nichtveranlagung|\btax\b"
               r"|kapitalertragsteuer|solidarit[äa]tszuschlag|kirchensteuer|steuerkorrektur", 2.5),
    ("Kontoauszug", r"konto\s*auszug|kontoabschluss|rechnungsabschluss|account\s+statement|kontoübersicht"
                    r"|umsatzübersicht|transaktionsübersicht|kontoumsätze", 5),
    ("Depotauszug", r"depot\s*auszug|jahresdepotauszug|depotübersicht|vermögensübersicht|depot\s*statement"
                    r"|securities\s+account\s+statement|wertpapierbestand|bestandsübersicht|depotbestand", 5),
    ("Sparplan", r"spar\s*plan|savings?\s*plan|sparplanausführung", 5),
    ("Kaufabrechnung", r"(?<!ver)kauf(?!s?mann)|\bbuy\b|\bkauforder|ankauf|zeichnung", 3.5),
    ("Verkaufsabrechnung", r"verkauf|\bsell\b|veräußerung|tilgung|rückzahlung", 3.5),
    ("Dividende", r"dividend|ausschüttung|ertragsgutschrift|ertrag\s*gutschrift|ertragsabrechnung|quellensteuer"
                  r"|kapitalmaßnahme|\bdistribution\b|zahltag", 4),
    ("Zinsen", r"zins|interest|guthabenverzinsung", 4),
    ("Gebühren", r"geb[üu]hr|entgelt|kosteninformation|ex[-\s]?post|ex[-\s]?ante|kostenaufstellung|\bfee"
                 r"|provision|depotgebühr", 4),
    ("Einzahlung", r"einzahlung|deposit|lastschrift|gutschrift\s+überweisung|eingang", 3),
    ("Auszahlung", r"auszahlung|withdrawal|überweisung\s+an|abgang", 3),
    ("Vertrag", r"vertrag|kontoeröffnung|depoteröffnung|\bagb\b|geschäftsbedingungen|kundenvereinbarung"
                r"|vereinbarung|vollmacht|vertragsunterlagen|vorvertraglich|informationsblatt|basisinformation"
                r"|preis-?\s*und\s*leistungsverzeichnis|datenschutz|bestätigung\s+der\s+eröffnung"
                r"|legitimation|einwilligung", 3),
]

_COMPILED = [(cat, re.compile(rx, re.IGNORECASE), w) for cat, rx, w in RULES]

# Gewichtung je Evidenzquelle
SOURCE_WEIGHTS = {"hint": 3.0, "title": 3.0, "filename": 2.0, "text": 1.0}

DATE_PATTERNS = [
    re.compile(r"(?<!\d)(?P<y>(?:19|20)\d{2})-(?P<m>0[1-9]|1[0-2])-(?P<d>0[1-9]|[12]\d|3[01])(?!\d)"),
    re.compile(r"(?<!\d)(?P<d>0?[1-9]|[12]\d|3[01])\.(?P<m>0?[1-9]|1[0-2])\.(?P<y>(?:19|20)\d{2})(?!\d)"),
    re.compile(r"(?<!\d)(?P<y>(?:19|20)\d{2})(?P<m>0[1-9]|1[0-2])(?P<d>0[1-9]|[12]\d|3[01])(?!\d)"),
]
LABELED_DATE = re.compile(
    r"(?:datum|abrechnungsdatum|buchungsdatum|valuta|stichtag|zahltag|ausführungsdatum|schlusstag|erstellt\s+am"
    r"|per|zum|vom)\s*[:\-]?\s*(\d{1,2}\.\d{1,2}\.(?:19|20)\d{2}|(?:19|20)\d{2}-\d{2}-\d{2})",
    re.IGNORECASE,
)
YEAR_IN_TITLE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
GERMAN_MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4, "mai": 5, "juni": 6, "juli": 7,
    "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12,
}
GERMAN_DATE = re.compile(
    r"(?<!\d)(\d{1,2})\.?\s+(" + "|".join(GERMAN_MONTHS) + r")\s+((?:19|20)\d{2})(?!\d)", re.IGNORECASE
)


def parse_date(text: str) -> str:
    """Findet das erste gültige Datum in ``text`` und liefert ISO-Format, sonst ''."""
    if not text:
        return ""
    for rx in DATE_PATTERNS:
        for m in rx.finditer(text):
            try:
                return date(int(m.group("y")), int(m.group("m")), int(m.group("d"))).isoformat()
            except ValueError:
                continue
    m = GERMAN_DATE.search(text)
    if m:
        try:
            return date(int(m.group(3)), GERMAN_MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()
        except ValueError:
            pass
    return ""


def parse_labeled_date(text: str) -> str:
    for m in LABELED_DATE.finditer(text or ""):
        iso = parse_date(m.group(1))
        if iso:
            return iso
    return ""


@dataclass
class Classification:
    category: str
    confidence: float
    doc_date: str = ""
    year: str = ""
    evidence: list[str] = field(default_factory=list)
    text_extracted: bool = False

    @property
    def folder(self) -> str:
        return CATEGORY_FOLDERS.get(self.category, "Sonstige")


class Classifier:
    def __init__(self, pdf_text: bool = True, ocr_enabled: bool = False, tesseract_cmd: str = "",
                 max_text_chars: int = 6000):
        self.pdf_text = pdf_text
        self.ocr_enabled = ocr_enabled
        self.tesseract_cmd = tesseract_cmd
        self.max_text_chars = max_text_chars

    # ------------------------------------------------------------------ #
    def extract_pdf_text(self, data: bytes) -> str:
        if not self.pdf_text or not data:
            return ""
        text = ""
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                try:
                    reader.decrypt("")
                except Exception:
                    return ""
            for page in reader.pages[:3]:
                text += (page.extract_text() or "") + "\n"
                if len(text) >= self.max_text_chars:
                    break
        except Exception as exc:  # beschädigte PDFs dürfen den Scan nicht stoppen
            log.debug("PDF-Text nicht extrahierbar: %s", exc)
        if not text.strip() and self.ocr_enabled:
            text = self._ocr(data)
        return text[: self.max_text_chars]

    def _ocr(self, data: bytes) -> str:
        """Lokale OCR (Tesseract). Wird nur bei aktivierter Option und installierter Software genutzt."""
        try:
            import pypdfium2 as pdfium  # type: ignore
            import pytesseract  # type: ignore
        except ImportError:
            log.warning("OCR aktiviert, aber pytesseract/pypdfium2 nicht installiert – OCR übersprungen")
            return ""
        if self.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd
        try:
            pdf = pdfium.PdfDocument(data)
            out = []
            for i in range(min(2, len(pdf))):
                image = pdf[i].render(scale=2).to_pil()
                out.append(pytesseract.image_to_string(image, lang="deu+eng"))
            return "\n".join(out)
        except Exception as exc:
            log.warning("OCR fehlgeschlagen: %s", exc)
            return ""

    # ------------------------------------------------------------------ #
    def score(self, sources: dict[str, str]) -> dict[str, float]:
        scores: dict[str, float] = {}
        for source, text in sources.items():
            if not text:
                continue
            sw = SOURCE_WEIGHTS.get(source, 1.0)
            for cat, rx, w in _COMPILED:
                hits = len(rx.findall(text))
                if hits:
                    # Fließtext: mehrfache Treffer nur gedämpft zählen
                    factor = min(hits, 3) if source == "text" else 1
                    scores[cat] = scores.get(cat, 0.0) + w * sw * factor
        # Spezifischere Kategorien verdrängen allgemeine
        if scores.get("Jahressteuerbescheinigung"):
            scores["Steuer"] = scores.get("Steuer", 0) * 0.3
        if scores.get("Sparplan") and scores.get("Kaufabrechnung"):
            scores["Kaufabrechnung"] *= 0.4
        if scores.get("Dividende") and scores.get("Steuer"):
            scores["Steuer"] *= 0.5  # Quellensteuer auf Dividendenabrechnungen
        return scores

    def classify(self, title: str = "", filename: str = "", list_date: str = "", type_hint: str = "",
                 data: bytes | None = None, text: str | None = None) -> Classification:
        pdf_text = text if text is not None else (self.extract_pdf_text(data) if data else "")
        sources = {"hint": type_hint, "title": title, "filename": filename, "text": pdf_text}
        scores = self.score(sources)
        evidence = [f"{k}" for k, v in sources.items() if v]

        # Datum: Liste > Titel > Dateiname > beschriftetes Datum im Text
        doc_date = ""
        for candidate in (list_date, title, filename):
            doc_date = parse_date(candidate)
            if doc_date:
                break
        if not doc_date and pdf_text:
            doc_date = parse_labeled_date(pdf_text)
        year = doc_date[:4] if doc_date else ""
        if not year:
            m = YEAR_IN_TITLE.search(f"{title} {filename}")
            year = m.group(1) if m else ""

        if not scores:
            return Classification("Unbekannt", 0.0, doc_date, year, evidence, bool(pdf_text))
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        top_cat, top = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        confidence = round(top / (top + second + 3.0), 2)
        if top < 4.0 or (second and top / second < 1.25):
            return Classification("Zu prüfen", confidence, doc_date, year, evidence + [f"kandidat:{top_cat}"],
                                  bool(pdf_text))
        return Classification(top_cat, confidence, doc_date, year, evidence, bool(pdf_text))
