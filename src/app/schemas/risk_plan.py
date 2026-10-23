"""Transport contracts for the risk planner.

As with the simulator, these carry types and request shape only. Every rule —
the target above capital, the date range, the payout, the risk levels — lives
in `RiskPlanConfig.__post_init__`, and a second copy here would drift from it.

`RiskPlanRead` is the view model both surfaces render: the API returns it and
the `/planner` page reads the same object, so verdict wording and its band are
decided once, in `services/risk_planner.py`.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# How a risk level's verdict reads. `steep` is a required win share more than
# ten points above break-even; `out_of_reach` needs more wins than units exist.
VerdictBand = Literal["within", "steep", "out_of_reach"]

DEFAULT_WEEKDAYS = [0, 1, 2, 3, 4]


class RiskPlanQuery(BaseModel):
    """A capital target to plan for. Dates default to today and 30 days on."""

    model_config = ConfigDict(extra="forbid")

    capital: float
    target_capital: float
    start_date: date | None = None
    end_date: date | None = None
    # Mon=0 … Sun=6. Repeated query keys: `weekdays=0&weekdays=1`.
    weekdays: list[int] = Field(default_factory=lambda: list(DEFAULT_WEEKDAYS))
    per_day: int = 4
    payout_percent: float = 92.0
    # "trade" or "session"; an unknown name is the domain's refusal, not a Literal here.
    style: str = "session"
    risk_percents: list[float] = Field(default_factory=lambda: [0.25, 0.5, 1.0])


class RawPlannerForm(BaseModel):
    """Exactly what the planner's GET form sent, kept as text so a refused
    query re-renders with the reader's own values in the inputs."""

    model_config = ConfigDict(extra="ignore")

    capital: str = ""
    target_capital: str = ""
    start_date: str = ""
    end_date: str = ""
    payout_percent: str = ""
    style: str = ""
    per_day: str = ""
    # An unchecked box is absent from the query, so "none checked" arrives as
    # an empty list and reaches the domain's `weekdays` refusal.
    weekdays: list[str] = Field(default_factory=list)
    risk_1: str = ""
    risk_2: str = ""
    risk_3: str = ""
    risk_4: str = ""


RISK_FIELDS = ("risk_1", "risk_2", "risk_3", "risk_4")


class PlannerForm(BaseModel):
    """The planner form's shape: four risk inputs, of which only the first is
    required, and dates that may be left blank."""

    model_config = ConfigDict(extra="ignore")

    capital: float
    target_capital: float
    start_date: date | None = None
    end_date: date | None = None
    payout_percent: float
    style: str
    per_day: int
    weekdays: list[int]
    risk_1: float
    risk_2: float | None = None
    risk_3: float | None = None
    risk_4: float | None = None

    @field_validator("start_date", "end_date", "risk_2", "risk_3", "risk_4", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        return None if value == "" else value

    def to_query(self) -> tuple[RiskPlanQuery, list[str]]:
        """The form in the API's shape, plus the input each risk came from —
        `risk_percents[i]` was typed into `fields[i]`, so a refused level can
        be pointed at its own input."""
        filled = [(name, getattr(self, name)) for name in RISK_FIELDS]
        filled = [(name, value) for name, value in filled if value is not None]
        query = RiskPlanQuery(
            capital=self.capital,
            target_capital=self.target_capital,
            start_date=self.start_date,
            end_date=self.end_date,
            weekdays=self.weekdays,
            per_day=self.per_day,
            payout_percent=self.payout_percent,
            style=self.style,
            risk_percents=[value for _, value in filled],
        )
        return query, [name for name, _ in filled]


class PlanDayRead(BaseModel):
    number: int
    date: date
    start_balance: float
    target_balance: float
    profit: float


class RiskLevelRead(BaseModel):
    """One risk level's answer. Percentages are percentages (0.93 means 0.93%).

    For sessions, `wins_needed` and every headline figure assume each win
    comes on the recharge (the worst case); `wins_needed_best` assumes each
    comes on the initial trade. For single trades the two are equal.
    """

    risk_percent: float
    # The opening trade, or a session's initial; `recharge` is null for trades.
    stake: float
    recharge: float | None
    win_gain_percent: float
    win_gain_best_percent: float
    loss_percent: float
    breakeven_percent: float
    wins_needed: int
    wins_needed_best: int
    units: int
    required_percent: float
    wins_per_day: int
    per_day: int
    reachable: bool
    balance_if_all_win: float
    band: VerdictBand
    verdict: str


class RiskPlanRead(BaseModel):
    capital: float
    target_capital: float
    start_date: date
    end_date: date
    weekdays: list[int]
    per_day: int
    payout_percent: float
    style: str
    trading_days: int
    units: int
    first_day: date
    last_day: date
    total_growth_percent: float
    daily_growth_percent: float
    unit_growth_percent: float
    day_one_profit: float
    levels: list[RiskLevelRead]
    days: list[PlanDayRead]
