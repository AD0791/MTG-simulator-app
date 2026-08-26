"""Transport contracts for the JSON API.

These carry types, required fields, and limits that protect the *server*. They
deliberately do **not** restate the domain's rules — capital must be positive, a
payout ratio must sit in (0, 1], a target profit cannot be negative. Those live
in `StakingConfig.__post_init__`, which protects the calculation from every
caller, and a second copy here would drift from it.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# A ceiling on the simulated ladder length. This is a request-shape constraint,
# not a domain rule: it bounds the work one request can ask the server to do.
MAX_ENTRIES_CEILING = 200


class SimulationCreate(BaseModel):
    """A staking plan to simulate.

    Every field is optional; the defaults mirror `StakingConfig`'s, so a body
    need only carry what it changes.
    """

    model_config = ConfigDict(extra="forbid")

    capital: float = 1000.0
    entry_1a: float = 5.0
    entry_1b: float = 5.0
    second_entry: float = 18.0
    payout_ratio: float = 0.92
    target_profit: float = 0.0
    max_entries: int = Field(default=50, ge=1, le=MAX_ENTRIES_CEILING)


class RawSimulationForm(BaseModel):
    """Exactly what the browser posted, before any coercion.

    Kept as text so a rejected submission can be re-rendered with the reader's
    own values still in the inputs.
    """

    model_config = ConfigDict(extra="ignore")

    capital: str = ""
    payout_percent: str = ""
    second_entry: str = ""
    entry_1a: str = "5"
    entry_1b: str = "5"
    target_profit: str = "0"
    max_entries: str = "50"


class SimulationForm(BaseModel):
    """The browser form's shape.

    It differs from `SimulationCreate` in one respect: the payout is entered as a
    percentage, because that is how a broker quotes it. The conversion to a ratio
    happens here so the rest of the app only ever sees a ratio.
    """

    model_config = ConfigDict(extra="ignore")

    capital: float
    payout_percent: float
    second_entry: float
    entry_1a: float = 5.0
    entry_1b: float = 5.0
    target_profit: float = 0.0
    max_entries: int = Field(default=50, ge=1, le=MAX_ENTRIES_CEILING)

    def to_create(self) -> "SimulationCreate":
        return SimulationCreate(
            capital=self.capital,
            entry_1a=self.entry_1a,
            entry_1b=self.entry_1b,
            second_entry=self.second_entry,
            payout_ratio=self.payout_percent / 100,
            target_profit=self.target_profit,
            max_entries=self.max_entries,
        )


class EntryRead(BaseModel):
    """One rung of the ladder."""

    model_config = ConfigDict(from_attributes=True)

    position: int
    label: str
    stake: float
    cumulative_loss: float
    balance: float
    balance_if_win: float


class SimulationSummary(BaseModel):
    """A stored run as it appears in a listing — inputs and verdict, no ladder."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    capital: float
    second_entry: float
    payout_ratio: float
    wall_hit: bool
    wall_required_stake: float | None
    wall_balance_available: float | None
    losses_survived: int


class SimulationRead(SimulationSummary):
    """A stored run in full, including every entry placed before the wall."""

    entry_1a: float
    entry_1b: float
    target_profit: float
    max_entries: int
    entries: list[EntryRead]


class Problem(BaseModel):
    """RFC 9457 problem detail — the shape of every 4xx from the error seam."""

    model_config = ConfigDict(json_schema_extra={"contentMediaType": "application/problem+json"})

    type: str = "about:blank"
    title: str
    status: int
    detail: str
