"""Transport contracts for the JSON API.

These carry types, required fields, and limits that protect the *server*. They
deliberately do **not** restate the domain's rules — capital must be positive, a
payout ratio must sit in (0, 1], a risk must give an entry above $0. Those live
in `StakingConfig.__post_init__`, which protects the calculation from every
caller, and a second copy here would drift from it.

`SimulationSummary` dropped `second_entry` from the v1 contract without cutting
a v2 (roadmap item 0) — the API had no external consumers, and the stored
column is kept nullable so already-recorded runs keep their data.

`strategies` on the form is a request-shape concern, not a domain one — the
domain only ever knows one strategy at a time (`StakingConfig.strategy`), so
"at least one strategy chosen" is policed here, in `Field(min_length=1)`, and
each individual name is left to the same domain rejection a bad payout gets.

Nobody types an opening entry. Every request carries `risk_percent`, and each
opener is `capital * risk_percent / 100` rounded to the cent — the domain's
`risk_entry`, applied once in `services/bands.config_for`. Whether a plan opens
with one entry or two is a request-shape concern too: `opener_count` resolves to
`entry_1b=None` there. `StakingConfig` never learns a "count" or a percentage
exists; it only ever sees the resolved amounts.

The read models are view models, not rows. Every ladder entry carries its
exposure and drawdown bands, and a run carries its wall share and opener badge —
classified once in `services/bands.py`, assembled in `services/presentation.py`
— so a client renders them and restates no threshold.

Every rejection under `/api/` is a `Problem`, whether the request was malformed
or the plan impossible, and `errors` names the fields at fault.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# A ceiling on the simulated ladder length. This is a request-shape constraint,
# not a domain rule: it bounds the work one request can ask the server to do.
MAX_ENTRIES_CEILING = 200

# The two colour ramps' vocabulary. Declared as part of the contract so a
# generated client sees unions, not strings; `services/bands.py` classifies
# into exactly these names.
Band = Literal["calm", "caution", "elevated", "danger"]
DrawdownBand = Literal["heavy", "severe", "critical", "terminal"]


class SimulationCreate(BaseModel):
    """A staking plan to simulate.

    Every field is optional; the defaults mirror `StakingConfig`'s, so a body
    need only carry what it changes.
    """

    model_config = ConfigDict(extra="forbid")

    capital: float = 1000.0
    # Each opening entry is this share of capital, rounded to the cent. 0.5% of
    # the default $1000 is the reference case's $5.
    risk_percent: float = 0.5
    opener_count: int = Field(default=2, ge=1, le=2)
    payout_ratio: float = 0.92
    max_entries: int = Field(default=50, ge=1, le=MAX_ENTRIES_CEILING)
    # One of STRATEGIES in `domain.staking_simulator`. Not constrained to a
    # Literal here — an unknown name is a domain rejection, same seam as an
    # impossible payout, not a second copy of the check.
    strategy: str = "adder_breakeven"


class RunGroupCreate(BaseModel):
    """One plan run under one or more strategies — a simulator submission as JSON.

    Two or more strategies share a `run_group` id; one strategy behaves exactly
    like `POST /simulations`.
    """

    model_config = ConfigDict(extra="forbid")

    capital: float = 1000.0
    risk_percent: float = 0.5
    opener_count: int = Field(default=2, ge=1, le=2)
    payout_ratio: float = 0.92
    max_entries: int = Field(default=50, ge=1, le=MAX_ENTRIES_CEILING)
    # Each name is left to the domain's rejection, same as `SimulationCreate.strategy`.
    strategies: list[str] = Field(min_length=1)

    def to_creates(self) -> list[SimulationCreate]:
        """One `SimulationCreate` per strategy, sharing every other field."""
        return [
            SimulationCreate(
                capital=self.capital,
                risk_percent=self.risk_percent,
                opener_count=self.opener_count,
                payout_ratio=self.payout_ratio,
                max_entries=self.max_entries,
                strategy=strategy,
            )
            for strategy in self.strategies
        ]


class RawSimulationForm(BaseModel):
    """Exactly what the browser posted, before any coercion.

    Kept as text so a rejected submission can be re-rendered with the reader's
    own values still in the inputs.
    """

    model_config = ConfigDict(extra="ignore")

    capital: str = ""
    payout_percent: str = ""
    risk_percent: str = "0.5"
    # "1" or "2" openers. A form concern resolved at the edge -- the domain
    # never learns a "count" exists, only ever `entry_1b` as `float | None`.
    opener_count: str = "2"
    max_entries: str = "50"
    # Checkboxes sharing one `name` post as repeated form keys, which Form()
    # collects into a list the same way repeated query keys do. Defaults to
    # empty, not a suggested selection: an unchecked checkbox is omitted from
    # the POST entirely, so an empty default here is what lets "every box
    # unchecked" surface as SimulationForm's min_length=1 rejection instead
    # of silently falling back to some pre-picked set of strategies. The
    # simulator page's own suggested checked state lives in `DEFAULT_FORM`.
    strategies: list[str] = Field(default_factory=list)


class SimulationForm(BaseModel):
    """The browser form's shape.

    It differs from `RunGroupCreate` in one respect: the payout is entered as a
    percentage, because that is how a broker quotes it. `to_plan()` resolves it,
    so the form and the JSON API reach the service through one conversion.
    """

    model_config = ConfigDict(extra="ignore")

    capital: float
    payout_percent: float
    risk_percent: float = 0.5
    opener_count: int = Field(default=2, ge=1, le=2)
    max_entries: int = Field(default=50, ge=1, le=MAX_ENTRIES_CEILING)
    # No default: always comes from `RawSimulationForm`, which supplies the
    # key on every submission (empty when nothing was checked).
    strategies: list[str] = Field(min_length=1)

    def to_plan(self) -> RunGroupCreate:
        """The form in the API's units: payout as a ratio."""
        return RunGroupCreate(
            capital=self.capital,
            risk_percent=self.risk_percent,
            opener_count=self.opener_count,
            payout_ratio=self.payout_percent / 100,
            max_entries=self.max_entries,
            strategies=self.strategies,
        )


class OpenerBadgeQuery(BaseModel):
    """What the opener badge reads.

    The openers are sized from `risk_percent` by the domain's own rule, so a
    capital or risk that sizes no entry is the same problem a plan gets. The
    payout is not checked — the badge is arithmetic on it, nothing more.
    """

    model_config = ConfigDict(extra="forbid")

    capital: float
    risk_percent: float
    opener_count: int = Field(default=2, ge=1, le=2)
    payout_ratio: float


class EntryRead(BaseModel):
    """One rung of the ladder, with every colour mark already classified.

    `share` is the stake against the balance available before it; `drawdown` is
    the cumulative loss against starting capital; `win_net` is what a win on
    this entry would leave against starting capital.
    """

    model_config = ConfigDict(from_attributes=True)

    position: int
    label: str
    stake: float
    cumulative_loss: float
    balance: float
    balance_if_win: float
    share: float
    band: Band
    drawdown: float
    # Null below a 50% drawdown — the balance cell stays uncoloured there.
    drawdown_band: DrawdownBand | None
    # Null at a 100% drawdown, where the gain needed to recover is undefined.
    recovery_gain: float | None
    # Signed: negative when a win on this entry still ends below starting capital.
    win_net: float
    # True on a derived entry whose win recovers the streak only in part — never
    # on an opener, never under an adder.
    short_recovery: bool


class FundingRead(BaseModel):
    """What the account must hold to absorb `losses` straight losses, and what
    that leaves of the capital to hold elsewhere."""

    model_config = ConfigDict(from_attributes=True)

    losses: int
    keep: float
    # Negative on the `wall` row: by how much covering it exceeds capital.
    elsewhere: float
    share: float
    # True on the last row only, when there is a wall: the entry the plan could
    # not place. The table stops there.
    wall: bool


class OpenerBadgeRead(BaseModel):
    """What every opener winning returns — the ordinary case beside the ladder's worst."""

    model_config = ConfigDict(from_attributes=True)

    profit: float
    balance: float
    opener_count: int


class StrategyRead(BaseModel):
    name: str
    label: str


class SimulationSummary(BaseModel):
    """A stored run as it appears in a listing — inputs and verdict, no ladder."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    capital: float
    payout_ratio: float
    strategy: str
    # Set only when this run was one of several strategies compared from a
    # single submission; null for a standalone run.
    run_group: UUID | None
    # The share of capital each opener was sized at. Null for a run recorded
    # before openers were sized this way, when they were typed by hand.
    risk_percent: float | None
    wall_hit: bool
    wall_required_stake: float | None
    wall_balance_available: float | None
    losses_survived: int


class SimulationRead(SimulationSummary):
    """A stored run in full, including every entry placed before the wall."""

    entry_1a: float
    entry_1b: float | None
    max_entries: int
    # `required ÷ available` at the wall; null when the ladder ran to its cap.
    wall_share: float | None
    opener_badge: OpenerBadgeRead
    entries: list[EntryRead]
    # The balance to keep in the account for each number of losses covered.
    funding: list[FundingRead]


class LadderRead(BaseModel):
    """A plan simulated without being stored — the verdict and ladder a stored
    run carries, and nothing that identifies or lists it."""

    capital: float
    risk_percent: float
    opener_count: int
    # The openers `risk_percent` resolved to; `entry_1b` is null with one opener.
    entry_1a: float
    entry_1b: float | None
    payout_ratio: float
    max_entries: int
    strategy: str
    wall_hit: bool
    wall_required_stake: float | None
    wall_balance_available: float | None
    wall_share: float | None
    losses_survived: int
    opener_badge: OpenerBadgeRead
    entries: list[EntryRead]
    funding: list[FundingRead]


class RunGroupRead(BaseModel):
    """Every run from one submission, in the order its strategies were given.

    `run_group` is null when one strategy was run — there is nothing to compare,
    and the run is read at `/simulations/{id}` like any other.
    """

    run_group: UUID | None
    simulations: list[SimulationRead]


class FieldError(BaseModel):
    """One field at fault. For a malformed request, `field` is the request's own
    field name; for an impossible plan, the `StakingConfig` field the domain
    refused."""

    field: str
    detail: str


class Problem(BaseModel):
    """RFC 9457 problem detail — the shape of every 4xx from the error seam."""

    model_config = ConfigDict(json_schema_extra={"contentMediaType": "application/problem+json"})

    type: str = "about:blank"
    title: str
    status: int
    detail: str
    # An RFC 9457 extension member. Empty when the problem is not about a field.
    errors: list[FieldError] = Field(default_factory=list)
