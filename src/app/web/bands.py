"""Escalation bands for the results ladder, computed server-side.

Each row is banded by the share of the balance *available before that entry*
that its stake consumes. That is the honest ratio: a share of starting capital
understates the danger, because by the seventh entry the account is already
depleted — a $436 stake is 43.6% of the original $1,000 but 72.8% of the $599
actually left.

The template receives a band name and the share as a number. Colour only
reinforces what the printed share already says.
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


@dataclass(frozen=True)
class WallRow:
    """The entry that could not be placed. Not a data row, and not styled as one."""

    required_stake: float
    balance_available: float
    share: float


def _row(
    label: str, stake: float, cumulative_loss: float, balance: float, balance_if_win: float
) -> LadderRow:
    balance_before = balance + stake
    share = stake / balance_before if balance_before else 1.0
    return LadderRow(
        label=label,
        stake=stake,
        cumulative_loss=cumulative_loss,
        balance=balance,
        balance_if_win=balance_if_win,
        share=share,
        band=band_for(share),
    )


def _wall(required: float | None, available: float | None) -> WallRow | None:
    if required is None or available is None:
        return None
    return WallRow(
        required_stake=required,
        balance_available=available,
        share=required / available if available else 1.0,
    )


def ladder(entries: Sequence[SimulationEntry]) -> list[LadderRow]:
    return [_row(e.label, e.stake, e.cumulative_loss, e.balance, e.balance_if_win) for e in entries]


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


# The published reference case. The landing page renders it by running the
# simulator, so the worked example can never drift from what the tool produces.
REFERENCE_CONFIG = StakingConfig(capital=1000.0, entry_1a=5.0, entry_1b=5.0, payout_ratio=0.92)


def worked_example(strategy: str = "adder_profit") -> tuple[list[LadderRow], WallRow | None]:
    """The reference case, run under any strategy — same capital and openers,
    so the landing page can show more than one method side by side."""
    table = StakingTable.build(replace(REFERENCE_CONFIG, strategy=strategy))
    rows = [
        _row(r.label, r.stake, r.cumulative_loss, r.balance, r.balance_if_win) for r in table.rows
    ]
    return rows, _wall(table.wall_required_stake, table.wall_balance_available)
