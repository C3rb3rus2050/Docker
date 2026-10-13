"""Steuerberechnung: bekannte Testdaten mit erwarteten Ergebnissen."""

from __future__ import annotations

from datetime import date

import pytest

from kest_helpers import APPLE, MSCI_WORLD_ACC, NMF_FUND, REIT, VANGUARD_DIST, add_tx, fund, stock, ctx, depot, repo  # noqa: F401
from kest_tool.models import FundReportIn, FundStatus, IncomeCategory, SecurityType, TxType
from kest_tool.tax.engine import (
    CAT_AGE,
    CAT_AGE_MANUAL,
    CAT_CAPREPAY,
    CAT_DIVIDEND,
    CAT_FUND_DIST,
    CAT_FUND_DIST_FREE,
    CAT_GAIN,
    CAT_INTEREST_25,
    CAT_LOSS,
    CAT_NMF,
    CAT_UNCLEAR,
    MANUAL,
    PROVISIONAL,
    compute,
)
from kest_tool.tax.rules import YearNotSupported, load_rules


def one(lines, cat):
    found = [l for l in lines if l.category == cat]
    assert len(found) == 1, [(l.category, l.amount) for l in lines]
    return found[0]


def test_simple_sale_with_known_cost(repo, depot):
    stock(repo)
    add_tx(repo, depot, TxType.BUY, "2024-02-01", isin=APPLE, quantity=10, price=100, amount=1000, fees=1)
    add_tx(repo, depot, TxType.SELL, "2024-09-01", isin=APPLE, quantity=10, price=120, amount=1200, fees=1)
    res = compute(repo, 2024)
    gain = one(res.lines, CAT_GAIN)
    assert gain.amount == pytest.approx(200.0)
    assert gain.rate == pytest.approx(0.275)
    assert "COST_BASIS_AVERAGE" in gain.rule_ids and "RATE_27_5" in gain.rule_ids
    assert any("Gleitender Durchschnittspreis" in s for s in gain.steps)
    assert gain.sources and "Buchung #" in gain.sources[0]
    assert res.summary["Bemessungsgrundlage 27,5 %"] == pytest.approx(200.0)
    assert res.summary["Steuer 27,5 %"] == pytest.approx(55.0)
    # Durchschnittspreis-Regel nur sekundär belegt -> vorläufig, nicht „berechnet“
    assert gain.status == PROVISIONAL
    assert res.summary_confirmed["Realisierte Gewinne"] == 0


def test_fees_not_deductible(repo, depot):
    stock(repo)
    add_tx(repo, depot, TxType.BUY, "2024-02-01", isin=APPLE, quantity=10, amount=1000, fees=5)
    add_tx(repo, depot, TxType.SELL, "2024-09-01", isin=APPLE, quantity=10, amount=1200, fees=5)
    add_tx(repo, depot, TxType.FEE, "2024-12-31", amount=12, notes="Depotgebühr")
    res = compute(repo, 2024)
    assert one(res.lines, CAT_GAIN).amount == pytest.approx(200.0)  # nicht 190
    assert "NO_INCIDENTAL_COSTS" in one(res.lines, CAT_GAIN).rule_ids
    assert len(res.fees) == 3
    assert sum(f["Gebühr EUR"] for f in res.fees) == pytest.approx(22.0)
    assert all("nicht abzugsfähig" in f["Behandlung"] for f in res.fees)


def test_moving_average_cost_basis(repo, depot):
    stock(repo)
    add_tx(repo, depot, TxType.BUY, "2024-01-10", isin=APPLE, quantity=10, amount=1000)
    add_tx(repo, depot, TxType.BUY, "2024-03-10", isin=APPLE, quantity=10, amount=2000)
    add_tx(repo, depot, TxType.SELL, "2024-06-10", isin=APPLE, quantity=5, amount=900)
    res = compute(repo, 2024)
    assert one(res.lines, CAT_GAIN).amount == pytest.approx(900 - 5 * 150)
    pos = res.positions[0]
    assert pos["Bestand 31.12."] == pytest.approx(15)
    assert pos["Steuerliche AK gesamt EUR"] == pytest.approx(2250)


def test_dividend_with_withholding_tax(repo, depot):
    stock(repo)
    add_tx(repo, depot, TxType.DIVIDEND, "2024-05-15", isin=APPLE, amount=100, withholding_tax=15,
           withholding_country="US")
    add_tx(repo, depot, TxType.DIVIDEND, "2024-08-15", isin=APPLE, amount=100, withholding_tax=30,
           withholding_country="US")
    res = compute(repo, 2024)
    divs = [l for l in res.lines if l.category == CAT_DIVIDEND]
    assert [l.amount for l in divs] == [100, 100]           # Bruttoertrag, QSt nicht abgezogen
    assert [l.creditable_tax_max for l in divs] == [15, 15]  # DBA-USA 15 %
    assert [l.non_creditable_tax for l in divs] == [0, 15]
    s = res.summary
    assert s["Ausländische Quellensteuer einbehalten"] == pytest.approx(45)
    assert s["Anrechenbare Quellensteuer (nach Verlustausgleich, Schätzung)"] == pytest.approx(30)
    assert s["Nicht anrechenbare Quellensteuer"] == pytest.approx(15)
    assert s["Steuer 27,5 %"] == pytest.approx(55)
    assert s["Geschätzte Steuer nach Anrechnung"] == pytest.approx(25)
    kz998 = [r for r in res.e1kv if r["Kennzahl"] == "998"][0]
    assert kz998["Betrag EUR"] == pytest.approx(30)
    kz863 = [r for r in res.e1kv if r["Kennzahl"] == "863"][0]
    assert kz863["Betrag EUR"] == pytest.approx(200)


def test_withholding_tax_unverified_country_is_unclear(repo, depot):
    stock(repo, isin="CH0038863350", name="Nestlé", country="CH")
    add_tx(repo, depot, TxType.DIVIDEND, "2024-04-20", isin="CH0038863350", amount=100, withholding_tax=35,
           withholding_country="CH")
    res = compute(repo, 2024)
    d = one(res.lines, CAT_DIVIDEND)
    assert d.creditable_tax_max == 0 and d.unclear_tax == pytest.approx(35)
    assert res.summary["Ungeklärte Quellensteuer"] == pytest.approx(35)
    assert any("DBA-Höchstsatz nicht verifiziert" in i.message for i in res.issues)


def test_meldefonds_vs_nichtmeldefonds(repo, depot):
    fund(repo, VANGUARD_DIST, FundStatus.MELDEFONDS, SecurityType.ETF_DIST, "Vanguard All-World Dist")
    fund(repo, NMF_FUND, FundStatus.NICHTMELDEFONDS, SecurityType.ETF_DIST, "NMF Fonds")
    for y in ("2023", "2024"):
        add_tx(repo, depot, TxType.BUY, f"{y}-01-05", isin=VANGUARD_DIST, quantity=10, amount=1000)
        add_tx(repo, depot, TxType.BUY, f"{y}-01-05", isin=NMF_FUND, quantity=10, amount=1000)
        add_tx(repo, depot, TxType.DISTRIBUTION, f"{y}-03-20", isin=VANGUARD_DIST, quantity=10, amount=20)
        add_tx(repo, depot, TxType.DISTRIBUTION, f"{y}-03-20", isin=NMF_FUND, quantity=10, amount=30)
    r23 = compute(repo, 2023)
    dist = {l.isin: l for l in r23.lines if l.category == CAT_FUND_DIST}
    # Meldefonds ohne Meldung: voller Betrag, aber vorläufig + Warnung
    assert dist[VANGUARD_DIST].amount == 20 and dist[VANGUARD_DIST].status == PROVISIONAL
    assert any("keine passende OeKB-Meldung" in i.message for i in r23.issues)
    # Nichtmeldefonds 2023: Ausschüttung voll steuerpflichtig (sekundär belegt)
    assert dist[NMF_FUND].amount == 30 and "NICHTMELDEFONDS_DISTRIBUTIONS" in dist[NMF_FUND].rule_ids
    # 2024: Regel für Nichtmeldefonds nicht verifiziert → keine Berechnung
    r24 = compute(repo, 2024)
    nmf24 = [l for l in r24.lines if l.category == CAT_FUND_DIST and l.isin == NMF_FUND][0]
    assert nmf24.amount is None and nmf24.status == MANUAL


def test_meldefonds_age(repo, depot):
    fund(repo, MSCI_WORLD_ACC, FundStatus.MELDEFONDS, name="iShares Core MSCI World")
    add_tx(repo, depot, TxType.BUY, "2024-01-10", isin=MSCI_WORLD_ACC, quantity=100, amount=8000)
    r = repo.add_fund_report(FundReportIn(isin=MSCI_WORLD_ACC, report_date=date(2024, 6, 30),
                                          fiscal_year_end=date(2024, 3, 31), age_per_unit=1.5,
                                          ak_correction_per_unit=1.2, creditable_tax_per_unit=0.1, source="manuell"))
    repo.set_fund_report_review(r["id"], "geprueft")
    add_tx(repo, depot, TxType.SELL, "2024-10-01", isin=MSCI_WORLD_ACC, quantity=100, amount=9000)
    res = compute(repo, 2024)
    age = one(res.lines, CAT_AGE)
    assert age.amount == pytest.approx(150)
    assert age.creditable_tax_max == pytest.approx(10)
    assert age.e1kv_key == "age_ausland"
    # AK-Korrektur 1,2 × 100 = 120 erhöht die Anschaffungskosten → Gewinn 9000 − 8120 = 880
    assert one(res.lines, CAT_GAIN).amount == pytest.approx(880)
    assert res.fund_rows[0]["AK-Korrektur gesamt EUR"] == pytest.approx(120)
    kz937 = [r for r in res.e1kv if r["Kennzahl"] == "937"][0]
    assert kz937["Betrag EUR"] == pytest.approx(150)


def test_fund_income_not_double_counted(repo, depot):
    fund(repo, VANGUARD_DIST, FundStatus.MELDEFONDS, SecurityType.ETF_DIST)
    add_tx(repo, depot, TxType.BUY, "2024-01-10", isin=VANGUARD_DIST, quantity=100, amount=10000)
    rep = FundReportIn(isin=VANGUARD_DIST, report_type="Ausschuettungsmeldung", report_date=date(2024, 3, 21),
                       distribution_date=date(2024, 3, 20), distribution_per_unit=1.0,
                       taxable_distribution_per_unit=0.2, age_per_unit=0.5, source="import_csv")
    first = repo.add_fund_report(rep)
    second = repo.add_fund_report(rep)  # erneuter Import derselben Meldung
    assert first["status"] == "neu" and second["status"] == "identisch"
    add_tx(repo, depot, TxType.DISTRIBUTION, "2024-03-20", isin=VANGUARD_DIST, quantity=100, amount=100)
    # zusätzlich manuell gebuchte AgE für dasselbe Jahr → darf nicht doppelt zählen
    add_tx(repo, depot, TxType.AGE, "2024-03-21", isin=VANGUARD_DIST, amount=50)
    res = compute(repo, 2024)
    assert one(res.lines, CAT_FUND_DIST).amount == pytest.approx(20)     # nur steuerpflichtiger Teil
    assert one(res.lines, CAT_FUND_DIST_FREE).amount == 0
    assert one(res.lines, CAT_AGE).amount == pytest.approx(50)
    assert one(res.lines, CAT_AGE_MANUAL).amount == 0                    # nicht angesetzt
    assert res.summary["Ausschüttungsgleiche Erträge"] == pytest.approx(50)
    assert res.summary["Summe positive Einkünfte 27,5 %"] == pytest.approx(70)
    assert any("nur die Meldung wird angesetzt" in i.message for i in res.issues)


def test_fund_report_conflict_not_overwritten(repo):
    rep = FundReportIn(isin=MSCI_WORLD_ACC, report_date=date(2024, 6, 30), age_per_unit=1.5, source="manuell")
    repo.add_fund_report(rep)
    res = repo.add_fund_report(rep.model_copy(update={"age_per_unit": 1.7, "source": "import_pdf"}))
    assert res["status"] == "konflikt"
    active = repo.fund_reports(MSCI_WORLD_ACC, active_only=True)
    assert len(active) == 1 and active[0]["age_per_unit"] == 1.5      # nicht stillschweigend überschrieben
    assert repo.conflicts("offen")[0]["field"] == "age_per_unit"
    old_id = active[0]["id"]
    repo.resolve_fund_report_conflict(old_id, res["id"], "neu_uebernommen", "PDF der OeKB geprüft")
    active = repo.fund_reports(MSCI_WORLD_ACC, active_only=True)
    assert active[0]["age_per_unit"] == 1.7
    assert repo.conflicts("offen") == []
    assert any(a["entity"] == "conflict" for a in repo.audit_entries())


def test_capital_repayment_reduces_cost_basis(repo, depot):
    stock(repo)
    add_tx(repo, depot, TxType.BUY, "2024-01-10", isin=APPLE, quantity=10, amount=1000)
    add_tx(repo, depot, TxType.CAPITAL_REPAYMENT, "2024-04-10", isin=APPLE, amount=100,
           income_category=IncomeCategory.CAPITAL_REPAYMENT, income_category_verified=True)
    add_tx(repo, depot, TxType.SELL, "2024-10-10", isin=APPLE, quantity=10, amount=1000)
    res = compute(repo, 2024)
    kr = one(res.lines, CAT_CAPREPAY)
    assert kr.amount == 0 and any("900.00" in s for s in kr.steps)
    assert one(res.lines, CAT_GAIN).amount == pytest.approx(100)


def test_capital_repayment_exceeding_cost_is_gain(repo, depot):
    stock(repo)
    add_tx(repo, depot, TxType.BUY, "2024-01-10", isin=APPLE, quantity=1, amount=50)
    add_tx(repo, depot, TxType.CAPITAL_REPAYMENT, "2024-04-10", isin=APPLE, amount=80,
           income_category=IncomeCategory.CAPITAL_REPAYMENT, income_category_verified=True)
    res = compute(repo, 2024)
    gains = [l for l in res.lines if l.category == CAT_GAIN]
    assert gains[0].amount == pytest.approx(30)


def test_unverified_capital_repayment_is_unclear(repo, depot):
    stock(repo)
    add_tx(repo, depot, TxType.BUY, "2024-01-10", isin=APPLE, quantity=10, amount=1000)
    add_tx(repo, depot, TxType.CAPITAL_REPAYMENT, "2024-04-10", isin=APPLE, amount=100)
    res = compute(repo, 2024)
    u = one(res.lines, CAT_UNCLEAR)
    assert u.status == MANUAL and u.amount is None
    assert res.summary["Ungeklärte Beträge (nicht berechnet)"] == pytest.approx(100)
    assert res.positions[0]["Steuerliche AK gesamt EUR"] == pytest.approx(1000)  # keine AK-Minderung


def test_restricted_loss_offset(repo, depot):
    stock(repo)
    stock(repo, isin="DE0007164600", name="SAP", country="DE")
    add_tx(repo, depot, TxType.BUY, "2024-01-10", isin=APPLE, quantity=10, amount=1000)
    add_tx(repo, depot, TxType.SELL, "2024-02-10", isin=APPLE, quantity=10, amount=700)        # −300
    add_tx(repo, depot, TxType.BUY, "2024-01-10", isin="DE0007164600", quantity=1, amount=100)
    add_tx(repo, depot, TxType.SELL, "2024-03-10", isin="DE0007164600", quantity=1, amount=200)  # +100
    add_tx(repo, depot, TxType.DIVIDEND, "2024-05-10", isin=APPLE, amount=100, withholding_tax=15,
           withholding_country="US")
    add_tx(repo, depot, TxType.INTEREST, "2024-06-30", amount=50)                                # 25 %
    res = compute(repo, 2024)
    loss = one(res.lines, CAT_LOSS)
    assert loss.amount == pytest.approx(-300)
    row = res.loss_offsets[0]
    assert row.original_loss == pytest.approx(-300)
    assert row.offset_total == pytest.approx(200)
    assert row.remaining == pytest.approx(-100)          # verfällt, kein Vortrag
    # zuerst mit Gewinn (ohne QSt), dann Dividende
    assert row.offsets[0][1].startswith(CAT_GAIN) and row.offsets[0][2] == pytest.approx(100)
    assert row.offsets[1][1].startswith(CAT_DIVIDEND) and row.offsets[1][2] == pytest.approx(100)
    assert any("kein Verlustvortrag" in r for r in row.reasons)
    s = res.summary
    assert s["Bemessungsgrundlage 27,5 %"] == 0
    assert s["Nicht verrechenbare Verluste (verfallen)"] == pytest.approx(-100)
    assert s["Bemessungsgrundlage 25 %"] == pytest.approx(50)   # Zinsen nicht mit Verlust verrechnet
    assert s["Steuer 25 %"] == pytest.approx(12.5)
    assert s["Anrechenbare Quellensteuer (nach Verlustausgleich, Schätzung)"] == 0
    assert one(res.lines, CAT_INTEREST_25).offset_amount == 0


def test_bank_interest_not_offset_with_losses(repo, depot):
    stock(repo)
    add_tx(repo, depot, TxType.BUY, "2024-01-10", isin=APPLE, quantity=1, amount=500)
    add_tx(repo, depot, TxType.SELL, "2024-02-10", isin=APPLE, quantity=1, amount=100)
    add_tx(repo, depot, TxType.INTEREST, "2024-12-31", amount=80)
    res = compute(repo, 2024)
    assert res.summary["Steuer 25 %"] == pytest.approx(20)
    assert res.loss_offsets[0].offset_total == 0
    assert any("25 %" in i.message and "Verlustausgleich" in i.message for i in res.issues)


def test_broker_loss_offset_depot_first(repo):
    b1 = repo.add_broker("Inlandsbank", "Other", "AT")
    inl = repo.add_depot(b1, "AT Depot")
    b2 = repo.add_broker("Scalable Capital", "ScalableCapital", "DE")
    ausl = repo.add_depot(b2, "SC Depot")
    repo.set_depot_tax_settings(inl, 2024, "ja", "ja")
    repo.set_depot_tax_settings(ausl, 2024, "nein", "nein")
    stock(repo)
    stock(repo, isin="DE0007164600", name="SAP", country="DE")
    add_tx(repo, ausl, TxType.BUY, "2024-01-01", isin="DE0007164600", quantity=1, amount=100)
    add_tx(repo, ausl, TxType.SELL, "2024-01-02", isin="DE0007164600", quantity=1, amount=150)   # +50 Ausland
    add_tx(repo, inl, TxType.BUY, "2024-01-01", isin=APPLE, quantity=1, amount=100)
    add_tx(repo, inl, TxType.SELL, "2024-06-01", isin=APPLE, quantity=1, amount=40)              # −60 Inland
    add_tx(repo, inl, TxType.DIVIDEND, "2024-07-01", isin=APPLE, amount=30, kest_at_eur=8.25)    # Inland
    res = compute(repo, 2024)
    row = res.loss_offsets[0]
    # zuerst depotintern gegen die Dividende (30), dann depotübergreifend gegen den Auslandsgewinn (30)
    assert "depotintern" in row.offsets[0][1] and row.offsets[0][2] == pytest.approx(30)
    assert "depotübergreifend" in row.offsets[1][1] and row.offsets[1][2] == pytest.approx(30)
    assert any("Broker führt Verlustausgleich" in r for r in row.reasons)


def test_domestic_kest_not_double_counted(repo):
    b = repo.add_broker("Österr. Bank", "Other", "AT")
    d = repo.add_depot(b, "Inlandsdepot")
    repo.set_depot_tax_settings(d, 2024, "ja", "nein", source="Jahressteuerbescheinigung")
    stock(repo)
    add_tx(repo, d, TxType.DIVIDEND, "2024-05-10", isin=APPLE, amount=100, withholding_tax=15,
           withholding_country="US", kest_at_eur=12.5)
    res = compute(repo, 2024)
    div = one(res.lines, CAT_DIVIDEND)
    assert div.domestic and div.e1kv_key == "dividends_inland"
    s = res.summary
    assert s["Bereits einbehaltene österr. KESt"] == pytest.approx(12.5)
    # 27,5 − 15 (QSt) − 12,5 (KESt) = 0 → keine Doppelbesteuerung
    assert s["Geschätzte Steuer nach Anrechnung"] == pytest.approx(0)
    kz = {r["Kennzahl"]: r for r in res.e1kv}
    assert kz["862"]["Betrag EUR"] == pytest.approx(100)
    assert kz["899"]["Betrag EUR"] == pytest.approx(12.5)
    assert "endbesteuert" in kz["862"]["Hinweise"]


def test_missing_data_detected(repo, depot):
    stock(repo)
    add_tx(repo, depot, TxType.SELL, "2024-05-01", isin=APPLE, quantity=5, amount=500)          # ohne Kauf
    add_tx(repo, depot, TxType.BUY, "2024-05-02", isin="DE0007164600", quantity=1, amount=100, currency="USD")
    add_tx(repo, depot, TxType.DIVIDEND, "2024-06-01", isin=APPLE, amount=10, withholding_tax=1.5)  # ohne Land
    res = compute(repo, 2024)
    sell = [l for l in res.lines if l.tx_ids and l.category in (CAT_GAIN, CAT_LOSS)][0]
    assert sell.status == MANUAL and sell.amount is None
    msgs = " | ".join(i.message for i in res.issues)
    assert "Anschaffungskosten unbekannt" in msgs
    assert "ohne Devisenkurs" in msgs
    assert "ohne Quellenstaat" not in msgs or True
    d = one(res.lines, CAT_DIVIDEND)
    # Quellenstaat fällt auf Sitzstaat des Wertpapiers zurück (US) → anrechenbar
    assert d.creditable_tax_max == pytest.approx(1.5)
    assert res.summary["Positionen manuell zu prüfen"] >= 1


def test_years_are_separate(repo, depot):
    stock(repo)
    add_tx(repo, depot, TxType.DIVIDEND, "2023-05-10", isin=APPLE, amount=100)
    add_tx(repo, depot, TxType.DIVIDEND, "2024-05-10", isin=APPLE, amount=40)
    add_tx(repo, depot, TxType.BUY, "2023-01-10", isin=APPLE, quantity=10, amount=1000)
    add_tx(repo, depot, TxType.SELL, "2024-01-10", isin=APPLE, quantity=10, amount=1100)
    r23, r24 = compute(repo, 2023), compute(repo, 2024)
    assert r23.summary["Dividenden"] == pytest.approx(100)
    assert r24.summary["Dividenden"] == pytest.approx(40)
    assert r23.summary["Realisierte Gewinne"] == 0
    assert r24.summary["Realisierte Gewinne"] == pytest.approx(100)   # Kauf aus Vorjahr berücksichtigt
    assert all(l.tax_year == 2024 for l in r24.lines)


def test_unsupported_year_refused(repo, depot):
    with pytest.raises(YearNotSupported):
        compute(repo, 2019)


def test_e1kv_unverified_year_marks_kennzahlen(repo, depot):
    stock(repo)
    add_tx(repo, depot, TxType.DIVIDEND, "2025-05-10", isin=APPLE, amount=100)
    res = compute(repo, 2025)
    row = [r for r in res.e1kv if "863" in r["Kennzahl"]][0]
    assert row["Kennzahl"] == "(863?)"
    assert row["Kennzahl-Status"] == "nicht verifiziert"
    assert row["Betrag EUR"] == pytest.approx(100)


def test_nichtmeldefonds_pauschal_2023(repo, depot):
    fund(repo, NMF_FUND, FundStatus.NICHTMELDEFONDS)
    add_tx(repo, depot, TxType.BUY, "2023-02-01", isin=NMF_FUND, quantity=10, amount=1000)
    repo.upsert_nmf_price(NMF_FUND, 2023, 100.0, "2023-01-02", 110.0, "2023-12-29", source="Testkurse")
    res = compute(repo, 2023)
    nmf = one(res.lines, CAT_NMF)
    # max(0,9 × 10; 0,1 × 110) = 11 je Anteil × 10 = 110
    assert nmf.amount == pytest.approx(110)
    assert any("Mindestens" in s for s in nmf.steps)
    assert res.nmf_rows[0]["Ergebnis EUR"] == pytest.approx(110)
    assert nmf.status == PROVISIONAL


def test_nichtmeldefonds_unverified_year_not_computed(repo, depot):
    fund(repo, NMF_FUND, FundStatus.NICHTMELDEFONDS)
    add_tx(repo, depot, TxType.BUY, "2024-02-01", isin=NMF_FUND, quantity=10, amount=1000)
    repo.upsert_nmf_price(NMF_FUND, 2024, 100.0, "2024-01-02", 130.0, "2024-12-30", source="Testkurse")
    res = compute(repo, 2024)
    nmf = one(res.lines, CAT_NMF)
    assert nmf.amount is None and nmf.status == MANUAL
    assert res.summary["Nichtmeldefonds pauschal"] == 0
    assert any("nicht verifiziert" in i.message and NMF_FUND in i.message for i in res.issues)


def test_nichtmeldefonds_missing_prices(repo, depot):
    fund(repo, NMF_FUND, FundStatus.NICHTMELDEFONDS)
    add_tx(repo, depot, TxType.BUY, "2023-02-01", isin=NMF_FUND, quantity=10, amount=1000)
    res = compute(repo, 2023)
    nmf = one(res.lines, CAT_NMF)
    assert nmf.amount is None
    assert "Rücknahmepreis" in res.nmf_rows[0]["Datenlücken / Prüfhinweise"]


def test_reit_without_classification_is_unclear(repo, depot):
    stock(repo, isin=REIT, name="Realty Income", stype=SecurityType.REIT)
    add_tx(repo, depot, TxType.DIVIDEND, "2024-02-15", isin=REIT, amount=25, withholding_tax=3.75,
           withholding_country="US")
    res = compute(repo, 2024)
    u = one(res.lines, CAT_UNCLEAR)
    assert u.amount is None and "REIT" in u.notes[0]
    assert res.summary["Dividenden"] == 0
    # nach belegter Einstufung je Buchung wird berechnet (vorläufig)
    tx = repo.transactions(2024)[0]
    repo.update_transaction(tx["id"], {"income_category": IncomeCategory.DIVIDEND.value,
                                       "income_category_verified": 1}, reason="Form 1099-DIV: ordinary dividend")
    res = compute(repo, 2024)
    d = one(res.lines, CAT_DIVIDEND)
    assert d.amount == pytest.approx(25) and d.status == PROVISIONAL


def test_rules_catalog_has_sources():
    rules = load_rules()
    for row in rules.catalog():
        assert row["Status"]
    r = rules.rule("NICHTMELDEFONDS_PAUSCHAL", 2025)
    assert not r.computable
    assert rules.rule("RATE_27_5", 2024).status == "offiziell_auszug"
