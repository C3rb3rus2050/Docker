"""Steuerberechnung (Österreich, Kapitalvermögen Privatvermögen) – modular nach Steuerjahr.

Bausteine:
- ``CostBasisTracker``: Bestände und Anschaffungskosten (gleitender Durchschnitt je Depot+ISIN) inkl.
  AK-Korrekturen aus Fondsmeldungen, Nichtmeldefonds-Pauschalen und Kapitalrückzahlungen.
- ``IncomeClassifier``: Dividenden, Zinsen, Fondsausschüttungen, REIT/BDC, Kapitalrückzahlungen, Quellensteuer.
- ``FundProcessor``: Meldefonds (OeKB) und Nichtmeldefonds.
- ``LossOffset``: Verlustausgleich mit gesetzlichen Einschränkungen.
- ``summarize`` / ``e1kv_rows``: Steuerbeträge und E 1kv-Arbeitshilfe.

Jede Rechenposition (``CalcLine``) enthält Ausgangsdaten, Herkunft, angewendete Regel, Satz, Rechenschritte,
Ergebnis, Steuerjahr und Prüfstatus. Ist eine Regel für das Jahr nicht verifiziert, wird kein Betrag berechnet.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from ..models import FUND_SECURITY_TYPES, FundStatus, IncomeCategory, SecurityType, TaxClass, TxType
from ..repository import Repository
from .rules import TaxRules, load_rules

EPS = 1e-9
CALC = "berechnet"
PROVISIONAL = "vorlaeufig"
MANUAL = "manuell_pruefen"
STATUS_TEXT = {CALC: "berechnet (Regel offiziell belegt, Daten geprüft)", PROVISIONAL: "vorläufig – prüfen",
               MANUAL: "manuell steuerlich zu prüfen – nicht berechnet"}

BUCKET_27_5 = "27,5 %"
BUCKET_25 = "25 %"
BUCKET_NONE = "nicht steuerpflichtig / AK-Anpassung"
BUCKET_UNCLEAR = "ungeklärt"

# Kategorien
CAT_DIVIDEND = "Dividende"
CAT_INTEREST_27 = "Zinsen (Wertpapier, 27,5 %)"
CAT_INTEREST_25 = "Zinsen Geldeinlage (25 %)"
CAT_FUND_DIST = "Fondsausschüttung (steuerpflichtig)"
CAT_FUND_DIST_FREE = "Fondsausschüttung (bereits versteuert/steuerfrei)"
CAT_AGE = "Ausschüttungsgleiche Erträge (Meldefonds)"
CAT_AGE_MANUAL = "Ausschüttungsgleiche Erträge (manuell)"
CAT_NMF = "Nichtmeldefonds – pauschale AgE"
CAT_GAIN = "Realisierter Gewinn"
CAT_LOSS = "Realisierter Verlust"
CAT_CAPREPAY = "Kapitalrückzahlung (AK-Minderung)"
CAT_UNCLEAR = "Ungeklärter Ertrag"
CAT_REIT_OTHER = "REIT/BDC – sonstige Ausschüttung"

# Reihenfolge der Verlustverrechnung (Annahme, siehe Regel LOSS_OFFSET_ORDER)
OFFSET_ORDER = [CAT_GAIN, CAT_AGE, CAT_AGE_MANUAL, CAT_NMF, CAT_FUND_DIST, CAT_INTEREST_27, CAT_REIT_OTHER,
                CAT_DIVIDEND]


@dataclass
class Issue:
    severity: str          # Fehler | Warnung | Hinweis
    kind: str              # Fehlende Daten | Widerspruch | Offene steuerliche Frage | Warnung | Manuelle Änderung
    message: str
    ref: str = ""
    tax_year: int | None = None
    action: str = ""       # Was tun?
    page: str = ""         # Seite zur Behebung (url_path)


# (Muster in der Meldung, Was tun?, Seite)
ISSUE_ACTIONS: list[tuple[str, str, str]] = [
    (r"Anschaffungskosten unbekannt|Kaufhistorie unvollständig",
     "Fehlende Käufe bzw. Depoteingänge importieren (am besten die gesamte Historie) oder unter Transaktionen "
     "manuell erfassen.", "import"),
    (r"ohne Devisenkurs|EUR-Betrag fehlt|EUR-Erlös fehlt",
     "Devisenkurse von der EZB ergänzen (Dashboard/Transaktionen) oder den Kurs aus dem Beleg eintragen.",
     "transaktionen"),
    (r"ohne Quellenstaat", "Unter Wertpapiere den Sitzstaat des Emittenten (z. B. US) eintragen.", "wertpapiere"),
    (r"DBA-Höchstsatz nicht verifiziert",
     "Anrechenbaren Satz laut Doppelbesteuerungsabkommen prüfen; bis dahin bleibt der Betrag ungeklärt.", "steuer"),
    (r"Meldefondsstatus unbekannt",
     "Unter Wertpapiere den Meldefondsstatus setzen (Fondssuche auf my.oekb.at) und die Quelle angeben.",
     "wertpapiere"),
    (r"OeKB-Meldung", "OeKB-Meldung importieren oder unter Fonds & OeKB erfassen.", "fonds"),
    (r"nicht angegeben, ob der Broker",
     "Unter Broker & Depots für dieses Jahr angeben, ob der Broker österreichische KESt abführt.", "depots"),
    (r"Steuerliche Einstufung .* ungeprüft",
     "Unter Wertpapiere die Einstufung prüfen und mit Quelle als geprüft markieren.", "wertpapiere"),
    (r"Kursdaten .* fehlen", "Rücknahmepreise unter Fonds & OeKB laden oder als CSV importieren.", "fonds"),
    (r"Pauschalbesteuerung .* nicht verifiziert",
     "Pauschale manuell bzw. mit Steuerberatung ermitteln – das Tool rechnet hier bewusst nicht.", "fonds"),
    (r"Kapitalrückzahlung|REIT|BDC|Ertragsart",
     "Unter Transaktionen die Ertragsart anhand des Belegs festlegen und als belegt markieren.", "transaktionen"),
    (r"Datenkonflikt|wartet auf Entscheidung|Meldung für .* vorhanden",
     "Unter Fonds & OeKB → Konflikte entscheiden, welcher Wert gilt.", "fonds"),
    (r"Depoteingang", "Anschaffungskosten aus dem Übertragsbeleg prüfen und eintragen.", "transaktionen"),
    (r"Depotausgang", "Prüfen, ob ein steuerpflichtiger Vorgang (z. B. Schenkung, Wegzug) vorliegt.", "transaktionen"),
    (r"Kapitalmaßnahme", "Als Split (mit Verhältnis) bzw. Kapitalmaßnahme unter Transaktionen erfassen.",
     "transaktionen"),
    (r"Österreichische KESt gebucht", "Unter Broker & Depots die KESt-Einstellung für das Jahr prüfen.", "depots"),
    (r"Steuererstattung", "Erstattete Steuer bei der betroffenen Dividende berücksichtigen.", "transaktionen"),
    (r"manuell gebuchte AgE", "Keine Aktion nötig – die OeKB-Meldung wird verwendet.", ""),
    (r"Zinsposition", "Keine Aktion nötig – gesetzliche Einschränkung.", ""),
    (r"^Regel ", "Information: Ergebnis vorläufig – Quellen siehe docs/STEUERREGELN.md.", ""),
]


def _issue_action(message: str) -> tuple[str, str]:
    import re as _re

    for rx, action, page in ISSUE_ACTIONS:
        if _re.search(rx, message):
            return action, page
    return "", ""


@dataclass
class CalcLine:
    line_id: str
    tax_year: int
    category: str
    bucket: str
    date: str
    depot_id: int | None = None
    depot: str = ""
    broker: str = ""
    domestic: bool = False
    isin: str | None = None
    name: str | None = None
    gross: float | None = None           # Ausgangsbetrag (Brutto/Erlös)
    amount: float | None = None          # steuerlich anzusetzender Betrag (+ Ertrag / − Verlust); None = nicht berechnet
    withholding_tax: float = 0.0
    creditable_tax_max: float = 0.0      # anrechenbare ausländische Steuer (Höchstbetrag vor Verlustausgleich)
    non_creditable_tax: float = 0.0
    unclear_tax: float = 0.0
    kest_at: float = 0.0
    fees: float = 0.0
    rate: float | None = None
    rule_ids: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    tx_ids: list[int] = field(default_factory=list)
    doc_ids: list[int] = field(default_factory=list)
    status: str = PROVISIONAL
    notes: list[str] = field(default_factory=list)
    e1kv_key: str | None = None
    offset_amount: float = 0.0           # durch Verlustausgleich verbraucht

    @property
    def taxable_after_offset(self) -> float:
        return (self.amount or 0.0) - self.offset_amount if (self.amount or 0) > 0 else 0.0

    def downgrade(self, status: str) -> None:
        order = {CALC: 0, PROVISIONAL: 1, MANUAL: 2}
        if order[status] > order[self.status]:
            self.status = status


@dataclass
class LossOffsetRow:
    loss_line: str
    tax_year: int
    category: str
    depot: str
    isin: str | None
    name: str | None
    original_loss: float
    offsets: list[tuple[str, str, float]] = field(default_factory=list)  # (line_id, Kategorie, Betrag)
    offset_total: float = 0.0
    remaining: float = 0.0
    reasons: list[str] = field(default_factory=list)
    status: str = PROVISIONAL


@dataclass
class Holding:
    qty: float = 0.0
    cost: float = 0.0
    cost_known: bool = True
    history_gap: bool = False


@dataclass
class TaxResult:
    tax_year: int
    lines: list[CalcLine]
    issues: list[Issue]
    loss_offsets: list[LossOffsetRow]
    summary: dict
    summary_confirmed: dict
    e1kv: list[dict]
    nmf_rows: list[dict]
    fund_rows: list[dict]
    positions: list[dict]
    rules_used: list[dict]
    fees: list[dict]

    def lines_by(self, *categories: str) -> list[CalcLine]:
        return [l for l in self.lines if l.category in categories]


# --------------------------------------------------------------------------- #
class Context:
    """Gemeinsame Daten für die Berechnung eines Steuerjahres."""

    def __init__(self, repo: Repository, rules: TaxRules, year: int):
        self.repo, self.rules, self.year = repo, rules, int(year)
        self.year_end = date(self.year, 12, 31).isoformat()
        self.issues: list[Issue] = []
        self.securities = {s["isin"]: s for s in repo.securities()}
        self.depots = {d["id"]: d for d in repo.depots()}
        self.depot_settings = {d: repo.depot_tax_settings(d, self.year) for d in self.depots}
        self.tx_all = repo.transactions(until=self.year_end)
        self.reports = repo.fund_reports(active_only=True)
        self.nmf = {(p["isin"], p["tax_year"]): p for p in repo.nmf_prices()}
        self.doc_names = {d["id"]: d["original_filename"] for d in repo.documents()}
        self._line_no = 0

    def issue(self, severity: str, kind: str, message: str, ref: str = "") -> None:
        action, page = _issue_action(message)
        self.issues.append(Issue(severity, kind, message, ref, self.year, action, page))

    def next_id(self, prefix: str) -> str:
        self._line_no += 1
        return f"{prefix}-{self.year}-{self._line_no:04d}"

    def rule(self, rid: str):
        return self.rules.rule(rid, self.year)

    def domestic(self, depot_id: int) -> bool:
        return self.depot_settings[depot_id]["kest_withheld"] == "ja"

    def tx_source(self, tx: dict) -> str:
        doc = self.doc_names.get(tx.get("document_id")) if tx.get("document_id") else None
        src = f"Buchung #{tx['id']} ({tx['source_type']}{', ' + tx['source_ref'] if tx.get('source_ref') else ''}"
        return src + (f", Dokument „{doc}“)" if doc else ")")

    def new_line(self, prefix: str, category: str, bucket: str, tx: dict | None = None, **kw) -> CalcLine:
        line = CalcLine(line_id=self.next_id(prefix), tax_year=self.year, category=category, bucket=bucket,
                        date=kw.pop("date", tx["trade_date"] if tx else self.year_end), **kw)
        if tx:
            dep = self.depots.get(tx["depot_id"], {})
            line.depot_id = tx["depot_id"]
            line.depot = dep.get("name", "")
            line.broker = dep.get("broker_name", "")
            line.domestic = self.domestic(tx["depot_id"])
            line.isin = tx.get("isin")
            line.name = tx.get("security_name") or (self.securities.get(tx.get("isin") or "", {}) or {}).get("name")
            line.tx_ids.append(tx["id"])
            line.sources.append(self.tx_source(tx))
            if tx.get("document_id"):
                line.doc_ids.append(tx["document_id"])
            if tx.get("review_status") == "pruefen":
                line.downgrade(PROVISIONAL)
                line.notes.append("Buchung ist als „prüfen“ markiert")
            if tx.get("currency") != "EUR":
                fx = self.rule("FX_CONVERSION")
                line.rule_ids.append("FX_CONVERSION")
                line.downgrade(PROVISIONAL)
                line.notes.append(f"Fremdwährung {tx.get('currency')}: EUR-Wert mit Kurs {tx.get('fx_rate')} "
                                  f"[{tx.get('fx_source') or 'Quelle unbekannt'}] ({fx.status_label})")
        return line

    def apply_rule(self, line: CalcLine, rid: str) -> bool:
        """Hängt eine Regel an; liefert False, wenn sie für das Jahr nicht berechnet werden darf."""
        r = self.rule(rid)
        if rid not in line.rule_ids:
            line.rule_ids.append(rid)
        if not r.computable:
            line.status = MANUAL
            line.notes.append(f"Regel {rid} für {self.year} nicht verifiziert – keine Berechnung")
            return False
        if r.provisional:
            line.downgrade(PROVISIONAL)
        return True


# --------------------------------------------------------------------------- #
class CostBasisTracker:
    """Bestandsführung je Depot+ISIN über alle Jahre bis zum Ende des Steuerjahres."""

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.holdings: dict[tuple[int, str], Holding] = defaultdict(Holding)
        self.lines: list[CalcLine] = []
        self.qty_at: dict[tuple[int, str, str], float] = {}  # (depot, isin, Stichtag) -> Bestand
        self.held_in_year: set[tuple[int, str]] = set()

    def _events(self):
        ev = []
        for tx in self.ctx.tx_all:
            if tx.get("isin"):
                ev.append((tx["trade_date"], 1, "tx", tx))
        # AK-Korrekturen aus Fondsmeldungen (vor Buchungen desselben Tages: Bestand zu Tagesbeginn)
        for rep in self.ctx.reports:
            if rep["report_date"] <= self.ctx.year_end and rep.get("ak_correction_per_unit") is not None:
                ev.append((rep["report_date"], 0, "fund_ak", rep))
            if rep["report_date"] <= self.ctx.year_end:
                ev.append((rep["report_date"], 0, "snapshot", rep))
        # Nichtmeldefonds: AK-Erhöhung zum 31.12. früherer Jahre (nur wenn Regel verifiziert und Kurse vorhanden)
        for (isin, y), p in self.ctx.nmf.items():
            if int(y) < self.ctx.year:
                ev.append((date(int(y), 12, 31).isoformat(), 2, "nmf_ak", p))
        ev.append((self.ctx.year_end, 3, "year_end", None))
        return sorted(ev, key=lambda e: (e[0], e[1]))

    def run(self) -> None:
        year_start = date(self.ctx.year, 1, 1).isoformat()
        for d, _, kind, obj in self._events():
            if kind == "tx":
                self._tx(obj, in_year=obj["trade_date"] >= year_start)
            elif kind == "snapshot":
                for (dep, isin), h in self.holdings.items():
                    if isin == obj["isin"]:
                        self.qty_at[(dep, isin, obj["report_date"])] = h.qty
            elif kind == "fund_ak":
                self._fund_ak(obj)
            elif kind == "nmf_ak":
                self._nmf_ak(obj)
            elif kind == "year_end":
                for (dep, isin), h in self.holdings.items():
                    self.qty_at[(dep, isin, self.ctx.year_end)] = h.qty
            for (dep, isin), h in self.holdings.items():
                if h.qty > EPS and d >= year_start:
                    self.held_in_year.add((dep, isin))

    # ------------------------------------------------------------------ #
    def _tx(self, tx: dict, in_year: bool) -> None:
        key = (tx["depot_id"], tx["isin"])
        h = self.holdings[key]
        t = tx["tx_type"]
        q = tx.get("quantity") or 0.0
        if h.qty > EPS:
            pass
        if t in (TxType.BUY.value, TxType.TRANSFER_IN.value):
            if tx.get("amount_eur") is None:
                h.cost_known = False
                if in_year:
                    self.ctx.issue("Fehler", "Fehlende Daten",
                                   f"{t} ohne EUR-Betrag (Devisenkurs/Anschaffungskosten fehlen) – Anschaffungskosten "
                                   f"für {tx['isin']} unbekannt", self.ctx.tx_source(tx))
            else:
                h.cost += tx["amount_eur"]  # Gebühren werden NICHT aktiviert (§ 27a Abs 4 Z 2 EStG)
            if t == TxType.TRANSFER_IN.value:
                self.ctx.issue("Warnung", "Offene steuerliche Frage",
                               f"Depoteingang {tx['isin']}: übernommene Anschaffungskosten prüfen", self.ctx.tx_source(tx))
            h.qty += q
        elif t == TxType.SELL.value:
            self._sell(tx, h, in_year)
        elif t == TxType.TRANSFER_OUT.value:
            if h.qty > EPS:
                share = min(1.0, q / h.qty)
                h.cost -= h.cost * share
                h.qty = max(0.0, h.qty - q)
            if in_year:
                self.ctx.issue("Hinweis", "Offene steuerliche Frage",
                               f"Depotausgang {tx['isin']}: Übertrag ohne Realisierung angenommen – prüfen "
                               "(z. B. Schenkung, Wegzug)", self.ctx.tx_source(tx))
        elif t == TxType.SPLIT.value:
            if tx.get("ratio"):
                h.qty *= tx["ratio"]
        elif t == TxType.CAPITAL_REPAYMENT.value or (
                t in (TxType.DIVIDEND.value, TxType.DISTRIBUTION.value)
                and tx.get("income_category") == IncomeCategory.CAPITAL_REPAYMENT.value):
            self._capital_repayment(tx, h, in_year)
        elif t == TxType.CORPORATE_ACTION.value and in_year:
            self.ctx.issue("Warnung", "Offene steuerliche Frage",
                           f"Kapitalmaßnahme {tx['isin']} – Auswirkung auf Bestand/Anschaffungskosten manuell prüfen",
                           self.ctx.tx_source(tx))

    def _sell(self, tx: dict, h: Holding, in_year: bool) -> None:
        ctx = self.ctx
        q = tx.get("quantity") or 0.0
        sec = ctx.securities.get(tx["isin"], {}) or {}
        if not in_year:
            if h.qty + 1e-6 < q:
                h.history_gap = True
            share = min(1.0, q / h.qty) if h.qty > EPS else 1.0
            h.cost -= h.cost * share
            h.qty = max(0.0, h.qty - q)
            return
        line = ctx.new_line("VK", CAT_GAIN, BUCKET_27_5, tx, gross=tx.get("amount_eur"), fees=tx.get("fees_eur") or 0)
        line.rate = ctx.rules.rate("RATE_27_5")
        ok = ctx.apply_rule(line, "RATE_27_5") & ctx.apply_rule(line, "COST_BASIS_AVERAGE")
        ctx.apply_rule(line, "NO_INCIDENTAL_COSTS")
        if tx.get("kest_at_eur"):
            line.kest_at = tx["kest_at_eur"]
        tc = sec.get("tax_class") or TaxClass.UNGEKLAERT.value
        if tc in (TaxClass.DERIVAT.value, TaxClass.IMMOBILIENFONDS.value, TaxClass.SONSTIGE.value):
            line.status = MANUAL
            line.notes.append(f"Steuerliche Einstufung „{tc}“ wird nicht automatisch berechnet")
            ok = False
        elif tc == TaxClass.UNGEKLAERT.value or not sec.get("tax_class_verified"):
            line.downgrade(PROVISIONAL)
            line.notes.append("Steuerliche Einstufung des Wertpapiers ungeprüft")
        if h.qty + 1e-6 < q or h.history_gap:
            line.status = MANUAL
            line.notes.append(f"Bestand vor Verkauf {h.qty:g} < Verkaufsmenge {q:g} – Kaufhistorie unvollständig")
            ctx.issue("Fehler", "Fehlende Daten",
                      f"Verkauf {tx['isin']} am {tx['trade_date']}: Anschaffungskosten unbekannt "
                      f"(Bestand {h.qty:g}, verkauft {q:g}). Fehlende Käufe/Depoteingänge erfassen.", ctx.tx_source(tx))
            ok = False
        if not h.cost_known:
            line.status = MANUAL
            line.notes.append("Anschaffungskosten unvollständig (Kauf ohne EUR-Betrag)")
            ok = False
        if tx.get("amount_eur") is None:
            line.status = MANUAL
            line.notes.append("Verkaufserlös in EUR fehlt (Devisenkurs)")
            ctx.issue("Fehler", "Fehlende Daten", f"Verkauf {tx['isin']}: EUR-Erlös fehlt", ctx.tx_source(tx))
            ok = False
        avg = h.cost / h.qty if h.qty > EPS else 0.0
        cost_sold = avg * min(q, h.qty)
        if ok:
            gain = tx["amount_eur"] - cost_sold
            line.amount = round(gain, 2)
            line.category = CAT_GAIN if gain >= 0 else CAT_LOSS
            line.steps += [
                f"Bestand vor Verkauf: {h.qty:g} Stk., Anschaffungskosten gesamt {h.cost:.2f} EUR",
                f"Gleitender Durchschnittspreis: {h.cost:.2f} / {h.qty:g} = {avg:.6f} EUR",
                f"Anschaffungskosten verkaufter Anteile: {q:g} × {avg:.6f} = {cost_sold:.2f} EUR",
                f"Veräußerungserlös (ohne Abzug von Gebühren {line.fees:.2f} EUR): {tx['amount_eur']:.2f} EUR",
                f"Ergebnis: {tx['amount_eur']:.2f} − {cost_sold:.2f} = {gain:.2f} EUR",
            ]
            line.e1kv_key = ("gains_" if gain >= 0 else "losses_") + ("inland" if line.domestic else "ausland")
        else:
            line.steps.append("Nicht berechnet – siehe Hinweise")
        self.lines.append(line)
        share = min(1.0, q / h.qty) if h.qty > EPS else 1.0
        h.cost -= h.cost * share
        h.qty = max(0.0, h.qty - q)
        if h.qty <= EPS:
            h.qty, h.cost, h.cost_known, h.history_gap = 0.0, 0.0, True, False

    def _capital_repayment(self, tx: dict, h: Holding, in_year: bool) -> None:
        ctx = self.ctx
        verified = bool(tx.get("income_category_verified")) and (
            tx["tx_type"] == TxType.CAPITAL_REPAYMENT.value
            or tx.get("income_category") == IncomeCategory.CAPITAL_REPAYMENT.value)
        amt = tx.get("amount_eur")
        if not verified or amt is None:
            return  # wird in IncomeClassifier als ungeklärt ausgewiesen
        r = ctx.rules.rule("CAPITAL_REPAYMENT", int(tx["trade_date"][:4]))
        if not r.computable:
            return
        before = h.cost
        reduce = min(amt, max(h.cost, 0.0))
        h.cost -= reduce
        excess = amt - reduce
        if in_year:
            line = ctx.new_line("KR", CAT_CAPREPAY, BUCKET_NONE, tx, gross=amt, amount=0.0)
            ctx.apply_rule(line, "CAPITAL_REPAYMENT")
            line.steps += [f"Anschaffungskosten vorher: {before:.2f} EUR",
                           f"Kapitalrückzahlung: {amt:.2f} EUR → AK-Minderung {reduce:.2f} EUR",
                           f"Anschaffungskosten nachher: {h.cost:.2f} EUR"]
            self.lines.append(line)
            if excess > 0.005:
                g = ctx.new_line("KR", CAT_GAIN, BUCKET_27_5, tx, gross=excess, amount=round(excess, 2))
                g.rate = ctx.rules.rate("RATE_27_5")
                ctx.apply_rule(g, "CAPITAL_REPAYMENT")
                ctx.apply_rule(g, "RATE_27_5")
                g.steps.append(f"Kapitalrückzahlung übersteigt Anschaffungskosten um {excess:.2f} EUR → "
                               "Veräußerungsvorgang (§ 4 Abs 12 EStG)")
                g.e1kv_key = "gains_" + ("inland" if g.domestic else "ausland")
                self.lines.append(g)

    def _fund_ak(self, rep: dict) -> None:
        corr = rep.get("ak_correction_per_unit")
        fx = rep.get("fx_rate") or 1.0
        if rep.get("currency", "EUR") != "EUR" and not rep.get("fx_rate"):
            return
        for (dep, isin), h in self.holdings.items():
            if isin == rep["isin"] and h.qty > EPS:
                h.cost += corr * h.qty / fx

    def _nmf_ak(self, p: dict) -> None:
        r = self.ctx.rules.rule("NICHTMELDEFONDS_PAUSCHAL", int(p["tax_year"]))
        if not r.computable or p.get("first_price") is None or p.get("last_price") is None:
            return
        per_unit = nmf_per_unit(self.ctx.rules, p["first_price"], p["last_price"])
        fx = p.get("fx_rate_last") or 1.0
        for (dep, isin), h in self.holdings.items():
            if isin == p["isin"] and h.qty > EPS:
                h.cost += per_unit * h.qty / fx


def nmf_per_unit(rules: TaxRules, first: float, last: float) -> float:
    f_diff = float(rules.param("NICHTMELDEFONDS_PAUSCHAL", "factor_difference"))
    f_min = float(rules.param("NICHTMELDEFONDS_PAUSCHAL", "factor_minimum"))
    return max(f_diff * (last - first), f_min * last)


# --------------------------------------------------------------------------- #
class IncomeClassifier:
    def __init__(self, ctx: Context, tracker: CostBasisTracker):
        self.ctx = ctx
        self.tracker = tracker
        self.lines: list[CalcLine] = []
        self.fees: list[dict] = []

    def run(self) -> None:
        y = str(self.ctx.year)
        for tx in self.ctx.tx_all:
            if tx["trade_date"][:4] != y:
                continue
            t = tx["tx_type"]
            if (tx.get("fees_eur") or 0) > 0 or t == TxType.FEE.value:
                self.fees.append({
                    "Datum": tx["trade_date"], "Depot": self.ctx.depots[tx["depot_id"]]["name"],
                    "ISIN": tx.get("isin"), "Art": t,
                    "Gebühr EUR": (tx.get("fees_eur") or 0) if t != TxType.FEE.value else (tx.get("amount_eur") or 0),
                    "Behandlung": "nicht abzugsfähig (§ 27a Abs 4 Z 2, § 20 Abs 2 EStG) – nur Ausweis",
                    "Quelle": self.ctx.tx_source(tx)})
            if t == TxType.DIVIDEND.value:
                self._dividend(tx)
            elif t == TxType.DISTRIBUTION.value:
                self._distribution(tx)
            elif t == TxType.INTEREST.value:
                self._interest(tx)
            elif t == TxType.AGE.value:
                self._manual_age(tx)
            elif t == TxType.CAPITAL_REPAYMENT.value and not tx.get("income_category_verified"):
                self._unclear(tx, "Kapitalrückzahlung ohne bestätigten Beleg – steuerliche Behandlung ungeklärt "
                                  "(nicht als AK-Minderung berücksichtigt)")
            elif t == TxType.TAX_REFUND.value:
                self.ctx.issue("Hinweis", "Offene steuerliche Frage",
                               "Steuererstattung gebucht – anrechenbare Quellensteuer/KESt ggf. korrigieren",
                               self.ctx.tx_source(tx))

    # ------------------------------------------------------------------ #
    def _base_checks(self, line: CalcLine, tx: dict) -> bool:
        if tx.get("amount_eur") is None:
            line.status = MANUAL
            line.notes.append("EUR-Betrag fehlt (Fremdwährung ohne Devisenkurs)")
            self.ctx.issue("Fehler", "Fehlende Daten", f"{tx['tx_type']} {tx.get('isin') or ''}: EUR-Betrag fehlt",
                           self.ctx.tx_source(tx))
            return False
        return True

    def _withholding(self, line: CalcLine, tx: dict, sec: dict) -> None:
        ctx = self.ctx
        wht = tx.get("withholding_tax_eur") or 0.0
        line.withholding_tax = wht
        line.kest_at = tx.get("kest_at_eur") or 0.0
        if line.kest_at:
            ctx.apply_rule(line, "DOMESTIC_KEST")
            if not line.domestic:
                ctx.issue("Warnung", "Widerspruch",
                          f"Österreichische KESt gebucht, Depot „{line.depot}“ ist für {ctx.year} aber nicht als "
                          "„KESt-Abzug durch Broker“ markiert", ctx.tx_source(tx))
        if wht <= 0:
            return
        country = tx.get("withholding_country") or sec.get("country")
        line.rule_ids.append("FOREIGN_TAX_CREDIT")
        rule = ctx.rule("FOREIGN_TAX_CREDIT")
        dba = ctx.rules.dba_rate(country)
        gross = line.gross or 0.0
        if not country:
            line.unclear_tax = wht
            line.notes.append("Quellenstaat unbekannt – anrechenbarer Betrag ungeklärt")
            ctx.issue("Warnung", "Fehlende Daten", f"Quellensteuer {wht:.2f} EUR ohne Quellenstaat",
                      ctx.tx_source(tx))
        elif not rule.computable or not dba or not dba.get("verified") or dba.get("rate") is None:
            line.unclear_tax = wht
            note = (dba or {}).get("note", "kein DBA-Satz hinterlegt")
            line.notes.append(f"DBA-Satz {country} nicht verifiziert ({note}) – anrechenbarer Betrag ungeklärt")
            ctx.issue("Warnung", "Offene steuerliche Frage",
                      f"Quellensteuer {country} {wht:.2f} EUR: DBA-Höchstsatz nicht verifiziert – Anrechnung prüfen",
                      ctx.tx_source(tx))
            line.downgrade(PROVISIONAL)
        else:
            rate_at = ctx.rules.rate("RATE_27_5")
            cap_dba = gross * dba["rate"]
            cap_at = gross * rate_at
            cred = min(wht, cap_dba, cap_at)
            line.creditable_tax_max = round(cred, 2)
            line.non_creditable_tax = round(wht - cred, 2)
            if rule.provisional:
                line.downgrade(PROVISIONAL)
            line.steps += [
                f"Quellensteuer einbehalten: {wht:.2f} EUR ({country})",
                f"Höchstbetrag DBA: {gross:.2f} × {dba['rate']:.2%} = {cap_dba:.2f} EUR",
                f"Höchstbetrag österr. Steuer: {gross:.2f} × {rate_at:.2%} = {cap_at:.2f} EUR",
                f"Anrechenbar (vor Verlustausgleich): min({wht:.2f}; {cap_dba:.2f}; {cap_at:.2f}) = {cred:.2f} EUR",
                f"Nicht anrechenbar (ggf. im Quellenstaat rückforderbar): {wht - cred:.2f} EUR",
            ]

    def _security(self, tx: dict) -> dict:
        return self.ctx.securities.get(tx.get("isin") or "", {}) or {}

    def _dividend(self, tx: dict) -> None:
        ctx = self.ctx
        sec = self._security(tx)
        cat = tx.get("income_category") or "auto"
        stype = sec.get("security_type")
        if cat == IncomeCategory.CAPITAL_REPAYMENT.value:
            if not tx.get("income_category_verified"):
                self._unclear(tx, "Als Kapitalrückzahlung gekennzeichnet, aber ohne bestätigten Beleg")
            return  # bestätigt → CostBasisTracker
        if cat == IncomeCategory.UNCLEAR.value:
            self._unclear(tx, "Ertragsart als ungeklärt gekennzeichnet")
            return
        if sec.get("tax_class") == TaxClass.INVESTMENTFONDS.value or stype in [s.value for s in FUND_SECURITY_TYPES]:
            self._distribution(tx)
            return
        if stype in (SecurityType.REIT.value, SecurityType.BDC.value):
            if cat not in (IncomeCategory.DIVIDEND.value, IncomeCategory.OTHER_DISTRIBUTION.value) or \
                    not tx.get("income_category_verified"):
                self._unclear(tx, f"{stype}: Ertragsbestandteile (Dividende/sonstige Ausschüttung/"
                                  "Kapitalrückzahlung) nicht belegt – keine automatische Einstufung", reit=True)
                return
        line = ctx.new_line("DIV", CAT_DIVIDEND if cat != IncomeCategory.OTHER_DISTRIBUTION.value else CAT_REIT_OTHER,
                            BUCKET_27_5, tx, gross=tx.get("amount_eur"))
        line.rate = ctx.rules.rate("RATE_27_5")
        ok = self._base_checks(line, tx) and ctx.apply_rule(line, "RATE_27_5")
        tc = sec.get("tax_class") or TaxClass.UNGEKLAERT.value
        if stype in (SecurityType.REIT.value, SecurityType.BDC.value):
            # Keine automatische Regel: Berechnung nur, weil die Ertragsart je Buchung bestätigt wurde.
            line.rule_ids.append("REIT_BDC")
            line.downgrade(PROVISIONAL)
            line.notes.append(f"{stype}: Ertragsart je Buchung als „{cat}“ bestätigt – Beleg dokumentieren")
        if tc in (TaxClass.DERIVAT.value, TaxClass.IMMOBILIENFONDS.value, TaxClass.SONSTIGE.value):
            line.status = MANUAL
            line.notes.append(f"Steuerliche Einstufung „{tc}“ wird nicht automatisch berechnet")
            ok = False
        elif tc == TaxClass.UNGEKLAERT.value or not sec.get("tax_class_verified"):
            line.downgrade(PROVISIONAL)
            line.notes.append("Steuerliche Einstufung des Wertpapiers ungeprüft (Annahme: Beteiligungsertrag)")
            if tx.get("isin"):
                ctx.issue("Hinweis", "Offene steuerliche Frage",
                          f"Steuerliche Einstufung von {tx.get('isin')} ungeprüft", tx.get("isin"))
        if not tx.get("isin"):
            line.downgrade(PROVISIONAL)
            line.notes.append("Ertrag ohne ISIN")
        if ok:
            line.amount = round(tx["amount_eur"], 2)
            line.steps.insert(0, f"Bruttoertrag: {tx['amount_eur']:.2f} EUR (Quellensteuer nicht abgezogen)")
            line.e1kv_key = "dividends_" + ("inland" if line.domestic else "ausland")
        self._withholding(line, tx, sec)
        self.lines.append(line)

    def _distribution(self, tx: dict) -> None:
        ctx = self.ctx
        sec = self._security(tx)
        fs = sec.get("fund_status") or FundStatus.UNKNOWN.value
        stype = sec.get("security_type")
        is_fund = fs in (FundStatus.MELDEFONDS.value, FundStatus.NICHTMELDEFONDS.value, FundStatus.UNKNOWN.value) \
            or stype in [s.value for s in FUND_SECURITY_TYPES] or sec.get("tax_class") == TaxClass.INVESTMENTFONDS.value
        if not is_fund:
            # Ausschüttung einer Nicht-Fonds-Gesellschaft → wie Dividende behandeln (mit Hinweis)
            tx = dict(tx, tx_type=TxType.DIVIDEND.value)
            self._dividend(tx)
            if self.lines:
                self.lines[-1].notes.append("Als „Ausschüttung“ gebucht, Wertpapier ist kein Fonds → wie Dividende")
            return
        line = ctx.new_line("FA", CAT_FUND_DIST, BUCKET_27_5, tx, gross=tx.get("amount_eur"))
        line.rate = ctx.rules.rate("RATE_27_5")
        ok = self._base_checks(line, tx) and ctx.apply_rule(line, "RATE_27_5")
        if fs == FundStatus.NICHTMELDEFONDS.value:
            ok = ctx.apply_rule(line, "NICHTMELDEFONDS_DISTRIBUTIONS") and ok
            if ok:
                line.amount = round(tx["amount_eur"], 2)
                line.steps.append(f"Nichtmeldefonds: tatsächliche Ausschüttung voll steuerpflichtig: "
                                  f"{tx['amount_eur']:.2f} EUR")
        elif fs == FundStatus.MELDEFONDS.value:
            ctx.apply_rule(line, "MELDEFONDS_AGE")
            rep = self._matching_report(tx)
            if rep and rep.get("taxable_distribution_per_unit") is not None and ok:
                units = tx.get("quantity") or self.tracker.qty_at.get((tx["depot_id"], tx["isin"], rep["report_date"]))
                fx = rep.get("fx_rate") or 1.0
                if not units:
                    line.status = MANUAL
                    line.notes.append("Bestand zum Ausschüttungstag unbekannt")
                else:
                    taxable = rep["taxable_distribution_per_unit"] * units / fx
                    free = max(0.0, tx["amount_eur"] - taxable)
                    line.amount = round(taxable, 2)
                    line.sources.append(f"Fondsmeldung #{rep['id']} ({rep['source']}, {rep['report_date']})")
                    line.steps += [f"Bruttoausschüttung laut Buchung: {tx['amount_eur']:.2f} EUR",
                                   f"Steuerpflichtiger Teil laut Meldung: {rep['taxable_distribution_per_unit']} "
                                   f"{rep['currency']} × {units:g} Anteile / {fx} = {taxable:.2f} EUR",
                                   f"Nicht steuerpflichtiger Teil (bereits versteuert/steuerfrei): {free:.2f} EUR"]
                    if rep.get("review_status") != "geprueft":
                        line.downgrade(PROVISIONAL)
                        line.notes.append("Fondsmeldung noch nicht geprüft")
                    if free > 0.005:
                        fl = ctx.new_line("FA", CAT_FUND_DIST_FREE, BUCKET_NONE, tx, gross=free, amount=0.0)
                        fl.steps.append(f"Kein Ansatz: {free:.2f} EUR laut Fondsmeldung nicht steuerpflichtig "
                                        "(Vermeidung Doppelbesteuerung)")
                        fl.rule_ids.append("MELDEFONDS_AGE")
                        self.lines.append(fl)
                    if rep.get("creditable_tax_per_unit"):
                        line.creditable_tax_max = round(rep["creditable_tax_per_unit"] * units / fx, 2)
                        line.steps.append(f"Anrechenbare Steuer laut Meldung: {line.creditable_tax_max:.2f} EUR")
            elif ok:
                line.amount = round(tx["amount_eur"], 2)
                line.downgrade(PROVISIONAL)
                line.notes.append("Keine OeKB-Ausschüttungsmeldung – voller Bruttobetrag angesetzt; steuerpflichtigen "
                                  "Anteil prüfen")
                line.steps.append(f"Bruttoausschüttung {tx['amount_eur']:.2f} EUR voll angesetzt (Meldung fehlt)")
                ctx.issue("Warnung", "Fehlende Daten",
                          f"Ausschüttung {tx['isin']} am {tx['trade_date']}: keine passende OeKB-Meldung – "
                          "steuerpflichtiger Anteil ungeprüft", ctx.tx_source(tx))
        else:
            line.status = MANUAL
            line.notes.append("Meldefondsstatus unbekannt – steuerliche Behandlung nicht bestimmbar")
            ctx.issue("Fehler", "Offene steuerliche Frage",
                      f"Fondsausschüttung {tx.get('isin')}: Meldefondsstatus unbekannt", ctx.tx_source(tx))
            ok = False
        if line.amount is not None:
            line.e1kv_key = "fund_dist_" + ("inland" if line.domestic else "ausland")
        if line.creditable_tax_max == 0:
            self._withholding(line, tx, sec)
        else:
            line.withholding_tax = tx.get("withholding_tax_eur") or 0.0
            line.kest_at = tx.get("kest_at_eur") or 0.0
        self.lines.append(line)

    def _matching_report(self, tx: dict) -> dict | None:
        d = date.fromisoformat(tx["trade_date"])
        best = None
        for rep in self.ctx.reports:
            if rep["isin"] != tx["isin"]:
                continue
            ref = rep.get("distribution_date") or rep["report_date"]
            delta = abs((date.fromisoformat(ref) - d).days)
            if delta <= 14 and (best is None or delta < best[0]):
                best = (delta, rep)
        return best[1] if best else None

    def _interest(self, tx: dict) -> None:
        ctx = self.ctx
        sec = self._security(tx)
        if tx.get("isin"):
            line = ctx.new_line("ZI", CAT_INTEREST_27, BUCKET_27_5, tx, gross=tx.get("amount_eur"))
            line.rate = ctx.rules.rate("RATE_27_5")
            ok = self._base_checks(line, tx) and ctx.apply_rule(line, "RATE_27_5")
            if sec.get("tax_class") != TaxClass.FORDERUNGSWERTPAPIER.value or not sec.get("tax_class_verified"):
                line.downgrade(PROVISIONAL)
                line.notes.append("Einstufung als Forderungswertpapier ungeprüft")
            key = "dividends_"
        else:
            line = ctx.new_line("ZI", CAT_INTEREST_25, BUCKET_25, tx, gross=tx.get("amount_eur"))
            line.rate = ctx.rules.rate("RATE_25")
            ok = self._base_checks(line, tx) and ctx.apply_rule(line, "RATE_25")
            line.downgrade(PROVISIONAL)
            line.notes.append("Annahme: Zinsen aus Geldeinlage bei einem Kreditinstitut (25 %) – prüfen")
            key = "interest25_"
        if ok:
            line.amount = round(tx["amount_eur"], 2)
            line.steps.append(f"Zinsertrag brutto {tx['amount_eur']:.2f} EUR × {line.rate:.2%}")
            line.e1kv_key = key + ("inland" if line.domestic else "ausland")
        self._withholding(line, tx, sec)
        self.lines.append(line)

    def _manual_age(self, tx: dict) -> None:
        ctx = self.ctx
        y = str(ctx.year)
        covered = [r for r in ctx.reports if r["isin"] == tx.get("isin") and r["report_date"][:4] == y
                   and r.get("age_per_unit") is not None]
        line = ctx.new_line("AGE", CAT_AGE_MANUAL, BUCKET_27_5, tx, gross=tx.get("amount_eur"))
        line.rate = ctx.rules.rate("RATE_27_5")
        ctx.apply_rule(line, "MELDEFONDS_AGE")
        if covered:
            line.bucket = BUCKET_NONE
            line.amount = 0.0
            line.steps.append(f"Nicht angesetzt: AgE für {tx.get('isin')} {y} bereits über Fondsmeldung "
                              f"#{covered[0]['id']} erfasst (Vermeidung Doppelzählung)")
            ctx.issue("Warnung", "Widerspruch",
                      f"Manuell gebuchte AgE {tx.get('isin')} und OeKB-Meldung für {y} vorhanden – nur die Meldung wird "
                      "angesetzt", ctx.tx_source(tx))
        elif self._base_checks(line, tx) and ctx.apply_rule(line, "RATE_27_5"):
            line.amount = round(tx["amount_eur"], 2)
            line.downgrade(PROVISIONAL)
            line.notes.append("Manuell erfasste AgE – Beleg (OeKB-Meldung) prüfen")
            line.steps.append(f"AgE laut manueller Buchung: {tx['amount_eur']:.2f} EUR")
            line.e1kv_key = "age_" + ("inland" if line.domestic else "ausland")
        line.withholding_tax = tx.get("withholding_tax_eur") or 0.0
        line.kest_at = tx.get("kest_at_eur") or 0.0
        self.lines.append(line)

    def _unclear(self, tx: dict, reason: str, reit: bool = False) -> None:
        ctx = self.ctx
        line = ctx.new_line("UK", CAT_UNCLEAR, BUCKET_UNCLEAR, tx, gross=tx.get("amount_eur"))
        line.status = MANUAL
        line.withholding_tax = tx.get("withholding_tax_eur") or 0.0
        line.unclear_tax = line.withholding_tax
        line.notes.append(reason)
        line.steps.append(f"Betrag {tx.get('amount_eur')} EUR nicht in die Bemessungsgrundlage übernommen")
        if reit:
            line.rule_ids.append("REIT_BDC")
        ctx.issue("Fehler", "Offene steuerliche Frage", f"{tx.get('isin') or ''} {tx['trade_date']}: {reason}",
                  ctx.tx_source(tx))
        self.lines.append(line)


# --------------------------------------------------------------------------- #
class FundProcessor:
    def __init__(self, ctx: Context, tracker: CostBasisTracker):
        self.ctx = ctx
        self.tracker = tracker
        self.lines: list[CalcLine] = []
        self.fund_rows: list[dict] = []
        self.nmf_rows: list[dict] = []

    def run(self) -> None:
        self._meldefonds()
        self._nichtmeldefonds()
        self._missing_reports()

    def _meldefonds(self) -> None:
        ctx = self.ctx
        y = str(ctx.year)
        for rep in ctx.reports:
            if rep["report_date"][:4] != y:
                continue
            sec = ctx.securities.get(rep["isin"], {}) or {}
            if sec.get("fund_status") == FundStatus.NICHTMELDEFONDS.value or rep.get("is_meldefonds") == 0:
                ctx.issue("Warnung", "Widerspruch", f"Meldung für {rep['isin']} vorhanden, Fonds ist als "
                                                    "Nichtmeldefonds gekennzeichnet", f"Fondsmeldung #{rep['id']}")
            fx = rep.get("fx_rate") or 1.0
            for (dep, isin, d), units in self.tracker.qty_at.items():
                if isin != rep["isin"] or d != rep["report_date"] or units <= EPS:
                    continue
                dep_row = ctx.depots[dep]
                row = {"ISIN": isin, "Fondsname": rep.get("fund_name") or sec.get("name"),
                       "Depot": dep_row["name"], "Broker": dep_row["broker_name"],
                       "Meldefondsstatus": sec.get("fund_status"), "Meldungsart": rep["report_type"],
                       "Geschäftsjahresende": rep.get("fiscal_year_end"), "Meldedatum": rep["report_date"],
                       "Bestand zum Meldedatum": units, "Währung": rep["currency"], "Devisenkurs": fx,
                       "Ausschüttung je Anteil": rep.get("distribution_per_unit"),
                       "AgE je Anteil": rep.get("age_per_unit"),
                       "AK-Korrektur je Anteil": rep.get("ak_correction_per_unit"),
                       "Anrechenbare Steuer je Anteil": rep.get("creditable_tax_per_unit"),
                       "AgE gesamt EUR": None, "AK-Korrektur gesamt EUR": None,
                       "Quelle": f"Fondsmeldung #{rep['id']} ({rep['source']}, importiert {rep['imported_at']})",
                       "Version": rep["version"], "Prüfstatus": rep["review_status"]}
                if rep.get("age_per_unit") is not None:
                    line = ctx.new_line("AGE", CAT_AGE, BUCKET_27_5, None, date=rep["report_date"])
                    line.depot_id, line.depot, line.broker = dep, dep_row["name"], dep_row["broker_name"]
                    line.domestic = ctx.domestic(dep)
                    line.isin, line.name = isin, rep.get("fund_name") or sec.get("name")
                    line.rate = ctx.rules.rate("RATE_27_5")
                    line.sources.append(row["Quelle"])
                    if rep.get("document_id"):
                        line.doc_ids.append(rep["document_id"])
                    ok = ctx.apply_rule(line, "MELDEFONDS_AGE") and ctx.apply_rule(line, "RATE_27_5")
                    if rep["review_status"] != "geprueft":
                        line.downgrade(PROVISIONAL)
                        line.notes.append("Fondsmeldung ungeprüft")
                    if rep["currency"] != "EUR":
                        line.downgrade(PROVISIONAL)
                        line.notes.append(f"Umrechnung {rep['currency']} mit Kurs {fx}")
                    if ok:
                        age = rep["age_per_unit"] * units / fx
                        line.amount = line.gross = round(age, 2)
                        line.steps.append(f"AgE: {rep['age_per_unit']} {rep['currency']} × {units:g} Anteile / {fx} "
                                          f"= {age:.2f} EUR (Zufluss zum Meldedatum {rep['report_date']})")
                        if rep.get("creditable_tax_per_unit"):
                            line.creditable_tax_max = round(rep["creditable_tax_per_unit"] * units / fx, 2)
                            line.steps.append(f"Anrechenbare Steuer laut Meldung: {line.creditable_tax_max:.2f} EUR")
                        if rep.get("kest_per_unit") and line.domestic:
                            line.kest_at = round(rep["kest_per_unit"] * units / fx, 2)
                        line.e1kv_key = "age_" + ("inland" if line.domestic else "ausland")
                        row["AgE gesamt EUR"] = line.amount
                    self.lines.append(line)
                if rep.get("ak_correction_per_unit") is not None:
                    row["AK-Korrektur gesamt EUR"] = round(rep["ak_correction_per_unit"] * units / fx, 2)
                self.fund_rows.append(row)

    def _nichtmeldefonds(self) -> None:
        ctx = self.ctx
        rule = ctx.rule("NICHTMELDEFONDS_PAUSCHAL")
        for (dep, isin, d), units in self.tracker.qty_at.items():
            if d != ctx.year_end or units <= EPS:
                continue
            sec = ctx.securities.get(isin, {}) or {}
            if sec.get("fund_status") != FundStatus.NICHTMELDEFONDS.value:
                continue
            dep_row = ctx.depots[dep]
            p = ctx.nmf.get((isin, ctx.year))
            line = ctx.new_line("NMF", CAT_NMF, BUCKET_27_5, None, date=ctx.year_end)
            line.depot_id, line.depot, line.broker = dep, dep_row["name"], dep_row["broker_name"]
            line.domestic = ctx.domestic(dep)
            line.isin, line.name = isin, sec.get("name")
            line.rate = ctx.rules.rate("RATE_27_5")
            row = {"ISIN": isin, "Name": sec.get("name"), "Depot": dep_row["name"], "Steuerjahr": ctx.year,
                   "Bestand 31.12.": units, "Erster Rücknahmepreis": p and p.get("first_price"),
                   "Datum erster Preis": p and p.get("first_price_date"), "Letzter Rücknahmepreis": p and p.get("last_price"),
                   "Datum letzter Preis": p and p.get("last_price_date"), "Währung": p and p.get("currency"),
                   "Devisenkurs 31.12.": p and p.get("fx_rate_last"),
                   "Regel": f"{rule.title} ({rule.legal_basis})", "Regelstatus": rule.status_label,
                   "Rechenschritte": "", "Ergebnis EUR": None, "Datenlücken / Prüfhinweise": ""}
            gaps = []
            ok = ctx.apply_rule(line, "NICHTMELDEFONDS_PAUSCHAL")
            if not ok:
                gaps.append(f"Regel für {ctx.year} nicht verifiziert – keine Berechnung")
                ctx.issue("Fehler", "Offene steuerliche Frage",
                          f"Nichtmeldefonds {isin}: Pauschalbesteuerung für {ctx.year} nicht verifiziert – manuell "
                          "steuerlich prüfen", isin)
            if not p or p.get("first_price") is None or p.get("last_price") is None:
                gaps.append("Erster und/oder letzter Rücknahmepreis des Kalenderjahres fehlt")
                ctx.issue("Fehler", "Fehlende Daten", f"Nichtmeldefonds {isin}: Kursdaten {ctx.year} fehlen", isin)
                line.status = MANUAL
                ok = False
            elif p.get("currency", "EUR") != "EUR" and not p.get("fx_rate_last"):
                gaps.append("Devisenkurs fehlt")
                line.status = MANUAL
                ok = False
            if ok:
                rp = ctx.rules
                fd = float(rp.param("NICHTMELDEFONDS_PAUSCHAL", "factor_difference"))
                fm = float(rp.param("NICHTMELDEFONDS_PAUSCHAL", "factor_minimum"))
                diff = fd * (p["last_price"] - p["first_price"])
                minimum = fm * p["last_price"]
                per_unit = max(diff, minimum)
                fx = p.get("fx_rate_last") or 1.0
                total = per_unit * units / fx
                line.amount = line.gross = round(total, 2)
                line.steps += [
                    f"{fd:.0%} × (letzter {p['last_price']} − erster {p['first_price']}) = {diff:.4f}",
                    f"Mindestens {fm:.0%} × letzter Rücknahmepreis {p['last_price']} = {minimum:.4f}",
                    f"Pauschale AgE je Anteil = max({diff:.4f}; {minimum:.4f}) = {per_unit:.4f} {p.get('currency')}",
                    f"Gesamt: {per_unit:.4f} × {units:g} Anteile / {fx} = {total:.2f} EUR (Zufluss 31.12.{ctx.year})",
                    "Anschaffungskosten erhöhen sich um diesen Betrag",
                ]
                line.sources.append(f"Kursdaten nmf_prices #{p['id']} ({p.get('source')})")
                if "kein Rücknahmepreis" in (p.get("source") or ""):
                    gaps.append("Börsenschlusskurse statt Rücknahmepreisen – mit Fondsgesellschaft/OeKB abgleichen")
                if p.get("review_status") != "geprueft":
                    line.downgrade(PROVISIONAL)
                    gaps.append("Kursdaten ungeprüft")
                line.e1kv_key = "age_" + ("inland" if line.domestic else "ausland")
                row["Ergebnis EUR"] = line.amount
            row["Rechenschritte"] = " | ".join(line.steps) or "nicht berechnet"
            row["Datenlücken / Prüfhinweise"] = "; ".join(gaps) or "-"
            self.nmf_rows.append(row)
            self.lines.append(line)

    def _missing_reports(self) -> None:
        ctx = self.ctx
        y = str(ctx.year)
        reported = {r["isin"] for r in ctx.reports if r["report_date"][:4] == y}
        for dep, isin in sorted(self.tracker.held_in_year):
            sec = ctx.securities.get(isin, {}) or {}
            fs = sec.get("fund_status")
            is_fund_type = sec.get("security_type") in [s.value for s in FUND_SECURITY_TYPES]
            if fs == FundStatus.MELDEFONDS.value and isin not in reported:
                ctx.issue("Warnung", "Fehlende Daten",
                          f"Meldefonds {isin}: keine OeKB-Meldung mit Meldedatum in {y} erfasst – AgE/AK-Korrektur "
                          "fehlen (oder keine Meldung erfolgt → ggf. Nichtmeldefonds)", isin)
            elif is_fund_type and fs in (FundStatus.UNKNOWN.value, FundStatus.NO_FUND.value, None):
                ctx.issue("Fehler", "Offene steuerliche Frage",
                          f"Fonds {isin} ({sec.get('security_type')}): Meldefondsstatus unbekannt – steuerliche "
                          "Behandlung nicht bestimmbar", isin)


# --------------------------------------------------------------------------- #
class LossOffset:
    def __init__(self, ctx: Context, lines: list[CalcLine]):
        self.ctx = ctx
        self.lines = lines
        self.rows: list[LossOffsetRow] = []

    def run(self) -> None:
        ctx = self.ctx
        computable = [l for l in self.lines if l.amount is not None and l.status != MANUAL]
        losses = [l for l in computable if l.bucket == BUCKET_27_5 and l.amount < 0]
        positives = [l for l in computable if l.bucket == BUCKET_27_5 and l.amount > 0]
        rule = ctx.rule("LOSS_OFFSET")
        rank = {c: i for i, c in enumerate(OFFSET_ORDER)}
        positives.sort(key=lambda l: (rank.get(l.category, 99), l.date))
        for l in self.lines:
            l.offset_amount = 0.0
        for loss in sorted(losses, key=lambda l: l.date):
            row = LossOffsetRow(loss.line_id, ctx.year, loss.category, loss.depot, loss.isin, loss.name,
                                original_loss=loss.amount, status=PROVISIONAL if rule.provisional else CALC)
            if "LOSS_OFFSET" not in loss.rule_ids:
                loss.rule_ids.append("LOSS_OFFSET")
            if not rule.computable:
                row.reasons.append("Verlustausgleich für dieses Jahr nicht verifiziert – manuell prüfen")
                row.remaining = loss.amount
                row.status = MANUAL
                self.rows.append(row)
                continue
            remaining = -loss.amount
            broker_offset = ctx.depot_settings.get(loss.depot_id, {}).get("loss_offset_by_broker") == "ja"
            phases = []
            if broker_offset:
                phases.append(([p for p in positives if p.depot_id == loss.depot_id], "depotintern (Broker)"))
                row.reasons.append("Broker führt Verlustausgleich durch – zuerst depotinterne Verrechnung "
                                   "(Werte laut Steuerbescheinigung des Brokers maßgeblich)")
            phases.append((positives, "depotübergreifend (Veranlagung)"))
            for pool, label in phases:
                for p in pool:
                    if remaining <= EPS:
                        break
                    avail = p.amount - p.offset_amount
                    if avail <= EPS:
                        continue
                    use = min(avail, remaining)
                    p.offset_amount += use
                    remaining -= use
                    row.offsets.append((p.line_id, f"{p.category} ({label})", round(use, 2)))
            row.offset_total = round(-loss.amount - remaining, 2)
            row.remaining = round(-remaining, 2)
            row.reasons.append("Verrechnung nur mit positiven Einkünften mit Sondersteuersatz 27,5 % desselben Jahres "
                               "(§ 27 Abs 8 EStG)")
            row.reasons.append("Kein Ausgleich mit 25-%-Zinsen aus Geldeinlagen und Stiftungszuwendungen "
                               "(§ 27 Abs 8 Z 1 EStG)")
            row.reasons.append("Reihenfolge: zuerst Einkünfte ohne ausländische Quellensteuer (Annahme – nicht "
                               "verifiziert, maßgeblich ist die Veranlagung)")
            if remaining > EPS:
                row.reasons.append(f"Nicht verrechenbarer Rest {remaining:.2f} EUR – kein Verlustvortrag "
                                   "(verfällt)")
            self.rows.append(row)
        bank = [l for l in computable if l.bucket == BUCKET_25]
        if losses and bank:
            ctx.issue("Hinweis", "Offene steuerliche Frage",
                      f"{len(bank)} Zinsposition(en) mit 25 % nicht in den Verlustausgleich einbezogen "
                      "(§ 27 Abs 8 Z 1 EStG)")


# --------------------------------------------------------------------------- #
def summarize(lines: list[CalcLine], rules: TaxRules, only_confirmed: bool = False) -> dict:
    sel = [l for l in lines if l.amount is not None and l.status != MANUAL and (not only_confirmed or l.status == CALC)]
    r27, r25 = rules.rate("RATE_27_5"), rules.rate("RATE_25")

    def total(cats, positive=None):
        out = 0.0
        for l in sel:
            if l.category in cats and (positive is None or (l.amount > 0) == positive):
                out += l.amount
        return round(out, 2)

    pos27 = round(sum(l.amount for l in sel if l.bucket == BUCKET_27_5 and l.amount > 0), 2)
    neg27 = round(sum(l.amount for l in sel if l.bucket == BUCKET_27_5 and l.amount < 0), 2)
    if only_confirmed:
        # Verlustausgleich nur innerhalb gesicherter Positionen
        avail = -neg27
        base27 = round(max(0.0, pos27 - avail), 2)
        offset_used = round(min(pos27, avail), 2)
    else:
        offset_used = round(sum(l.offset_amount for l in sel if l.bucket == BUCKET_27_5 and l.amount > 0), 2)
        base27 = round(pos27 - offset_used, 2)
    base25 = round(sum(l.amount for l in sel if l.bucket == BUCKET_25), 2)
    # Anrechenbare Quellensteuer nach Verlustausgleich: höchstens 27,5 % des verbleibenden Ertrags
    credit = 0.0
    credit_max = 0.0
    for l in sel:
        if l.creditable_tax_max:
            credit_max += l.creditable_tax_max
            remaining = (l.amount - (l.offset_amount if not only_confirmed else 0.0)) if l.amount > 0 else 0.0
            credit += min(l.creditable_tax_max, remaining * (r27 if l.bucket == BUCKET_27_5 else r25))
    tax27 = round(base27 * r27, 2)
    tax25 = round(base25 * r25, 2)
    kest = round(sum(l.kest_at for l in sel), 2)
    all_lines_wht = [l for l in lines]
    return {
        "Dividenden": total([CAT_DIVIDEND]),
        "Zinsen 27,5 %": total([CAT_INTEREST_27]),
        "Zinsen Geldeinlagen 25 %": total([CAT_INTEREST_25]),
        "Fondsausschüttungen (steuerpflichtig)": total([CAT_FUND_DIST]),
        "Ausschüttungsgleiche Erträge": total([CAT_AGE, CAT_AGE_MANUAL]),
        "Nichtmeldefonds pauschal": total([CAT_NMF]),
        "REIT/BDC sonstige Ausschüttungen": total([CAT_REIT_OTHER]),
        "Realisierte Gewinne": total([CAT_GAIN], True),
        "Realisierte Verluste": total([CAT_LOSS], False),
        "Summe positive Einkünfte 27,5 %": pos27,
        "Verrechnete Verluste": -offset_used,
        "Nicht verrechenbare Verluste (verfallen)": round(neg27 + offset_used, 2),
        "Bemessungsgrundlage 27,5 %": base27,
        "Steuer 27,5 %": tax27,
        "Bemessungsgrundlage 25 %": base25,
        "Steuer 25 %": tax25,
        "Ausländische Quellensteuer einbehalten": round(sum(l.withholding_tax for l in all_lines_wht), 2),
        "Anrechenbare Quellensteuer (Höchstbetrag vor Verlustausgleich)": round(credit_max, 2),
        "Anrechenbare Quellensteuer (nach Verlustausgleich, Schätzung)": round(credit, 2),
        "Nicht anrechenbare Quellensteuer": round(sum(l.non_creditable_tax for l in all_lines_wht), 2),
        "Ungeklärte Quellensteuer": round(sum(l.unclear_tax for l in all_lines_wht), 2),
        "Bereits einbehaltene österr. KESt": kest,
        "Geschätzte Steuer nach Anrechnung": round(tax27 + tax25 - credit - kest, 2),
        "Ungeklärte Beträge (nicht berechnet)": round(sum((l.gross or 0) for l in lines if l.status == MANUAL), 2),
        "Positionen gesamt": len(lines),
        "Positionen vorläufig": sum(1 for l in lines if l.status == PROVISIONAL),
        "Positionen manuell zu prüfen": sum(1 for l in lines if l.status == MANUAL),
    }


def e1kv_rows(result_lines: list[CalcLine], rules: TaxRules, year: int) -> list[dict]:
    spec = rules.e1kv(year)
    fields = spec.get("fields") or {}
    ref_year = spec.get("unverified_reference_year")
    ref_fields = (rules.e1kv(ref_year).get("fields") or {}) if ref_year else {}
    keys = list(fields or ref_fields)
    agg: dict[str, dict] = {k: {"amount": 0.0, "lines": [], "status": CALC} for k in keys}
    order = {CALC: 0, PROVISIONAL: 1, MANUAL: 2}
    for l in result_lines:
        if l.status == MANUAL or l.amount is None:
            continue
        targets = []
        if l.e1kv_key:
            targets.append((l.e1kv_key, l.amount))
        if l.kest_at:
            targets.append(("kest_inland" if l.domestic else None, l.kest_at))
        if l.creditable_tax_max and l.bucket == BUCKET_27_5:
            targets.append(("foreign_tax_27_5", l.creditable_tax_max))
        for key, val in targets:
            if not key or key not in agg:
                continue
            a = agg[key]
            a["amount"] += val
            a["lines"].append(l.line_id)
            if order[l.status] > order[a["status"]]:
                a["status"] = l.status
    rows = []
    for key in keys:
        f = fields.get(key) or ref_fields.get(key) or {}
        a = agg[key]
        verified_kz = key in fields
        kz_status = f.get("status", "nicht_verifiziert") if verified_kz else "nicht_verifiziert"
        hints = []
        if not verified_kz:
            hints.append(f"Kennzahl für {year} nicht verifiziert – Wert aus Formular {ref_year} nur als Hinweis")
        if kz_status == "sekundaer":
            hints.append("Kennzahl nur über Sekundärquelle belegt – im Formular prüfen")
        if key.endswith("_inland"):
            hints.append("Inländische (KESt-abzugspflichtige) Einkünfte sind grundsätzlich endbesteuert – nur bei "
                         "Verlustausgleichs-/Regelbesteuerungsoption angeben")
        if key == "foreign_tax_27_5":
            hints.append("Höchstbetrag vor Verlustausgleich; das Finanzamt begrenzt die Anrechnung im Bescheid")
        if key.startswith("losses_"):
            hints.append("Verluste mit negativem Vorzeichen eintragen")
        amount = round(a["amount"], 2)
        rows.append({
            "Kennzahl": f.get("kz", "?") if verified_kz else f"({f.get('kz', '?')}?)",
            "Bezeichnung": f.get("label", key),
            "Betrag EUR": amount,
            "Kennzahl-Status": {"offiziell_auszug": "offiziell belegt (Auszug)", "sekundaer": "Sekundärquelle",
                                "nicht_verifiziert": "nicht verifiziert"}.get(kz_status, kz_status),
            "Betrags-Status": STATUS_TEXT[a["status"]] if a["lines"] else "kein Betrag",
            "Positionen": ", ".join(a["lines"]),
            "Hinweise": "; ".join(hints),
        })
    return rows


def positions_snapshot(ctx: Context, tracker: CostBasisTracker) -> list[dict]:
    """Bestände zum 31.12. mit steuerlichen AK und – falls Kurse vorliegen – Bewertung (nur Information)."""
    from ..fx import FxService

    try:
        fx_rates = FxService(ctx.repo.store.base).rates(allow_download=False)
    except Exception:  # noqa: BLE001 – Bewertung ist optional
        fx_rates = None
    end = date(ctx.year, 12, 31)
    rows = []
    for (dep, isin), h in sorted(tracker.holdings.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        if h.qty <= EPS:
            continue
        sec = ctx.securities.get(isin, {}) or {}
        price = ctx.repo.db.one(
            "SELECT * FROM security_prices WHERE isin=? AND price_date<=? AND price_date>=? "
            "ORDER BY price_date DESC LIMIT 1", (isin, end.isoformat(), date(ctx.year, 12, 21).isoformat()))
        value_eur = None
        if price:
            rate = 1.0
            if price["currency"] != "EUR":
                hit = fx_rates.lookup(price["currency"], end) if fx_rates else None
                rate = hit[0] if hit else None
            value_eur = round(h.qty * price["close"] / rate, 2) if rate else None
        cost = round(h.cost, 2) if h.cost_known else None
        rows.append({"Depot": ctx.depots[dep]["name"], "Broker": ctx.depots[dep]["broker_name"], "ISIN": isin,
                     "Name": sec.get("name"), "Bestand 31.12.": round(h.qty, 6),
                     "Steuerliche AK gesamt EUR": cost,
                     "AK je Stück EUR": round(h.cost / h.qty, 6) if h.cost_known and h.qty else None,
                     "AK vollständig": "ja" if h.cost_known and not h.history_gap else "nein",
                     "Kurs 31.12.": price["close"] if price else None,
                     "Kurswährung": price["currency"] if price else None,
                     "Kursdatum": price["price_date"] if price else None,
                     "Kursquelle": price["source"] if price else "kein Kurs",
                     "Wert 31.12. EUR": value_eur,
                     "Unrealisiert EUR (Info)": round(value_eur - cost, 2) if value_eur is not None and cost is not None
                     else None})
    return rows


def compute(repo: Repository, year: int, rules: TaxRules | None = None) -> TaxResult:
    rules = rules or load_rules()
    rules.check_year(year)
    ctx = Context(repo, rules, year)

    # Grunddaten prüfen
    for dep_id, s in ctx.depot_settings.items():
        if s.get("_default") and any(t["depot_id"] == dep_id and t["trade_date"][:4] == str(year) for t in ctx.tx_all):
            ctx.issue("Warnung", "Fehlende Daten",
                      f"Depot „{ctx.depots[dep_id]['name']}“: für {year} nicht angegeben, ob der Broker österreichische "
                      "KESt abführt/Verlustausgleich durchführt – als ausländisches Depot ohne KESt-Abzug behandelt",
                      f"Depot #{dep_id}")
    for tx in ctx.tx_all:
        if tx["trade_date"][:4] == str(year) and tx.get("currency") != "EUR" and not tx.get("fx_rate"):
            ctx.issue("Fehler", "Fehlende Daten", f"Buchung in {tx['currency']} ohne Devisenkurs – „Devisenkurse von der "
                                                  "EZB ergänzen“ (Dashboard/Transaktionen) oder Kurs eintragen",
                      ctx.tx_source(tx))
    for c in repo.conflicts("offen"):
        ctx.issue("Warnung", "Widerspruch", f"Offener Datenkonflikt {c['entity']} {c['entity_key']} Feld "
                                            f"„{c['field']}“: {c['existing_value']} ↔ {c['new_value']}",
                  f"Konflikt #{c['id']}")
    for r in repo.fund_reports():
        if r["active"] == 0 and r["superseded_by"] is None and r["report_date"][:4] == str(year):
            ctx.issue("Warnung", "Widerspruch", f"Fondsmeldung #{r['id']} ({r['isin']}) wartet auf Entscheidung "
                                                "(Abweichung zu bestehender Meldung)", f"Fondsmeldung #{r['id']}")

    tracker = CostBasisTracker(ctx)
    tracker.run()
    income = IncomeClassifier(ctx, tracker)
    income.run()
    funds = FundProcessor(ctx, tracker)
    funds.run()
    lines = sorted(tracker.lines + income.lines + funds.lines, key=lambda l: (l.date, l.line_id))
    lo = LossOffset(ctx, lines)
    lo.run()

    used = sorted({rid for l in lines for rid in l.rule_ids} | {"LOSS_OFFSET", "LOSS_OFFSET_ORDER", "RATE_27_5"})
    rules_used = []
    for rid in used:
        r = rules.rule(rid, year)
        rules_used.append({"Regel-ID": rid, "Titel": r.title, "Rechtsgrundlage": r.legal_basis,
                           "Status": r.status_label, "Quellen": rules.source_text(r.sources), "Logik": r.logic,
                           "Einschränkungen": r.limitations, "Letzte Prüfung": rules.last_review,
                           "Satz": rules.param(rid, "rate")})
        if r.status != "offiziell_auszug":
            ctx.issue("Hinweis", "Offene steuerliche Frage", f"Regel {rid} ({r.title}) für {year}: {r.status_label}",
                      rid)
    return TaxResult(
        tax_year=year, lines=lines, issues=ctx.issues, loss_offsets=lo.rows,
        summary=summarize(lines, rules), summary_confirmed=summarize(lines, rules, only_confirmed=True),
        e1kv=e1kv_rows(lines, rules, year), nmf_rows=funds.nmf_rows, fund_rows=funds.fund_rows,
        positions=positions_snapshot(ctx, tracker), rules_used=rules_used, fees=income.fees,
    )
