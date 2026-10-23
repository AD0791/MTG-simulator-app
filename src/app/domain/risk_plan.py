"""
risk_plan.py

What daily growth a capital target requires over a date range, and how many
wins that requires at a given risk per trade or per session.

Every unit (a trade, or a session of a trade plus one recharge) risks the
same percentage of the balance as it stands, so outcomes multiply and their
order does not matter: after N units with W wins the balance is

  capital * (1 + w)**W * (1 - r)**(N - W)

That makes the answer deterministic -- no win rate, no probability -- in
keeping with the staking simulator's worst-case stance. The plan states what
a target requires. It never says whether anyone wins that often.

  trade    a win adds r * payout, a loss costs r
  session  initial r / 3, recharge 2r / 3 (double) only if the initial loses:
           win first     + r * payout / 3
           win recharge  + r * (2 * payout - 1) / 3   (the worst case)
           lose both     - r

RiskPlan.build(config) is the entry point, like StakingTable.build. Today's
date is the caller's business; nothing here reads the clock.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import FrozenSet, List, Optional, Tuple
import math

from .staking_simulator import InvalidStakingConfig, check_payout_ratio, risk_entry

STYLES = ("trade", "session")
MAX_SPAN_DAYS = 730
MAX_PER_DAY = 100
MAX_RISK_LEVELS = 4

# Float noise can leave 62.000000001 where the algebra says 62.
_EPSILON = 1e-9


class InvalidRiskLevel(InvalidStakingConfig):
    """A refused risk level, with its position in `risk_percents`.

    Still an InvalidStakingConfig with field "risk_percents", so the error
    seam treats it like any other refusal. `index` lets a form that collects
    the levels in separate inputs point at the one at fault; it is None when
    no single level is (too many of them).
    """

    def __init__(self, message: str, index: Optional[int] = None) -> None:
        super().__init__("risk_percents", message)
        self.index = index


def trading_days(start: date, end: date, weekdays: FrozenSet[int]) -> List[date]:
    """Every date in [start, end], both inclusive, whose weekday (Mon=0) is selected."""
    return [
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
        if (start + timedelta(days=offset)).weekday() in weekdays
    ]


def _ceil(x: float) -> int:
    return math.ceil(x - _EPSILON)


def _cents(amount: Decimal) -> float:
    return float(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


@dataclass
class RiskPlanConfig:
    capital: float
    target_capital: float
    start: date
    end: date
    weekdays: FrozenSet[int] = frozenset(range(5))
    per_day: int = 4
    payout_ratio: float = 0.92
    style: str = "session"
    risk_percents: Tuple[float, ...] = (0.25, 0.5, 1.0)

    def __post_init__(self):
        # Each refusal names the field as the request calls it, so the error
        # seam and the form both point at the right input.
        if self.capital <= 0:
            raise InvalidStakingConfig("capital", "Capital must be more than $0.")
        if self.target_capital <= self.capital:
            raise InvalidStakingConfig(
                "target_capital", "The target must be more than your capital."
            )
        if not self.weekdays or not self.weekdays <= frozenset(range(7)):
            raise InvalidStakingConfig("weekdays", "Choose at least one trading day of the week.")
        if self.end < self.start:
            raise InvalidStakingConfig("end_date", "The end date must be on or after the start date.")
        if (self.end - self.start).days > MAX_SPAN_DAYS:
            raise InvalidStakingConfig(
                "end_date", f"The end date must be at most {MAX_SPAN_DAYS} days after the start."
            )
        if not trading_days(self.start, self.end, self.weekdays):
            raise InvalidStakingConfig(
                "end_date", "The dates must include at least one of the chosen weekdays."
            )
        if not 1 <= self.per_day <= MAX_PER_DAY:
            raise InvalidStakingConfig(
                "per_day", f"Enter a whole number from 1 to {MAX_PER_DAY}."
            )
        try:
            check_payout_ratio(self.payout_ratio)
        except InvalidStakingConfig as exc:
            raise InvalidStakingConfig(
                "payout_percent", "Payout must be above 0% and no more than 100%."
            ) from exc
        if self.style not in STYLES:
            raise InvalidStakingConfig("style", f"Style must be one of {', '.join(STYLES)}.")
        if self.style == "session" and self.payout_ratio <= 0.5:
            # A recharge doubles the initial, so its win nets 2 * payout - 1
            # of it: at 50% or less the worst-case win gains nothing.
            raise InvalidStakingConfig(
                "payout_percent", "A session needs a payout above 50%: below it, a recharge win gains nothing."
            )
        if not 1 <= len(self.risk_percents) <= MAX_RISK_LEVELS:
            raise InvalidRiskLevel(f"Give 1 to {MAX_RISK_LEVELS} risk levels.")
        for index, risk in enumerate(self.risk_percents):
            if not 0 < risk < 100:
                raise InvalidRiskLevel("Risk must be above 0% and below 100%.", index)
            if risk in self.risk_percents[:index]:
                raise InvalidRiskLevel("Each risk level must be different.", index)


@dataclass
class PlanDay:
    number: int
    date: date
    start_balance: float
    target_balance: float
    profit: float


@dataclass
class RiskLevel:
    risk_percent: float
    win_gain: float               # worst case for a session
    win_gain_best: float          # equal to win_gain for single trades
    loss: float
    breakeven_share: float
    wins_needed: int              # worst case for a session
    wins_needed_best: int
    units: int
    wins_per_day: int
    reachable: bool
    balance_if_all_win: float     # every unit won, worst case
    stake: float                  # the opening trade, or a session's initial
    recharge: Optional[float]     # a session's recharge; None for trades


@dataclass
class RiskPlan:
    config: RiskPlanConfig
    days: List[PlanDay] = field(default_factory=list)
    daily_growth: float = 0.0
    unit_growth: float = 0.0
    total_growth: float = 0.0
    levels: List[RiskLevel] = field(default_factory=list)

    @classmethod
    def build(cls, config: RiskPlanConfig) -> "RiskPlan":
        dates = trading_days(config.start, config.end, config.weekdays)
        ratio = config.target_capital / config.capital
        d = len(dates)
        n = d * config.per_day
        daily = ratio ** (1 / d) - 1

        plan = cls(
            config=config,
            daily_growth=daily,
            unit_growth=ratio ** (1 / n) - 1,
            total_growth=ratio - 1,
        )
        for number, day in enumerate(dates, start=1):
            start_balance = config.capital * (1 + daily) ** (number - 1)
            target_balance = config.capital * (1 + daily) ** number
            plan.days.append(
                PlanDay(number, day, start_balance, target_balance, target_balance - start_balance)
            )
        for index, risk_percent in enumerate(config.risk_percents):
            plan.levels.append(_level(config, index, risk_percent, n, ratio, daily))
        return plan


def _level(
    config: RiskPlanConfig, index: int, risk_percent: float, n: int, ratio: float, daily: float
) -> RiskLevel:
    r = risk_percent / 100
    p = config.payout_ratio
    if config.style == "trade":
        gain = gain_best = r * p
    else:
        gain, gain_best = r * (2 * p - 1) / 3, r * p / 3

    ln_loss = math.log(1 - r)

    def wins(target_ln: float, units: int, w: float) -> int:
        return _ceil((target_ln - units * ln_loss) / (math.log(1 + w) - ln_loss))

    wins_needed = wins(math.log(ratio), n, gain)
    stake, recharge = _stakes(config, index, risk_percent)
    return RiskLevel(
        risk_percent=risk_percent,
        win_gain=gain,
        win_gain_best=gain_best,
        loss=r,
        breakeven_share=-ln_loss / (math.log(1 + gain) - ln_loss),
        wins_needed=wins_needed,
        wins_needed_best=wins(math.log(ratio), n, gain_best),
        units=n,
        wins_per_day=wins(math.log(1 + daily), config.per_day, gain),
        reachable=wins_needed <= n,
        balance_if_all_win=config.capital * (1 + gain) ** n,
        stake=stake,
        recharge=recharge,
    )


def _stakes(
    config: RiskPlanConfig, index: int, risk_percent: float
) -> Tuple[float, Optional[float]]:
    """The opening stake in dollars at the starting capital -- display only;
    the growth maths stays fractional."""
    try:
        entry = risk_entry(config.capital, risk_percent)
    except InvalidStakingConfig as exc:
        raise InvalidRiskLevel("This risk is too small to size a stake of at least $0.01.", index) from exc
    if config.style == "trade":
        return entry, None
    initial = _cents(Decimal(str(entry)) / 3)
    if initial <= 0:
        raise InvalidRiskLevel("This risk is too small to size a session of at least $0.01.", index)
    return initial, round(2 * initial, 2)


if __name__ == "__main__":
    reference = RiskPlan.build(
        RiskPlanConfig(
            capital=1600,
            target_capital=2000,
            start=date(2026, 10, 23),
            end=date(2026, 11, 25),
            risk_percents=(0.5, 1.0),
        )
    )
    print(f"{len(reference.days)} trading days, daily growth {reference.daily_growth:.4%}")
    for level in reference.levels:
        verdict = "reachable" if level.reachable else "out of reach"
        print(
            f"  {level.risk_percent}%: wins {level.wins_needed}/{level.wins_needed_best}"
            f" of {level.units}, break-even {level.breakeven_share:.2%}, {verdict}"
        )
