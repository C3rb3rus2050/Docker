"""Hilfsfunktionen für KESt-Tool-Tests."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from kest_tool.config import load_settings
from kest_tool.context import create_context

from kest_tool.models import FundStatus, SecurityIn, SecurityType, TaxClass, TransactionIn, TxType

# Gültige ISIN (Prüfziffern korrekt)
APPLE = "US0378331005"
MSCI_WORLD_ACC = "IE00B4L5Y983"
VANGUARD_DIST = "IE00B3RBWM25"
NMF_FUND = "LU0274208692"
REIT = "US7561091049"   # Realty Income
SAP = "DE0007164600"


def add_tx(repo, depot_id, tx_type: TxType, d: str, **kw) -> int:
    return repo.add_transaction(TransactionIn(depot_id=depot_id, tx_type=tx_type, trade_date=date.fromisoformat(d),
                                              **kw))


def stock(repo, isin=APPLE, name="Apple Inc.", verified=True, country="US", stype=SecurityType.STOCK):
    repo.upsert_security(SecurityIn(isin=isin, name=name, country=country, security_type=stype,
                                    tax_class=TaxClass.KAPITALGESELLSCHAFT, tax_class_verified=verified,
                                    tax_class_source="Test: Rechtsform Inc. laut Emittentenangaben" if verified else None,
                                    fund_status=FundStatus.NO_FUND))


def fund(repo, isin, status: FundStatus, stype=SecurityType.ETF_ACC, name="Fonds"):
    repo.upsert_security(SecurityIn(isin=isin, name=name, country="IE", security_type=stype,
                                    tax_class=TaxClass.INVESTMENTFONDS, tax_class_verified=True,
                                    tax_class_source="Test", fund_status=status, fund_status_verified=True,
                                    fund_status_source="Test"))

@pytest.fixture()
def ctx(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KEST_TOOL_HOME", str(tmp_path / "KESt-Tool"))
    settings = load_settings(local_file=tmp_path / "none.yaml")
    c = create_context(settings, base_dir=tmp_path / "KESt-Tool")
    yield c
    c.close()


@pytest.fixture()
def repo(ctx):
    return ctx.repo


@pytest.fixture()
def depot(repo):
    """Ausländisches Depot ohne KESt-Abzug (Steuerjahre 2023–2025 gesetzt)."""
    b = repo.add_broker("Trade Republic", "TradeRepublic", "DE")
    d = repo.add_depot(b, "TR Depot")
    for y in (2023, 2024, 2025):
        repo.set_depot_tax_settings(d, y, "nein", "nein", source="Test")
    return d
