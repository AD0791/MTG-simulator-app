"""The risk planner as both surfaces present it.

The one place a request becomes a `RiskPlanConfig`, and the one place a plan
becomes words. `GET /api/v1/risk-plans` and the `/planner` page both call
`plan_read`, so a verdict cannot read one way in JSON and another on screen.

Read path only — nothing is stored, so nothing here logs.
"""

from datetime import date, timedelta

from ..domain.risk_plan import RiskLevel, RiskPlan, RiskPlanConfig
from ..schemas.risk_plan import PlanDayRead, RiskLevelRead, RiskPlanQuery, RiskPlanRead, VerdictBand

DEFAULT_SPAN_DAYS = 30

# A required win share this far above break-even reads as steep.
STEEP_MARGIN_POINTS = 10.0


def default_dates(today: date) -> tuple[date, date]:
    return today, today + timedelta(days=DEFAULT_SPAN_DAYS)


def config_for(query: RiskPlanQuery, today: date) -> RiskPlanConfig:
    """The request in the domain's units. Blank dates are today and 30 days on."""
    default_start, default_end = default_dates(today)
    return RiskPlanConfig(
        capital=query.capital,
        target_capital=query.target_capital,
        start=query.start_date or default_start,
        end=query.end_date or default_end,
        weekdays=frozenset(query.weekdays),
        per_day=query.per_day,
        payout_ratio=query.payout_percent / 100,
        style=query.style,
        risk_percents=tuple(query.risk_percents),
    )


def plan_read(query: RiskPlanQuery, today: date) -> RiskPlanRead:
    plan = RiskPlan.build(config_for(query, today))
    config = plan.config
    return RiskPlanRead(
        capital=config.capital,
        target_capital=config.target_capital,
        start_date=config.start,
        end_date=config.end,
        weekdays=sorted(config.weekdays),
        per_day=config.per_day,
        payout_percent=query.payout_percent,
        style=config.style,
        trading_days=len(plan.days),
        units=len(plan.days) * config.per_day,
        first_day=plan.days[0].date,
        last_day=plan.days[-1].date,
        total_growth_percent=plan.total_growth * 100,
        daily_growth_percent=plan.daily_growth * 100,
        unit_growth_percent=plan.unit_growth * 100,
        day_one_profit=round(plan.days[0].profit, 2),
        levels=[_level_read(level, config.per_day) for level in plan.levels],
        days=[
            PlanDayRead(
                number=day.number,
                date=day.date,
                start_balance=round(day.start_balance, 2),
                target_balance=round(day.target_balance, 2),
                profit=round(day.profit, 2),
            )
            for day in plan.days
        ],
    )


def _level_read(level: RiskLevel, per_day: int) -> RiskLevelRead:
    required = level.wins_needed / level.units * 100
    breakeven = level.breakeven_share * 100
    band, verdict = _verdict(level, required, breakeven)
    return RiskLevelRead(
        risk_percent=level.risk_percent,
        stake=level.stake,
        recharge=level.recharge,
        win_gain_percent=level.win_gain * 100,
        win_gain_best_percent=level.win_gain_best * 100,
        loss_percent=level.loss * 100,
        breakeven_percent=breakeven,
        wins_needed=level.wins_needed,
        wins_needed_best=level.wins_needed_best,
        units=level.units,
        required_percent=required,
        wins_per_day=level.wins_per_day,
        per_day=per_day,
        reachable=level.reachable,
        balance_if_all_win=round(level.balance_if_all_win, 2),
        band=band,
        verdict=verdict,
    )


def _verdict(level: RiskLevel, required: float, breakeven: float) -> tuple[VerdictBand, str]:
    """What the target requires at this risk, in words that stand without colour.

    It states a requirement. It never says the target will be met, and never
    suggests a higher risk.
    """
    if not level.reachable:
        return (
            "out_of_reach",
            f"Out of reach at {level.risk_percent:g}%: even winning all {level.units} "
            f"ends at ${level.balance_if_all_win:,.2f}",
        )
    verdict = (
        f"Requires winning {level.wins_needed} of {level.units} ({required:.2f}%) "
        f"— break-even is {breakeven:.2f}%"
    )
    if required - breakeven > STEEP_MARGIN_POINTS:
        return "steep", f"{verdict}. Steep: {required - breakeven:.1f} points above break-even"
    return "within", verdict
