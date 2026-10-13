"""CSV-/Excel-Import: deutsche Formate, Spaltenzuordnung, Dubletten, Brokerzuordnung."""

from __future__ import annotations

import io

import pandas as pd
import pytest

from kest_helpers import ctx, depot, repo  # noqa: F401
from kest_tool.importers.csv_importer import (
    ImportError_,
    ImportOptions,
    auto_mapping,
    build_preview,
    commit_preview,
    preview_frame,
    read_table,
)
from kest_tool.importers.parsing import detect_decimal_separator, parse_number, parse_tx_type
from kest_tool.models import TxType

GERMAN_CSV = (
    "Datum;Typ;ISIN;Wertpapier;Stück;Kurs;Betrag;Gebühren;Währung;Quellensteuer;Land\n"
    "15.03.2024;Kauf;US0378331005;Apple Inc.;10;150,25;1.502,50;1,00;EUR;;\n"
    "16.05.2024;Dividende;US0378331005;Apple Inc.;;;2,40;;EUR;0,36;US\n"
    "02.09.2024;Verkauf;US0378331005;Apple Inc.;5;180,00;900,00;1,00;EUR;;\n"
)


def _import(repo, depot, data: bytes, name="export.csv", options=None, decisions=None):
    doc, new = repo.add_document(data, name, doc_type="Transaktionsexport (CSV)", source="TradeRepublic",
                                 tax_year=2024)
    df, meta = read_table(data, name)
    mapping = auto_mapping(list(df.columns))
    rows = build_preview(df, mapping, options or ImportOptions(), depot, repo)
    res = commit_preview(repo, rows, decisions or {}, import_type="CSV", depot_id=depot, document_id=doc["id"])
    return doc, new, rows, res


def test_parse_numbers_german_and_english():
    assert parse_number("1.234,56", ",") == pytest.approx(1234.56)
    assert parse_number("-12,5 €", ",") == pytest.approx(-12.5)
    assert parse_number("(12.50)", ".") == pytest.approx(-12.5)
    assert parse_number("1,234.56", ".") == pytest.approx(1234.56)
    assert parse_number("12,50-", ",") == pytest.approx(-12.5)
    assert parse_number("", ",") is None
    assert detect_decimal_separator(["1.502,50", "2,40", "900,00"]) == ","
    assert detect_decimal_separator(["1502.50", "2.40", "1,234.00"]) == "."
    assert parse_tx_type("Sparplanausführung") == TxType.BUY
    assert parse_tx_type("Ausschüttung") == TxType.DISTRIBUTION
    assert parse_tx_type("Quellensteuer") == TxType.TAX


def test_csv_with_german_decimal_separator(repo, depot):
    df, meta = read_table(GERMAN_CSV.encode("cp1252"), "tr.csv")
    assert meta["separator"] == ";" and meta["encoding"] in ("cp1252", "latin-1", "utf-8-sig")
    mapping = auto_mapping(list(df.columns))
    assert mapping["trade_date"] == "Datum" and mapping["quantity"] == "Stück" and mapping["amount"] == "Betrag"
    assert mapping["withholding_tax"] == "Quellensteuer" and mapping["withholding_country"] == "Land"
    rows = build_preview(df, mapping, ImportOptions(), depot, repo)
    assert all(not r.errors for r in rows), [r.errors for r in rows]
    buy, div, sell = (r.tx for r in rows)
    assert buy.amount == pytest.approx(1502.50) and buy.price == pytest.approx(150.25) and buy.fees == 1.0
    assert buy.trade_date.isoformat() == "2024-03-15"
    assert div.tx_type == TxType.DIVIDEND and div.withholding_tax == pytest.approx(0.36)
    assert sell.quantity == 5
    frame = preview_frame(rows)
    assert list(frame["Entscheidung"]) == ["uebernehmen"] * 3


def test_reimport_detects_duplicate_document_and_rows(repo, depot):
    data = GERMAN_CSV.encode("utf-8")
    doc1, new1, _, res1 = _import(repo, depot, data)
    assert new1 and res1["rows_imported"] == 3
    doc2, new2, rows2, res2 = _import(repo, depot, data, name="export_kopie.csv")
    assert not new2 and doc2["id"] == doc1["id"]                 # gleicher SHA-256 → kein zweites Dokument
    assert all(r.duplicate == "dublette" for r in rows2)
    assert res2["rows_imported"] == 0 and res2["rows_duplicates"] == 3
    assert len(repo.transactions()) == 3
    assert any(e["event"] == "erneuter_import_erkannt" for e in repo.document_events(doc1["id"]))
    assert len(list((repo.store.base / "documents" / "2024" / "TradeRepublic").iterdir())) == 1


def test_duplicate_decision_by_user(repo, depot):
    _import(repo, depot, GERMAN_CSV.encode())
    other = GERMAN_CSV.replace("1,00;EUR;;\n", "1,00;EUR;; \n", 1).encode()  # anderer Hash, gleiche Buchungen
    doc, new, rows, res = _import(repo, depot, other, name="anders.csv", decisions={2: "pruefen"})
    assert new
    assert res["rows_imported"] == 1 and res["rows_skipped"] == 2
    flagged = [t for t in repo.transactions() if t["review_status"] == "pruefen"]
    assert len(flagged) == 1 and "Dublettenverdacht" in flagged[0]["notes"]


def test_possible_duplicate_fuzzy(repo, depot):
    _import(repo, depot, GERMAN_CSV.encode())
    shifted = ("Datum;Typ;ISIN;Stück;Betrag\n16.03.2024;Kauf;US0378331005;10;1.502,50\n").encode()
    df, _ = read_table(shifted, "x.csv")
    rows = build_preview(df, auto_mapping(list(df.columns)), ImportOptions(), depot, repo)
    assert rows[0].duplicate == "moeglich" and rows[0].default_decision == "pruefen"


def test_transactions_assigned_to_correct_broker(repo):
    tr = repo.add_depot(repo.add_broker("Trade Republic", "TradeRepublic"), "TR")
    sc = repo.add_depot(repo.add_broker("Scalable Capital", "ScalableCapital"), "SC Prime")
    df, _ = read_table(GERMAN_CSV.encode(), "sc.csv")
    rows = build_preview(df, auto_mapping(list(df.columns)), ImportOptions(), sc, repo)
    commit_preview(repo, rows, {}, import_type="CSV", depot_id=sc)
    txs = repo.transactions()
    assert {t["broker_name"] for t in txs} == {"Scalable Capital"}
    assert {t["depot_id"] for t in txs} == {sc}
    assert repo.transactions(depot_id=tr) == []
    # gleiche Buchungen in anderem Depot sind keine Dubletten
    rows_tr = build_preview(df, auto_mapping(list(df.columns)), ImportOptions(), tr, repo)
    assert all(r.duplicate == "neu" for r in rows_tr)


def test_manual_mapping_and_errors(repo, depot):
    csv = "Tag;Vorgang X;Wert;Code\n2024-01-05;Spezialbuchung;10.5;US0378331005\n2024-01-06;Kauf;;US0378331005\n"
    df, _ = read_table(csv.encode(), "x.csv")
    auto = auto_mapping(list(df.columns))
    assert auto["isin"] is None
    with pytest.raises(ImportError_):
        build_preview(df, {"trade_date": "Tag"}, ImportOptions(), depot, repo)
    mapping = {**auto, "trade_date": "Tag", "tx_type": "Vorgang X", "amount": "Wert", "isin": "Code"}
    rows = build_preview(df, mapping, ImportOptions(decimal="."), depot, repo)
    assert "unbekannt" in rows[0].errors[0]
    assert rows[1].errors  # Kauf ohne Stückzahl
    # Benutzer ordnet den unbekannten Typwert zu
    rows = build_preview(df, mapping, ImportOptions(decimal=".", type_value_map={"Spezialbuchung": "Dividende"}),
                         depot, repo)
    assert rows[0].tx.tx_type == TxType.DIVIDEND and rows[0].tx.amount == pytest.approx(10.5)


def test_foreign_currency_warning_and_netto(repo, depot):
    csv = ("Date,Type,ISIN,Quantity,Amount,Fees,Currency,FX Rate\n"
           "03/15/2024,Buy,US0378331005,2,-301.00,1.00,USD,1.0850\n"
           "03/16/2024,Buy,US0378331005,2,-301.00,1.00,USD,\n")
    df, meta = read_table(csv.encode(), "ibkr.csv")
    assert meta["separator"] == ","
    rows = build_preview(df, auto_mapping(list(df.columns)), ImportOptions(amount_is="netto"), depot, repo)
    assert rows[0].tx.amount == pytest.approx(300.0) and rows[0].tx.fx_rate == pytest.approx(1.085)
    assert rows[0].tx.trade_date.isoformat() == "2024-03-15"
    assert any("ohne Devisenkurs" in w for w in rows[1].warnings)


def test_excel_import(repo, depot):
    df = pd.DataFrame({"Buchungsdatum": ["2024-02-01"], "Art": ["Zinsen"], "Betrag": ["3,21"]})
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    table, meta = read_table(buf.getvalue(), "zinsen.xlsx")
    assert meta["format"] == "excel"
    rows = build_preview(table, auto_mapping(list(table.columns)), ImportOptions(), depot, repo)
    assert rows[0].tx.tx_type == TxType.INTEREST and rows[0].tx.amount == pytest.approx(3.21)


def test_import_log_written(repo, depot):
    doc, _, _, res = _import(repo, depot, GERMAN_CSV.encode())
    run = repo.import_runs()[0]
    assert run["rows_imported"] == 3 and run["status"] == "abgeschlossen"
    logs = list((repo.store.base / "imports" / "2024" / "import_logs").glob("import_*.log"))
    assert logs and "Importlauf" in logs[0].read_text(encoding="utf-8")
    assert all(t["document_id"] == doc["id"] for t in repo.transactions())
    assert repo.document(doc["id"])["status"] == "verarbeitet"
