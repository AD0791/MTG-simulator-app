"""Escalation bands for the results ladder, computed server-side.

Two independent bands, each on its own cell — never combined into one row
tint. The stake cell is banded by **exposure**: the share of the balance
*available before that entry* that its stake consumes. That answers "how big
is this bet against what's left?" A share of starting capital understates the
danger, because by the seventh entry the account is already depleted — a $436
stake is 43.6% of the original $1,000 but 72.8% of the $599 actually left.

The balance cell is banded by **drawdown**: `cumulative_loss / capital`, how
much of the account is already gone. Exposure and drawdown diverge exactly
where it matters — a row can read "elevated" on exposure while the account is
down past half. The drawdown ramp only starts at 50%, the point where
recovering costs more than the loss did, so a typical ladder stays uncoloured
until abruptly, near the wall, it isn't.

The template receives band names and the raw numbers. Colour only reinforces
what the printed figures already say.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

from ..domain.staking_simulator import StakingConfig, StakingTable
from ..models import Simulation, SimulationEntry

# Lower bound of each band, highest first.
BANDS = (
    (0.50, "danger"),
    (0.25, "elevated"),
    (0.10, "caution"),
)

# The drawdown ramp starts at 50% — below it, no band at all (the cell is
# left uncoloured). Recovering a drawdown needs a *larger* gain than the loss
# that caused it, so the thresholds are spaced across `gain = drawdown / (1 -
# drawdown)`, not evenly: 50% needs +100%, 90% needs +900%.
DRAWDOWN_BANDS = (
    (0.90, "terminal"),
    (0.80, "critical"),
    (0.65, "severe"),
    (0.50, "heavy"),
)

# Reader-facing names for the STRATEGIES keys in `domain.staking_simulator`.
STRATEGY_LABELS = {
    "adder_breakeven": "Breakeven recovery",
    "adder_profit": "Profit recovery",
    "double": "Double",
}


def band_for(share: float) -> str:
    for threshold, name in BANDS:
        if share >= threshold:
            return name
    return "calm"


def drawdown_band_for(drawdown: float) -> str | None:
    """None below 50% — the cell stays uncoloured, not just "calm"; colour
    below the floor would be crying wolf, per the roadmap's own framing."""
    for threshold, name in DRAWDOWN_BANDS:
        if drawdown >= threshold:
            return name
    return None


def recovery_gain(drawdown: float) -> float | None:
    """The gain required to recover a drawdown — `drawdown / (1 - drawdown)`.
    None at a 100% drawdown (balance hit exactly zero): the ratio is
    undefined, not merely large, and the domain's own wall check means this
    is the only way a placed entry's drawdown ever reaches 1.0.
    """
    if drawdown >= 1.0:
        return None
    return drawdown / (1 - drawdown)


@dataclass(frozen=True)
class LadderRow:
    """One entry, prepared for display."""

    label: str
    stake: float
    cumulative_loss: float
    balance: float
    balance_if_win: float
    share: float
    band: str
    drawdown: float
    drawdown_band: str | None
    recovery_gain: float | None


@dataclass(frozen=True)
class WallRow:
    """The entry that could not be placed. Not a data row, and not styled as one."""

    required_stake: float
    balance_available: float
    share: float


def _row(
    label: str,
    stake: float,
    cumulative_loss: float,
    balance: float,
    balance_if_win: float,
    capital: float,
) -> LadderRow:
    balance_before = balance + stake
    share = stake / balance_before if balance_before else 1.0
    drawdown = cumulative_loss / capital if capital else 1.0
    return LadderRow(
        label=label,
        stake=stake,
        cumulative_loss=cumulative_loss,
        balance=balance,
        balance_if_win=balance_if_win,
        share=share,
        band=band_for(share),
        drawdown=drawdown,
        drawdown_band=drawdown_band_for(drawdown),
        recovery_gain=recovery_gain(drawdown),
    )


def _wall(required: float | None, available: float | None) -> WallRow | None:
    if required is None or available is None:
        return None
    return WallRow(
        required_stake=required,
        balance_available=available,
        share=required / available if available else 1.0,
    )


def ladder(entries: Sequence[SimulationEntry], capital: float) -> list[LadderRow]:
    return [
        _row(e.label, e.stake, e.cumulative_loss, e.balance, e.balance_if_win, capital)
        for e in entries
    ]


def wall(simulation: Simulation) -> WallRow | None:
    """The wall row, or None when the ladder ran to `max_entries` intact."""
    if not simulation.wall_hit:
        return None
    return _wall(simulation.wall_required_stake, simulation.wall_balance_available)


@dataclass(frozen=True)
class OpenerBadge:
    """What happens if `entry_1a` and `entry_1b` both win — the ordinary case,
    shown beside the ladder's worst case. Identical for every strategy: the
    openers are shared inputs and neither has acted before the streak starts,
    so nothing about how later stakes are sized has had a chance to matter yet.
    """

    profit: float
    balance: float
    target: float | None  # None when no target profit is set
    meets_target: bool | None  # None when `target` is None


def opener_badge(
    capital: float, entry_1a: float, entry_1b: float, payout_ratio: float, target_profit: float
) -> OpenerBadge:
    profit = round((entry_1a + entry_1b) * payout_ratio, 2)
    target = target_profit if target_profit > 0 else None
    return OpenerBadge(
        profit=profit,
        balance=round(capital + profit, 2),
        target=target,
        meets_target=(profit >= target) if target is not None else None,
    )


def suggested_opener(target_profit: float, payout_ratio: float) -> float | None:
    """The equal opener `entry_1a == entry_1b` that clears `target_profit` the
    moment both win: `a = b = ceil(target / (2 * payout))`.

    None when there is no target to clear — a zero or negative target derives
    a zero or negative opener, which the domain rightly rejects, so the form
    falls back to whatever the reader already typed rather than seizing it.
    """
    if target_profit <= 0:
        return None
    return math.ceil(target_profit / (2 * payout_ratio))


@dataclass(frozen=True)
class OpenerDerivation:
    """The worked arithmetic behind `suggested_opener`, laid out for the
    Suggest dialog: target, payout, divisor, the exact quotient before
    rounding up, the opener, what both openers winning returns, and the
    surplus over the target the ceiling leaves."""

    target: float
    payout_ratio: float
    divisor: float
    exact: float
    opener: float
    returns: float
    surplus: float


def opener_derivation(target_profit: float, payout_ratio: float) -> OpenerDerivation | None:
    """The same rule as `suggested_opener`, shown rather than recomputed.

    `opener` comes from calling `suggested_opener` directly — this function
    only assembles the intermediate figures around that one result, so the
    dialog can never drift from the value the form actually uses. None
    exactly when `suggested_opener` is: a target of $0 or below derives no
    opener at all.
    """
    opener = suggested_opener(target_profit, payout_ratio)
    if opener is None:
        return None
    divisor = 2 * payout_ratio
    returns = round((opener + opener) * payout_ratio, 2)
    return OpenerDerivation(
        target=target_profit,
        payout_ratio=payout_ratio,
        divisor=divisor,
        exact=target_profit / divisor,
        opener=opener,
        returns=returns,
        surplus=round(returns - target_profit, 2),
    )


# The published reference case. The landing page renders it by running the
# simulator, so the worked example can never drift from what the tool produces.
REFERENCE_CONFIG = StakingConfig(capital=1000.0, entry_1a=5.0, entry_1b=5.0, payout_ratio=0.92)


def worked_example(strategy: str = "adder_profit") -> tuple[list[LadderRow], WallRow | None]:
    """The reference case, run under any strategy — same capital and openers,
    so the landing page can show more than one method side by side."""
    table = StakingTable.build(replace(REFERENCE_CONFIG, strategy=strategy))
    rows = [
        _row(
            r.label,
            r.stake,
            r.cumulative_loss,
            r.balance,
            r.balance_if_win,
            REFERENCE_CONFIG.capital,
        )
        for r in table.rows
    ]
    return rows, _wall(table.wall_required_stake, table.wall_balance_available)
