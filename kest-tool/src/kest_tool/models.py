"""Fachliche Konstanten und pydantic-Modelle für validierte Eingaben."""

from __future__ import annotations

import re
from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


class TxType(str, Enum):
    BUY = "Kauf"
    SELL = "Verkauf"
    DIVIDEND = "Dividende"
    DISTRIBUTION = "Ausschüttung"
    INTEREST = "Zinsen"
    CAPITAL_REPAYMENT = "Kapitalrückzahlung"
    AGE = "Ausschüttungsgleicher Ertrag"
    FEE = "Gebühr"
    TAX = "Steuer"
    TAX_REFUND = "Steuererstattung"
    DEPOSIT = "Einzahlung"
    WITHDRAWAL = "Auszahlung"
    SPLIT = "Split"
    TRANSFER_IN = "Depoteingang"
    TRANSFER_OUT = "Depotausgang"
    CORPORATE_ACTION = "Kapitalmaßnahme"
    OTHER = "Sonstige"


INCOME_TYPES = {TxType.DIVIDEND, TxType.DISTRIBUTION, TxType.INTEREST, TxType.AGE}


class SecurityType(str, Enum):
    STOCK = "Aktie"
    ETF_DIST = "ETF ausschüttend"
    ETF_ACC = "ETF thesaurierend"
    FUND_AT = "Investmentfonds (AT)"
    FUND_FOREIGN = "Investmentfonds (Ausland)"
    REIT = "REIT"
    BDC = "BDC"
    BOND = "Anleihe"
    CERTIFICATE = "Zertifikat/Derivat"
    OTHER = "Sonstige"


FUND_SECURITY_TYPES = {SecurityType.ETF_DIST, SecurityType.ETF_ACC, SecurityType.FUND_AT, SecurityType.FUND_FOREIGN}


class TaxClass(str, Enum):
    """Steuerliche Einstufung – bewusst getrennt von der Wertpapierart."""

    KAPITALGESELLSCHAFT = "beteiligung_kapitalgesellschaft"  # Aktie: Dividenden § 27 Abs 2 Z 1 EStG
    INVESTMENTFONDS = "investmentfonds"                      # § 186/188 InvFG 2011
    IMMOBILIENFONDS = "immobilienfonds"                      # ImmoInvFG – nicht implementiert
    FORDERUNGSWERTPAPIER = "forderungswertpapier"            # Anleihe
    DERIVAT_VERBRIEFT = "derivat_verbrieft_oeffentlich"
    DERIVAT = "derivat"                                      # nicht implementiert
    SONSTIGE = "sonstige"
    UNGEKLAERT = "ungeklaert"


TAX_CLASS_LABELS = {
    TaxClass.KAPITALGESELLSCHAFT: "Beteiligung an Kapitalgesellschaft (Dividenden/Wertsteigerung)",
    TaxClass.INVESTMENTFONDS: "Investmentfonds (InvFG 2011)",
    TaxClass.IMMOBILIENFONDS: "Immobilienfonds (ImmoInvFG) – manuelle Prüfung",
    TaxClass.FORDERUNGSWERTPAPIER: "Forderungswertpapier (Anleihe)",
    TaxClass.DERIVAT: "Derivat/Zertifikat – manuelle Prüfung",
    TaxClass.DERIVAT_VERBRIEFT: "Öffentlich begebenes verbrieftes Derivat (Long-Bestand; mit Emittentenbeleg)",
    TaxClass.SONSTIGE: "Sonstige – manuelle Prüfung",
    TaxClass.UNGEKLAERT: "ungeklärt",
}


class FundStatus(str, Enum):
    NO_FUND = "kein_fonds"
    MELDEFONDS = "meldefonds"
    NICHTMELDEFONDS = "nichtmeldefonds"
    UNKNOWN = "unbekannt"


class IncomeCategory(str, Enum):
    AUTO = "auto"
    DIVIDEND = "dividende"
    OTHER_DISTRIBUTION = "sonstige_ausschuettung"
    CAPITAL_REPAYMENT = "kapitalrueckzahlung"
    UNCLEAR = "ungeklaert"


class ReviewStatus(str, Enum):
    UNCHECKED = "ungeprueft"
    CHECKED = "geprueft"
    TO_REVIEW = "pruefen"


DOC_SOURCES = ["TradeRepublic", "ScalableCapital", "OeKB", "Other", "Unclassified"]
DOC_TYPES = [
    "Kaufabrechnung", "Verkaufsabrechnung", "Dividendenabrechnung", "Ertragsabrechnung",
    "Ausschüttungsabrechnung", "Jahressteuerbescheinigung", "OeKB-Fondsmeldung", "Transaktionsexport (CSV)",
    "Transaktionsexport (Excel)", "Kontoauszug", "Depotauszug", "Sonstiges", "Unbekannt",
    "Zinsabrechnung", "Kosteninformation", "Zahlungsbeleg", "Storno", "Steuerkorrektur",
    "Depotübertrag", "Kapitalmaßnahme", "Sammelabrechnung", "Kryptoabrechnung",
    "Vorabpauschale (DE)", "Informationsdokument",
    "Gebührenabrechnung", "Fremdsprachige Abrechnung",
]
DOC_STATUS = ["neu", "verarbeitet", "teilweise", "pruefen", "fehlgeschlagen", "ignoriert"]
BROKER_KEYS = ["TradeRepublic", "ScalableCapital", "Other"]
TRISTATE = ["ja", "nein", "unbekannt"]


def normalize_isin(value: str | None) -> str | None:
    if value is None:
        return None
    v = re.sub(r"\s+", "", str(value)).upper()
    return v or None


def isin_checksum_ok(isin: str) -> bool:
    """Prüft die Luhn-Prüfziffer einer ISIN."""
    if not ISIN_RE.match(isin or ""):
        return False
    digits = "".join(str(int(c, 36)) for c in isin[:-1])
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return (10 - total % 10) % 10 == int(isin[-1])


class TransactionIn(BaseModel):
    """Validierte Buchung vor dem Speichern."""

    model_config = ConfigDict(use_enum_values=False, str_strip_whitespace=True, allow_inf_nan=False)

    depot_id: int
    tx_type: TxType
    trade_date: date
    value_date: Optional[date] = None
    execution_order: Optional[int] = Field(default=None, gt=0)
    isin: Optional[str] = None
    security_name: Optional[str] = None
    quantity: Optional[float] = None
    price: Optional[float] = None
    currency: str = "EUR"
    amount: Optional[float] = None
    fees: float = 0.0
    fx_rate: Optional[float] = Field(default=None, gt=0)
    fx_source: Optional[str] = None
    withholding_tax: float = 0.0
    withholding_country: Optional[str] = None
    kest_at_eur: float = 0.0
    ratio: Optional[float] = Field(default=None, gt=0)
    income_category: IncomeCategory = IncomeCategory.AUTO
    income_category_verified: bool = False
    notes: Optional[str] = None
    source_type: str = "manuell"
    source_ref: Optional[str] = None
    document_id: Optional[int] = None
    review_status: ReviewStatus = ReviewStatus.UNCHECKED

    @field_validator("isin", mode="before")
    @classmethod
    def _isin(cls, v):
        v = normalize_isin(v)
        if v and not ISIN_RE.match(v):
            raise ValueError(f"ungültige ISIN '{v}'")
        return v

    @field_validator("currency", mode="before")
    @classmethod
    def _cur(cls, v):
        v = (v or "EUR").strip().upper()
        if v in {"€", "EURO"}:
            v = "EUR"
        if not re.fullmatch(r"[A-Z]{3}", v):
            raise ValueError(f"ungültige Währung '{v}'")
        return v

    @field_validator("withholding_country", mode="before")
    @classmethod
    def _country(cls, v):
        if v in (None, ""):
            return None
        v = str(v).strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", v):
            raise ValueError(f"Länderkennzeichen muss ISO-2 sein, nicht '{v}'")
        return v

    @field_validator("quantity", "amount", "fees", "withholding_tax", "kest_at_eur", "price", mode="after")
    @classmethod
    def _abs(cls, v):
        # Beträge werden vorzeichenlos gespeichert; die Richtung ergibt sich aus der Buchungsart.
        return abs(v) if v is not None else v

    @model_validator(mode="after")
    def _consistency(self):
        if self.tx_type in (TxType.BUY, TxType.SELL) and not self.isin:
            raise ValueError("Kauf/Verkauf benötigt eine ISIN")
        if self.tx_type in (TxType.BUY, TxType.SELL, TxType.TRANSFER_OUT) and not self.quantity:
            raise ValueError("Kauf/Verkauf benötigt eine Stückzahl")
        if self.tx_type == TxType.SPLIT and not self.ratio:
            raise ValueError("Split benötigt ein Verhältnis (neu/alt)")
        if self.currency != "EUR" and self.amount and not self.fx_rate:
            # zulässig, wird aber in der Berechnung als fehlende Angabe gemeldet
            pass
        return self

    # EUR-Werte ---------------------------------------------------------
    def eur(self, value: float | None) -> float | None:
        if value is None:
            return None
        if self.currency == "EUR":
            return value
        if not self.fx_rate:
            return None
        return value / self.fx_rate


class SecurityIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    isin: str
    name: Optional[str] = None
    ticker: Optional[str] = None
    wkn: Optional[str] = None
    currency: Optional[str] = None
    country: Optional[str] = None
    security_type: SecurityType = SecurityType.OTHER
    tax_class: TaxClass = TaxClass.UNGEKLAERT
    tax_class_source: Optional[str] = None
    tax_class_verified: bool = False
    fund_status: FundStatus = FundStatus.NO_FUND
    fund_status_source: Optional[str] = None
    fund_status_verified: bool = False
    notes: Optional[str] = None

    @field_validator("isin", mode="before")
    @classmethod
    def _isin(cls, v):
        v = normalize_isin(v)
        if not v or not ISIN_RE.match(v):
            raise ValueError(f"ungültige ISIN '{v}'")
        return v

    @model_validator(mode="after")
    def _verified_needs_source(self):
        if self.tax_class_verified and not (self.tax_class_source or "").strip():
            raise ValueError("Eine als geprüft markierte steuerliche Einstufung benötigt eine Quellenangabe")
        if self.fund_status_verified and not (self.fund_status_source or "").strip():
            raise ValueError("Ein als geprüft markierter Meldefondsstatus benötigt eine Quellenangabe")
        return self


class FundReportIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, allow_inf_nan=False)

    isin: str
    fund_name: Optional[str] = None
    report_type: str = "Jahresmeldung"
    fiscal_year_end: Optional[date] = None
    report_date: date
    distribution_date: Optional[date] = None
    currency: str = "EUR"
    fx_rate: Optional[float] = Field(default=None, gt=0)
    distribution_per_unit: Optional[float] = None
    age_per_unit: Optional[float] = None
    taxable_distribution_per_unit: Optional[float] = None
    creditable_tax_per_unit: Optional[float] = None
    ak_correction_per_unit: Optional[float] = None
    kest_per_unit: Optional[float] = None
    is_meldefonds: Optional[bool] = True
    source: str = "manuell"
    document_id: Optional[int] = None
    notes: Optional[str] = None

    @field_validator("isin", mode="before")
    @classmethod
    def _isin(cls, v):
        v = normalize_isin(v)
        if not v or not ISIN_RE.match(v):
            raise ValueError(f"ungültige ISIN '{v}'")
        return v

    @field_validator("currency", mode="before")
    @classmethod
    def _cur(cls, v):
        v = (v or "EUR").strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", v):
            raise ValueError(f"ungültige Währung '{v}'")
        return v

    @model_validator(mode="after")
    def _fx(self):
        if self.currency != "EUR" and not self.fx_rate:
            raise ValueError("Fondsmeldung in Fremdwährung benötigt einen Umrechnungskurs (Währung je EUR)")
        return self


COMPARE_FIELDS_FUND_REPORT = [
    "distribution_per_unit", "age_per_unit", "taxable_distribution_per_unit", "creditable_tax_per_unit",
    "ak_correction_per_unit", "kest_per_unit", "currency", "fiscal_year_end",
]
