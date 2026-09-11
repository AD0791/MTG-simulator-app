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
precedent as `payout_percent` — resolved to an absolute dollar amount before the
domain sees it. `SimulationCreate` stays in absolute dollars: it is a direct
line to the domain's own units. `RunGroupCreate` takes the percentage, because
it is the JSON form of one simulator submission and history shows the
percentage back.

Whether a plan opens with one entry or two is likewise a request-shape
concern, not a domain one — `SimulationForm.opener_count` resolves to
`entry_1b=None` in `to_plan()` when one opener is chosen. `StakingConfig` never
learns a "count" exists; it only ever sees `entry_1b` as `float | None`.

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

from pydantic import BaseModel, ConfigDict, Field, model_validator

# A ceiling on the simulated ladder length. This is a request-shape constraint,
# not a domain rule: it bounds the work one request can ask the server to do.
MAX_ENTRIES_CEILING = 200

# The two colour ramps' vocabulary. Declared as part of the contract so a
# generated client sees unions, not strings; `services/bands.py` classifies
# into exactly these names.
Band = Literal["calm", "caution", "elevated", "danger"]
DrawdownBand = Literal["heavy", "severe", "critical", "terminal"]


def _percent_of(capital: float, percent: float) -> float:
    """A target entered as a percentage, resolved to dollars with capital as the
    reference point — the only form the domain ever sees."""
    return capital * percent / 100


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


class RunGroupCreate(BaseModel):
    """One plan run under one or more strategies — a simulator submission as JSON.

    Two or more strategies share a `run_group` id; one strategy behaves exactly
    like `POST /simulations`. The target is a percentage of capital, stored as
    provenance and resolved to dollars in `to_creates()`.
    """

    model_config = ConfigDict(extra="forbid")

    capital: float = 1000.0
    entry_1a: float = 5.0
    entry_1b: float | None = 5.0
    payout_ratio: float = 0.92
    target_profit_percent: float = 0.0
    max_entries: int = Field(default=50, ge=1, le=MAX_ENTRIES_CEILING)
    # Each name is left to the domain's rejection, same as `SimulationCreate.strategy`.
    strategies: list[str] = Field(min_length=1)

    @property
    def target_profit(self) -> float:
        return _percent_of(self.capital, self.target_profit_percent)

    @property
    def recorded_target_percent(self) -> float | None:
        """What a run stores as provenance: the percentage, only when one was chosen."""
        return self.target_profit_percent if self.target_profit_percent > 0 else None

    def to_creates(self) -> list[SimulationCreate]:
        """One `SimulationCreate` per strategy, sharing every other field."""
        return [
            SimulationCreate(
                capital=self.capital,
                entry_1a=self.entry_1a,
                entry_1b=self.entry_1b,
                payout_ratio=self.payout_ratio,
                target_profit=self.target_profit,
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

    It differs from `RunGroupCreate` in two respects: the payout is entered as a
    percentage, because that is how a broker quotes it, and the second opener is
    a count rather than a null. `to_plan()` resolves both, so the form and the
    JSON API reach the service through one conversion.
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
        see `to_plan()` below. Dropping it here, rather than validating it,
        is what stops a blank or malformed leftover in a hidden field from
        rejecting a submission the reader never meant to fill in."""
        if isinstance(data, dict) and str(data.get("opener_count")) == "1":
            data = {k: v for k, v in data.items() if k != "entry_1b"}
        return data

    @property
    def target_profit(self) -> float:
        return _percent_of(self.capital, self.target_profit_percent)

    def to_plan(self) -> RunGroupCreate:
        """The form in the API's units: payout as a ratio, a single opener as a null."""
        return RunGroupCreate(
            capital=self.capital,
            entry_1a=self.entry_1a,
            entry_1b=self.entry_1b if self.opener_count == 2 else None,
            payout_ratio=self.payout_percent / 100,
            target_profit_percent=self.target_profit_percent,
            max_entries=self.max_entries,
            strategies=self.strategies,
        )


class OpenerBadgeQuery(BaseModel):
    """What the opener badge reads. Omit `entry_1b` for a plan with one opener.

    No domain rule applies — the badge is arithmetic on whatever was typed, the
    same tolerance the form's live preview has.
    """

    model_config = ConfigDict(extra="forbid")

    capital: float
    entry_1a: float
    entry_1b: float | None = None
    payout_ratio: float
    target_profit_percent: float = 0.0

    @property
    def target_profit(self) -> float:
        return _percent_of(self.capital, self.target_profit_percent)


class OpenerSuggestionQuery(BaseModel):
    """What sizing the openers to a target reads."""

    model_config = ConfigDict(extra="forbid")

    capital: float
    # Not bounded here: the derivation applies the domain's own payout rule
    # before it divides, and an impossible payout reaches the same problem seam
    # as an impossible plan.
    payout_ratio: float
    target_profit_percent: float = 0.0
    opener_count: int = Field(default=2, ge=1, le=2)

    @property
    def target_profit(self) -> float:
        return _percent_of(self.capital, self.target_profit_percent)


class EntryRead(BaseModel):
    """One rung of the ladder, with both colour ramps already classified.

    `share` is the stake against the balance available before it; `drawdown` is
    the cumulative loss against starting capital.
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


class OpenerBadgeRead(BaseModel):
    """What every opener winning returns — the ordinary case beside the ladder's worst."""

    model_config = ConfigDict(from_attributes=True)

    profit: float
    balance: float
    # Null when no target profit is set; `meets_target` is null with it.
    target: float | None
    meets_target: bool | None
    opener_count: int


class OpenerDerivationRead(BaseModel):
    """The worked arithmetic behind a suggested opener, figure by figure."""

    model_config = ConfigDict(from_attributes=True)

    target: float
    payout_ratio: float
    opener_count: int
    divisor: float
    exact: float
    opener: float
    returns: float
    surplus: float


class OpenerSuggestionRead(BaseModel):
    # Null when there is no target above $0 to size the openers against.
    derivation: OpenerDerivationRead | None


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
    target_profit: float
    # Null unless target_profit was entered as a percentage of capital — through
    # the web form or `POST /run-groups`. A run created with an absolute
    # target_profit carries no percentage, because none was chosen.
    target_profit_percent: float | None
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


class LadderRead(BaseModel):
    """A plan simulated without being stored — the verdict and ladder a stored
    run carries, and nothing that identifies or lists it."""

    capital: float
    entry_1a: float
    entry_1b: float | None
    payout_ratio: float
    target_profit: float
    max_entries: int
    strategy: str
    wall_hit: bool
    wall_required_stake: float | None
    wall_balance_available: float | None
    wall_share: float | None
    losses_survived: int
    opener_badge: OpenerBadgeRead
    entries: list[EntryRead]


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
