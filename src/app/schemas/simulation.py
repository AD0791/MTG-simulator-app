"""Transport contracts for the JSON API.

These carry types, required fields, and limits that protect the *server*. They
deliberately do **not** restate the domain's rules — capital must be positive, a
payout ratio must sit in (0, 1], a target profit cannot be negative. Those live
in `StakingConfig.__post_init__`, which protects the calculation from every
caller, and a second copy here would drift from it.

`SimulationSummary` dropped `second_entry` from the v1 contract without cutting
a v2 (roadmap item 0) — the API had no external consumers, and the stored
column is kept nullable so already-recorded runs keep their data.

`strategies` on the form is a request-shape concern, not a domain one — the
domain only ever knows one strategy at a time (`StakingConfig.strategy`), so
"at least one strategy chosen" is policed here, in `Field(min_length=1)`, and
each individual name is left to the same domain rejection a bad payout gets.

The form asks for a target profit as a percentage of capital, the same
precedent as `payout_percent` — converted to an absolute dollar amount in
`SimulationForm.to_creates()` so the domain never learns about percentages.
`SimulationCreate` stays in absolute dollars too: the JSON API is a direct
line to the domain's own units, not the form's.

Whether a plan opens with one entry or two is likewise a request-shape
concern, not a domain one — `RawSimulationForm.opener_count` and
`SimulationForm.opener_count` resolve to `entry_1b=None` in `to_creates()`
when one opener is chosen. `StakingConfig` never learns a "count" exists;
it only ever sees `entry_1b` as `float | None`.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    entry_1b: float | None = 5.0
    payout_ratio: float = 0.92
    target_profit: float = 0.0
    max_entries: int = Field(default=50, ge=1, le=MAX_ENTRIES_CEILING)
    # One of STRATEGIES in `domain.staking_simulator`. Not constrained to a
    # Literal here — an unknown name is a domain rejection, same seam as an
    # impossible payout, not a second copy of the check.
    strategy: str = "adder_profit"


class RawSimulationForm(BaseModel):
    """Exactly what the browser posted, before any coercion.

    Kept as text so a rejected submission can be re-rendered with the reader's
    own values still in the inputs.
    """

    model_config = ConfigDict(extra="ignore")

    capital: str = ""
    payout_percent: str = ""
    entry_1a: str = "5"
    entry_1b: str = "5"
    # "1" or "2" openers. A form concern resolved at the edge, same precedent
    # as payout_percent and target_profit_percent -- the domain never learns
    # a "count" exists, only ever `entry_1b` as `float | None`.
    opener_count: str = "2"
    target_profit_percent: str = "0"
    max_entries: str = "50"
    # Checkboxes sharing one `name` post as repeated form keys, which Form()
    # collects into a list the same way repeated query keys do. Defaults to
    # empty, not a suggested selection: an unchecked checkbox is omitted from
    # the POST entirely, so an empty default here is what lets "every box
    # unchecked" surface as SimulationForm's min_length=1 rejection instead
    # of silently falling back to some pre-picked set of strategies. The
    # simulator page's own suggested checked state lives in `DEFAULT_FORM`.
    strategies: list[str] = Field(default_factory=list)
    # Which submit button was pressed: "run" simulates and stores; "suggest"
    # only recomputes entry_1a/entry_1b from the target and re-renders the
    # form. Two buttons sharing one name, not a second endpoint — see
    # `web/pages.py`.
    action: str = "run"


class SimulationForm(BaseModel):
    """The browser form's shape.

    It differs from `SimulationCreate` in one respect: the payout is entered as a
    percentage, because that is how a broker quotes it. The conversion to a ratio
    happens here so the rest of the app only ever sees a ratio.
    """

    model_config = ConfigDict(extra="ignore")

    capital: float
    payout_percent: float
    entry_1a: float = 5.0
    entry_1b: float = 5.0
    opener_count: int = Field(default=2, ge=1, le=2)
    target_profit_percent: float = 0.0
    max_entries: int = Field(default=50, ge=1, le=MAX_ENTRIES_CEILING)
    # No default: always comes from `RawSimulationForm`, which supplies the
    # key on every submission (empty when nothing was checked).
    strategies: list[str] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _ignore_second_opener_when_one(cls, data: object) -> object:
        """`entry_1b` is ignored server-side once one opener is requested —
        see `to_creates()` below. Dropping it here, rather than validating it,
        is what stops a blank or malformed leftover in a hidden field from
        rejecting a submission the reader never meant to fill in."""
        if isinstance(data, dict) and str(data.get("opener_count")) == "1":
            data = {k: v for k, v in data.items() if k != "entry_1b"}
        return data

    @property
    def target_profit(self) -> float:
        """The percentage resolved to an absolute dollar amount, capital as
        the reference point — the only form the domain ever sees."""
        return self.capital * self.target_profit_percent / 100

    def to_creates(self) -> list["SimulationCreate"]:
        """One `SimulationCreate` per selected strategy, sharing every other field."""
        return [
            SimulationCreate(
                capital=self.capital,
                entry_1a=self.entry_1a,
                entry_1b=self.entry_1b if self.opener_count == 2 else None,
                payout_ratio=self.payout_percent / 100,
                target_profit=self.target_profit,
                max_entries=self.max_entries,
                strategy=strategy,
            )
            for strategy in self.strategies
        ]


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
    payout_ratio: float
    strategy: str
    # Set only when this run was one of several strategies compared from a
    # single simulator submission; null for a standalone run and for every
    # run made through the JSON API, which submits one strategy at a time.
    run_group: UUID | None
    wall_hit: bool
    wall_required_stake: float | None
    wall_balance_available: float | None
    losses_survived: int


class SimulationRead(SimulationSummary):
    """A stored run in full, including every entry placed before the wall."""

    entry_1a: float
    entry_1b: float | None
    target_profit: float
    # Null unless target_profit was entered as a percentage of capital — the
    # only way the web form sets it. A run created through the JSON API with
    # an absolute target_profit carries no percentage, because none was
    # chosen.
    target_profit_percent: float | None
    max_entries: int
    entries: list[EntryRead]


class Problem(BaseModel):
    """RFC 9457 problem detail — the shape of every 4xx from the error seam."""

    model_config = ConfigDict(json_schema_extra={"contentMediaType": "application/problem+json"})

    type: str = "about:blank"
    title: str
    status: int
    detail: str
