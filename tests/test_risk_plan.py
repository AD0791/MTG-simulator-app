"""Risk planner domain tests — the growth arithmetic, called directly.

The reference case: $1,600 to $2,000 from 2026-10-23 to 2026-11-25, Monday to
Friday, four units a day, at a 92% payout.
"""

from dataclasses import replace
from datetime import date

import pytest

from app.domain.risk_plan import (
    InvalidRiskLevel,
    RiskLevel,
    RiskPlan,
    RiskPlanConfig,
    trading_days,
)
from app.domain.staking_simulator import InvalidStakingConfig

START = date(2026, 10, 23)
END = date(2026, 11, 25)
WEEKDAYS = frozenset(range(5))


def _config(**overrides: object) -> RiskPlanConfig:
    values: dict[str, object] = {
        "capital": 1600.0,
        "target_capital": 2000.0,
        "start": START,
        "end": END,
        "weekdays": WEEKDAYS,
        "per_day": 4,
        "payout_ratio": 0.92,
        "style": "trade",
        "risk_percents": (1.0, 0.5, 0.25),
    }
    values.update(overrides)
    return RiskPlanConfig(**values)  # type: ignore[arg-type]


def _level(plan: RiskPlan, risk_percent: float) -> RiskLevel:
    return next(level for level in plan.levels if level.risk_percent == risk_percent)


def test_reference_case_has_24_trading_days_and_96_units() -> None:
    days = trading_days(START, END, WEEKDAYS)
    assert len(days) == 24
    assert days[0] == date(2026, 10, 23)
    assert days[-1] == date(2026, 11, 25)
    assert _level(RiskPlan.build(_config()), 1.0).units == 96


def test_reference_daily_growth_and_day_one() -> None:
    plan = RiskPlan.build(_config())
    assert plan.daily_growth * 100 == pytest.approx(0.9341, abs=1e-4)
    first = plan.days[0]
    assert (first.number, first.date) == (1, START)
    assert round(first.profit, 2) == 14.95
    assert round(first.target_balance, 2) == 1614.95
    assert plan.days[-1].target_balance == pytest.approx(2000.0)


def test_trade_at_one_percent() -> None:
    level = _level(RiskPlan.build(_config()), 1.0)
    assert level.wins_needed == level.wins_needed_best == 62
    assert level.wins_needed / level.units * 100 == pytest.approx(64.58, abs=0.01)
    assert level.breakeven_share * 100 == pytest.approx(52.32, abs=0.01)
    assert level.wins_per_day == 3
    assert level.reachable
    assert (level.stake, level.recharge) == (16.0, None)


def test_trade_at_half_a_percent() -> None:
    level = _level(RiskPlan.build(_config()), 0.5)
    assert level.wins_needed == 74
    assert level.wins_per_day == 4
    assert level.breakeven_share * 100 == pytest.approx(52.20, abs=0.01)
    assert level.reachable


def test_trade_at_a_quarter_percent_is_out_of_reach() -> None:
    level = _level(RiskPlan.build(_config()), 0.25)
    assert level.wins_needed == 97
    assert not level.reachable
    assert round(level.balance_if_all_win, 2) == 1994.81


def test_session_at_one_percent() -> None:
    level = _level(RiskPlan.build(_config(style="session")), 1.0)
    assert (level.wins_needed, level.wins_needed_best) == (93, 91)
    assert level.wins_per_day == 4
    assert level.breakeven_share * 100 == pytest.approx(78.23, abs=0.01)
    assert level.reachable
    assert (level.stake, level.recharge) == (5.33, 10.66)


def test_session_at_half_a_percent_is_out_of_reach() -> None:
    level = _level(RiskPlan.build(_config(style="session")), 0.5)
    assert (level.wins_needed, level.wins_needed_best) == (110, 108)
    assert not level.reachable
    assert round(level.balance_if_all_win, 2) == 1829.99


def test_all_seven_weekdays() -> None:
    plan = RiskPlan.build(_config(weekdays=frozenset(range(7))))
    assert len(plan.days) == 34
    assert plan.daily_growth * 100 == pytest.approx(0.6585, abs=1e-4)


def test_order_of_outcomes_does_not_matter() -> None:
    """The closed form the whole planner rests on: fractional sizing multiplies."""
    level = _level(RiskPlan.build(_config()), 1.0)
    wins, losses = level.wins_needed, level.units - level.wins_needed
    balance = 1600.0
    for _ in range(losses):
        balance *= 1 - level.loss
    for _ in range(wins):
        balance *= 1 + level.win_gain
    assert balance >= 2000.0
    # One fewer win falls short.
    assert balance / (1 + level.win_gain) * (1 - level.loss) < 2000.0


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"capital": 0.0}, "capital"),
        ({"target_capital": 1600.0}, "target_capital"),
        ({"target_capital": 1000.0}, "target_capital"),
        ({"end": date(2026, 10, 22)}, "end_date"),
        ({"end": date(2028, 10, 23)}, "end_date"),
        # A Saturday and a Sunday only, with Monday to Friday selected.
        ({"start": date(2026, 10, 24), "end": date(2026, 10, 25)}, "end_date"),
        ({"weekdays": frozenset()}, "weekdays"),
        ({"weekdays": frozenset({7})}, "weekdays"),
        ({"per_day": 0}, "per_day"),
        ({"per_day": 101}, "per_day"),
        ({"payout_ratio": 0.0}, "payout_percent"),
        ({"payout_ratio": 1.01}, "payout_percent"),
        ({"style": "session", "payout_ratio": 0.5}, "payout_percent"),
        ({"style": "martingale"}, "style"),
        ({"risk_percents": ()}, "risk_percents"),
        ({"risk_percents": (0.1, 0.2, 0.3, 0.4, 0.5)}, "risk_percents"),
        ({"risk_percents": (0.5, 0.5)}, "risk_percents"),
        ({"risk_percents": (0.0,)}, "risk_percents"),
        ({"risk_percents": (100.0,)}, "risk_percents"),
    ],
)
def test_every_refusal_names_the_request_field(overrides: dict[str, object], field: str) -> None:
    with pytest.raises(InvalidStakingConfig) as caught:
        _config(**overrides)
    assert caught.value.field == field


@pytest.mark.parametrize(
    ("risks", "index"),
    [((0.5, 0.5), 1), ((0.5, 0.0), 1), ((100.0,), 0), ((0.1, 0.2, 0.3, 0.4, 0.5), None)],
)
def test_a_refused_risk_level_knows_its_position(
    risks: tuple[float, ...], index: int | None
) -> None:
    with pytest.raises(InvalidRiskLevel) as caught:
        _config(risk_percents=risks)
    assert caught.value.index == index


def test_a_trade_at_fifty_percent_payout_still_runs() -> None:
    """Only sessions need a payout above 50%; a single trade's win always gains."""
    plan = RiskPlan.build(_config(payout_ratio=0.5))
    assert all(level.win_gain > 0 for level in plan.levels)


def test_a_risk_too_small_to_size_a_stake_is_refused_at_its_position() -> None:
    config = replace(_config(), capital=1.0, target_capital=2.0, risk_percents=(50.0, 0.1))
    with pytest.raises(InvalidRiskLevel) as caught:
        RiskPlan.build(config)
    assert caught.value.index == 1
