from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Edit(Input):
    values: dict[str, Any]
    reason: str = ''
    revision: str | None = None


class Review(Edit):
    confirmed: bool = False
    transaction_id: int | None = None
    duplicate_confirmed: bool = False


class SecurityReview(Edit):
    review: Literal['ungeprueft', 'pruefen', 'geprueft'] = 'ungeprueft'
    price_symbol: str = ''


class Process(Input):
    ids: list[int] = Field(max_length=1000)
    depot_id: int | None = None


class Broker(Input):
    name: str = Field(min_length=1, max_length=160)
    key: Literal['TradeRepublic', 'ScalableCapital', 'Other'] = 'Other'
    country: str | None = None
    notes: str | None = None


class Depot(Input):
    broker_id: int
    name: str = Field(min_length=1, max_length=160)
    account_ref: str | None = None
    currency: str = Field(default='EUR', pattern='^[A-Z]{3}$')
    notes: str | None = None
    active: bool = True


class DepotTax(Input):
    kest_withheld: Literal['ja', 'nein', 'unbekannt']
    loss_offset_by_broker: Literal['ja', 'nein', 'unbekannt']
    source: str = ''
    notes: str = ''


class Decision(Input):
    existing_id: int
    new_id: int
    decision: Literal['bestehend_behalten', 'neu_uebernommen']
    note: str = Field(min_length=1)


class Nmf(Input):
    isin: str
    tax_year: int = Field(ge=2000, le=2100)
    first_price: float | None = Field(default=None, gt=0)
    first_date: str | None = None
    last_price: float | None = Field(default=None, gt=0)
    last_date: str | None = None
    currency: str = Field(default='EUR', pattern='^[A-Z]{3}$')
    fx_rate_last: float | None = Field(default=None, gt=0)
    source: str = Field(min_length=1)


class Consent(Input):
    confirmed: bool = False
