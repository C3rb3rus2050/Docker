"""Wertpapierkurse: Symbolsuche per ISIN, Jahreskurse für Nichtmeldefonds, Bewertung 31.12., CSV-Import."""

from __future__ import annotations

import os
from datetime import date

import pytest

from kest_helpers import APPLE, NMF_FUND, add_tx, ctx, depot, fund, repo, stock  # noqa: F401
from kest_tool.config import load_env_file, save_env_var
from kest_tool.models import FundStatus, TxType
from kest_tool.prices import (
    EodhdProvider,
    PriceError,
    PriceService,
    fill_nmf_prices,
    fill_year_end_prices,
    import_price_csv,
)
from kest_tool.tax.engine import CAT_NMF, compute


class FakeApi:
    """Antworten im Format der EODHD-API (search / eod)."""

    def __init__(self):
        self.calls = []

    def __call__(self, url: str):
        self.calls.append(url)
        assert "api_token=TESTKEY" in url and "fmt=json" in url
        if "/search/LU0274208692" in url:
            return [{"Code": "XDWD", "Exchange": "LSE", "Name": "Xtrackers MSCI World", "Currency": "USD",
                     "ISIN": "LU0274208692"},
                    {"Code": "XDWD", "Exchange": "XETRA", "Name": "Xtrackers MSCI World", "Currency": "EUR",
                     "ISIN": "LU0274208692"}]
        if "/search/US0378331005" in url:
            return [{"Code": "AAPL", "Exchange": "US", "Name": "Apple Inc", "Currency": "USD", "ISIN": "US0378331005"}]
        if "/eod/XDWD.XETRA" in url:
            return [{"date": "2022-12-30", "close": 99.0}, {"date": "2023-01-02", "close": 100.0},
                    {"date": "2023-06-30", "close": 105.0}, {"date": "2023-12-29", "close": 110.0}]
        if "/eod/AAPL.US" in url:
            return [{"date": "2023-12-29", "close": 192.53}]
        raise OSError("unbekannte URL")


def _svc(repo, api):
    return PriceService(repo, EodhdProvider(api_key="TESTKEY", fetch=api))


def test_nmf_year_prices_and_calculation(repo, depot):
    fund(repo, NMF_FUND, FundStatus.NICHTMELDEFONDS)
    add_tx(repo, depot, TxType.BUY, "2023-02-01", isin=NMF_FUND, quantity=10, amount=1000)
    api = FakeApi()
    res = fill_nmf_prices(repo, _svc(repo, api), 2023)
    assert [(r.isin, r.status) for r in res] == [(NMF_FUND, "gesetzt")]
    p = repo.nmf_prices(2023)[0]
    assert (p["first_price"], p["first_price_date"]) == (100.0, "2023-01-02")    # erster Kurs IM Jahr
    assert (p["last_price"], p["last_price_date"]) == (110.0, "2023-12-29")
    assert "kein Rücknahmepreis" in p["source"] and p["review_status"] == "ungeprueft"
    assert repo.security_by_isin(NMF_FUND)["price_symbol"] == "XDWD.XETRA"       # EUR-Notiz bevorzugt
    result = compute(repo, 2023)
    nmf = [l for l in result.lines if l.category == CAT_NMF][0]
    assert nmf.amount == pytest.approx(110)                                       # max(0,9×10; 0,1×110) × 10
    assert "Rücknahmepreisen" in result.nmf_rows[0]["Datenlücken / Prüfhinweise"]
    # zweiter Lauf: kein erneuter Abruf, nichts überschrieben
    n = len(api.calls)
    assert fill_nmf_prices(repo, _svc(repo, api), 2023)[0].status == "identisch"
    assert len(api.calls) == n


def test_existing_manual_nmf_prices_are_not_overwritten(repo, depot):
    fund(repo, NMF_FUND, FundStatus.NICHTMELDEFONDS)
    add_tx(repo, depot, TxType.BUY, "2023-02-01", isin=NMF_FUND, quantity=10, amount=1000)
    repo.upsert_nmf_price(NMF_FUND, 2023, 101.0, "2023-01-02", None, None, source="Fondsgesellschaft")
    fill_nmf_prices(repo, _svc(repo, FakeApi()), 2023)
    p = repo.nmf_prices(2023)[0]
    assert p["first_price"] == 101.0                                   # manueller Wert bleibt
    assert any(c["entity"] == "nmf_price" and c["field"] == "first_price" for c in repo.conflicts("offen"))


def test_year_end_valuation(repo, depot, ctx):
    stock(repo)
    add_tx(repo, depot, TxType.BUY, "2023-03-01", isin=APPLE, quantity=10, amount=1500)
    res = fill_year_end_prices(repo, _svc(repo, FakeApi()), 2023)
    assert res[0].status == "gesetzt"
    from kest_tool.fx import FxService
    FxService(ctx.store.base).import_bytes(b"Date,USD,\n2023-12-29,1.1050,\n")
    pos = compute(repo, 2023).positions[0]
    assert pos["Kurs 31.12."] == pytest.approx(192.53) and pos["Kurswährung"] == "USD"
    assert pos["Wert 31.12. EUR"] == pytest.approx(10 * 192.53 / 1.1050, abs=0.01)
    assert pos["Unrealisiert EUR (Info)"] == pytest.approx(10 * 192.53 / 1.1050 - 1500, abs=0.01)


def test_no_key_and_errors_are_explained(repo, depot, monkeypatch):
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    prov = EodhdProvider(api_key="")
    assert not prov.available
    with pytest.raises(PriceError, match="API-Schlüssel"):
        prov.find_symbol(APPLE)

    def boom(url):
        raise OSError(f"HTTP 402 for {url}")

    err = EodhdProvider(api_key="GEHEIM123", fetch=boom)
    with pytest.raises(PriceError) as exc:
        err.find_symbol(APPLE)
    assert "GEHEIM123" not in str(exc.value) and "CSV" in str(exc.value)


def test_price_csv_import(repo, depot):
    fund(repo, NMF_FUND, FundStatus.NICHTMELDEFONDS)
    add_tx(repo, depot, TxType.BUY, "2023-02-01", isin=NMF_FUND, quantity=10, amount=1000)
    data = "ISIN;Datum;Kurs;Währung\nLU0274208692;02.01.2023;100,00;EUR\nLU0274208692;29.12.2023;110,00;EUR\n"
    svc = _svc(repo, FakeApi())
    assert import_price_csv(repo, svc, data.encode(), "kurse.csv") == 2
    assert svc.price_on(NMF_FUND, date(2023, 12, 31))["close"] == 110.0


def test_env_file_helpers(tmp_path, monkeypatch):
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    env = tmp_path / ".env"
    save_env_var("EODHD_API_KEY", "abc", env)
    assert os.environ["EODHD_API_KEY"] == "abc" and "EODHD_API_KEY=abc" in env.read_text()
    monkeypatch.delenv("EODHD_API_KEY")
    load_env_file(env)
    assert os.environ["EODHD_API_KEY"] == "abc"
    save_env_var("EODHD_API_KEY", "", env)
    assert "EODHD_API_KEY" not in env.read_text() and "EODHD_API_KEY" not in os.environ


class NavApi(FakeApi):
    """Wie FakeApi, zusätzlich Rücknahmepreise über EUFUND (Ticker = ISIN.EUFUND)."""

    def __call__(self, url: str):
        if "/eod/LU0274208692.EUFUND" in url:
            self.calls.append(url)
            return [{"date": "2023-01-03", "close": 50.0}, {"date": "2023-12-28", "close": 60.0}]
        if "/search/LU0274208692" in url:
            self.calls.append(url)
            return [{"Code": "LU0274208692", "Exchange": "EUFUND", "Currency": "USD", "ISIN": "LU0274208692"},
                    {"Code": "XDWD", "Exchange": "XETRA", "Currency": "EUR", "ISIN": "LU0274208692"}]
        return super().__call__(url)


def test_redemption_prices_preferred_via_eufund(repo, depot, ctx):
    from kest_tool.fx import FxService
    FxService(ctx.store.base).import_bytes(b"Date,USD,\n2023-12-28,1.1000,\n")
    fund(repo, NMF_FUND, FundStatus.NICHTMELDEFONDS)
    add_tx(repo, depot, TxType.BUY, "2023-02-01", isin=NMF_FUND, quantity=10, amount=1000)
    api = NavApi()
    res = fill_nmf_prices(repo, _svc(repo, api), 2023)
    assert res[0].status == "gesetzt" and res[0].message.startswith("Rücknahmepreis")
    assert not any("/eod/XDWD" in u for u in api.calls)                       # kein Börsenkurs nötig
    p = repo.nmf_prices(2023)[0]
    assert (p["first_price"], p["last_price"], p["currency"]) == (50.0, 60.0, "USD")
    assert p["fx_rate_last"] == pytest.approx(1.1)
    assert "Rücknahmepreis" in p["source"] and "kein Rücknahmepreis" not in p["source"]
    result = compute(repo, 2023)
    nmf = [l for l in result.lines if l.category == CAT_NMF][0]
    # max(0,9 × 10; 0,1 × 60) = 9 USD je Anteil × 10 / 1,1 = 81,82 EUR
    assert nmf.amount == pytest.approx(9 * 10 / 1.1, abs=0.01)
    assert "Rücknahmepreisen" not in result.nmf_rows[0]["Datenlücken / Prüfhinweise"]


def test_imported_redemption_prices_used_without_network(repo, depot):
    fund(repo, NMF_FUND, FundStatus.NICHTMELDEFONDS)
    add_tx(repo, depot, TxType.BUY, "2023-02-01", isin=NMF_FUND, quantity=10, amount=1000)
    svc = PriceService(repo, EodhdProvider(api_key=""))                      # kein Schlüssel
    data = "ISIN;Datum;Rücknahmepreis;Währung\nLU0274208692;02.01.2023;100,00;EUR\nLU0274208692;29.12.2023;104,00;EUR\n"
    assert import_price_csv(repo, svc, data.encode(), "fondsgesellschaft.csv", redemption=True) == 2
    res = fill_nmf_prices(repo, svc, 2023)
    assert res[0].status == "gesetzt" and res[0].message.startswith("Rücknahmepreis")
    p = repo.nmf_prices(2023)[0]
    assert (p["first_price"], p["last_price"]) == (100.0, 104.0)
    assert "Rücknahmepreis (manueller Import" in p["source"]


def test_fallback_to_exchange_close_explains_missing_nav(repo, depot):
    fund(repo, NMF_FUND, FundStatus.NICHTMELDEFONDS)
    add_tx(repo, depot, TxType.BUY, "2023-02-01", isin=NMF_FUND, quantity=10, amount=1000)
    res = fill_nmf_prices(repo, _svc(repo, FakeApi()), 2023)                 # EUFUND schlägt fehl
    assert res[0].status == "gesetzt" and res[0].message.startswith("Börsenkurs")
    assert "All World Extended" in res[0].message
    assert "kein Rücknahmepreis" in repo.nmf_prices(2023)[0]["source"]
    # ohne Ersatz: kein Wert, sondern Fehler mit Grund
    repo.db.execute("DELETE FROM nmf_prices")
    repo.db.execute("DELETE FROM security_prices")
    res = fill_nmf_prices(repo, _svc(repo, FakeApi()), 2023, allow_exchange_fallback=False)
    assert res[0].status == "fehler" and "EUFUND" in res[0].message
    assert repo.nmf_prices(2023) == []
