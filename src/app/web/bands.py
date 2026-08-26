"""Escalation bands for the results ladder, computed server-side.

Each row is banded by the share of the balance *available before that entry*
that its stake consumes. That is the honest ratio: a share of starting capital
understates the danger, because by the seventh entry the account is already
depleted — a $436 stake is 43.6% of the original $1,000 but 72.8% of the $599
actually left.

The template receives a band name and the share as a number. Colour only
reinforces what the printed share already says.
"""

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
