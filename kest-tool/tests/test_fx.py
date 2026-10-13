"""Devisenkurse: EZB-Format, Wochenend-Rückgriff, Ergänzen fehlender Kurse, Belegkurse unverändert."""

from __future__ import annotations

import io
import sqlite3
import zipfile
from datetime import date

import pytest

from kest_helpers import APPLE, add_tx, ctx, depot, repo, stock  # noqa: F401
from kest_tool.db import Database
from kest_tool.fx import FxError, FxService, fill_missing_fx, parse_ecb_csv
from kest_tool.models import TxType
from kest_tool.tax.engine import CAT_DIVIDEND, compute

# Gleiches Format wie https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip (Werte frei gewählt)
ECB_CSV = (
    "Date,USD,JPY,CHF,CYP,\n"
    "2024-02-16,1.0776,161.92,0.9487,N/A,\n"
    "2024-02-15,1.0745,161.36,0.9504,N/A,\n"
    "2024-02-14,1.0713,161.43,0.9517,N/A,\n"
    "2023-12-29,1.1050,156.33,0.9260,N/A,\n"
)


def _zip(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("eurofxref-hist.csv", text)
    return buf.getvalue()


def test_parse_and_lookup_with_weekend_backtrack():
    r = parse_ecb_csv(ECB_CSV)
    assert r.currencies == ["CHF", "JPY", "USD"]          # N/A-Spalten werden ignoriert
    assert r.lookup("USD", date(2024, 2, 15)) == (1.0745, date(2024, 2, 15))
    assert r.lookup("USD", date(2024, 2, 18)) == (1.0776, date(2024, 2, 16))   # Sonntag → Freitag
    assert r.lookup("USD", date(2024, 3, 30)) is None                          # > 7 Tage Lücke
    assert r.lookup("EUR", date(2024, 1, 1)) == (1.0, date(2024, 1, 1))
    assert r.lookup("XYZ", date(2024, 2, 15)) is None
    with pytest.raises(FxError):
        parse_ecb_csv("foo,bar\n1,2\n")


def test_download_via_url_and_cache(ctx, tmp_path):
    src = tmp_path / "eurofxref-hist.zip"
    src.write_bytes(_zip(ECB_CSV))
    svc = FxService(ctx.store.base, url=src.as_uri())
    rates = svc.download()
    assert rates.last_date == date(2024, 2, 16)
    assert svc.cache_file.exists()
    again = FxService(ctx.store.base, url="file:///gibt/es/nicht.zip").rates(allow_download=False)
    assert again.lookup("CHF", date(2024, 2, 14))[0] == pytest.approx(0.9517)


def test_download_failure_is_explained(ctx):
    svc = FxService(ctx.store.base, url="file:///gibt/es/nicht.zip")
    with pytest.raises(FxError, match="manuell"):
        svc.download()


def test_fill_missing_fx_and_compute(repo, depot, ctx):
    stock(repo)
    FxService(ctx.store.base).import_bytes(_zip(ECB_CSV))
    t_missing = add_tx(repo, depot, TxType.DIVIDEND, "2024-02-17", isin=APPLE, amount=10.745, currency="USD",
                       withholding_tax=1.61, withholding_country="US")           # Samstag → Kurs vom 16.02.
    t_beleg = add_tx(repo, depot, TxType.DIVIDEND, "2024-02-15", isin=APPLE, amount=10.0, currency="USD",
                     fx_rate=1.08)
    before = compute(repo, 2024)
    assert any("ohne Devisenkurs" in i.message for i in before.issues)
    res = fill_missing_fx(repo, FxService(ctx.store.base), 2024, allow_download=False)
    assert [(r.tx_id, r.status, r.rate_date) for r in res] == [(t_missing, "gesetzt", "2024-02-16")]
    tx = repo.transaction(t_missing)
    assert tx["fx_rate"] == pytest.approx(1.0776)
    assert tx["amount_eur"] == pytest.approx(10.745 / 1.0776)
    assert tx["withholding_tax_eur"] == pytest.approx(1.61 / 1.0776)
    assert "EZB-Referenzkurs" in tx["fx_source"] and "letzter Bankarbeitstag" in tx["fx_source"]
    assert repo.transaction(t_beleg)["fx_rate"] == pytest.approx(1.08)          # Belegkurs unverändert
    assert any(a["action"] == "manuell geändert" and "Devisenkurs automatisch" in a["details"]
               for a in repo.audit_entries())
    after = compute(repo, 2024)
    assert not any("ohne Devisenkurs" in i.message for i in after.issues)
    divs = [l for l in after.lines if l.category == CAT_DIVIDEND]
    assert sum(l.amount for l in divs) == pytest.approx(10.745 / 1.0776 + 10 / 1.08, abs=0.01)
    assert any("EZB-Referenzkurs" in n for l in divs for n in l.notes)
    assert fill_missing_fx(repo, FxService(ctx.store.base), 2024, allow_download=False) == []


def test_no_rates_without_download(repo, depot, ctx):
    add_tx(repo, depot, TxType.BUY, "2024-02-15", isin=APPLE, quantity=1, amount=100, currency="USD")
    with pytest.raises(FxError):
        fill_missing_fx(repo, FxService(ctx.store.base), 2024, allow_download=False)


def test_schema_migration_adds_fx_source(tmp_path):
    """Datenbank der Vorversion (Schema 1, ohne fx_source) wird beim Öffnen ergänzt – Daten bleiben erhalten."""
    from kest_tool import db as dbmod

    v1 = "\n".join(l for l in dbmod.SCHEMA.splitlines() if "fx_source" not in l)
    p = tmp_path / "alt.db"
    con = sqlite3.connect(p)
    con.executescript(v1)
    con.execute("INSERT INTO meta VALUES('schema_version','1')")
    con.execute("INSERT INTO brokers(name, key, created_at) VALUES('B','Other','x')")
    con.execute("INSERT INTO depots(broker_id, name, created_at) VALUES(1,'D','x')")
    con.execute("INSERT INTO transactions(depot_id, tx_type, trade_date, currency, created_at) "
                "VALUES(1,'Kauf','2024-01-01','USD','x')")
    con.commit()
    con.close()
    db = Database(p)
    cols = {r["name"] for r in db.query("PRAGMA table_info(transactions)")}
    assert "fx_source" in cols
    assert db.one("SELECT COUNT(*) n FROM transactions")["n"] == 1
    assert db.one("SELECT value FROM meta WHERE key='schema_version'")["value"] == str(dbmod.SCHEMA_VERSION)
    db.close()
