"""Runs as the JSON API presents them.

The API returns view models, not rows: every ladder entry carries its exposure
and drawdown bands, and a run carries its wall share and opener badge. Each
figure is classified by the same `bands` functions the HTML pages use, so a
client restates no threshold and the two surfaces cannot disagree.

Read paths only — nothing here writes, so nothing here logs.
"""

from collections.abc import Sequence
from dataclasses import asdict

from ..domain.staking_simulator import STRATEGIES, StakingConfig, StakingTable
from ..models import Simulation
from ..schemas import (
    EntryRead,
    LadderRead,
    OpenerBadgeQuery,
    OpenerBadgeRead,
    OpenerDerivationRead,
    OpenerSuggestionQuery,
    OpenerSuggestionRead,
    RunGroupRead,
    SimulationCreate,
    SimulationRead,
    SimulationSummary,
    StrategyRead,
)
from . import bands


def strategies() -> list[StrategyRead]:
    """Every strategy the simulator runs, in the order the form offers them."""
    return [
        StrategyRead(name=name, label=bands.STRATEGY_LABELS.get(name, name)) for name in STRATEGIES
    ]


def simulation_read(simulation: Simulation) -> SimulationRead:
    wall = bands.wall(simulation)
    rows = bands.ladder(simulation.entries, simulation.capital)
    return SimulationRead(
        **SimulationSummary.model_validate(simulation).model_dump(),
        entry_1a=simulation.entry_1a,
        entry_1b=simulation.entry_1b,
        max_entries=simulation.max_entries,
        wall_share=wall.share if wall is not None else None,
        opener_badge=_badge(
            simulation.capital,
            simulation.entry_1a,
            simulation.entry_1b,
            simulation.payout_ratio,
            simulation.target_profit,
        ),
        entries=[
            EntryRead(position=entry.position, **asdict(row))
            for entry, row in zip(simulation.entries, rows, strict=True)
        ],
    )


def run_group_read(simulations: Sequence[Simulation]) -> RunGroupRead:
    """One submission's runs. Callers pass at least one — a group is never empty."""
    return RunGroupRead(
        run_group=simulations[0].run_group,
        simulations=[simulation_read(simulation) for simulation in simulations],
    )


def ladder_read(plan: SimulationCreate) -> LadderRead:
    """Simulate without storing. An impossible plan raises, same seam as a stored one."""
    config = StakingConfig(**plan.model_dump())
    table = StakingTable.build(config)
    rows, wall = bands.table_ladder(table)
    return LadderRead(
        **plan.model_dump(),
        wall_hit=table.wall_hit,
        wall_required_stake=table.wall_required_stake,
        wall_balance_available=table.wall_balance_available,
        wall_share=wall.share if wall is not None else None,
        losses_survived=table.losses_survived,
        opener_badge=_badge(
            config.capital,
            config.entry_1a,
            config.entry_1b,
            config.payout_ratio,
            config.target_profit,
        ),
        entries=[
            EntryRead(position=position, **asdict(row))
            for position, row in enumerate(rows, start=1)
        ],
    )


def opener_badge_read(query: OpenerBadgeQuery) -> OpenerBadgeRead:
    return _badge(
        query.capital, query.entry_1a, query.entry_1b, query.payout_ratio, query.target_profit
    )


def opener_suggestion_read(query: OpenerSuggestionQuery) -> OpenerSuggestionRead:
    derivation = bands.opener_derivation(
        query.target_profit, query.payout_ratio, query.opener_count
    )
    return OpenerSuggestionRead(
        derivation=OpenerDerivationRead.model_validate(derivation) if derivation else None
    )


def _badge(
    capital: float,
    entry_1a: float,
    entry_1b: float | None,
    payout_ratio: float,
    target_profit: float,
) -> OpenerBadgeRead:
    return OpenerBadgeRead.model_validate(
        bands.opener_badge(capital, entry_1a, entry_1b, payout_ratio, target_profit)
    )
