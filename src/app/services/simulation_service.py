"""Use cases: run a plan, store it, read it back, clear it.

Services receive a session and never create one, so a request is one
transaction. Each use case commits at its own end — not the router, and not per
mutation.

Domain rejections are not caught here. `StakingConfig` raises `ValueError` for an
invalid plan and that propagates to the single exception handler in `main.py`,
which is the one place a domain error becomes an HTTP response.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy.orm import Session, selectinload

from ..domain.staking_simulator import StakingConfig, StakingTable
from ..models import Simulation, SimulationEntry
from ..models.queries import live_simulations, soft_delete
from ..schemas import SimulationCreate


def _build_simulation(
    config: StakingConfig,
    table: StakingTable,
    run_group: uuid.UUID | None,
    target_profit_percent: float | None = None,
) -> Simulation:
    return Simulation(
        run_group=run_group,
        capital=config.capital,
        entry_1a=config.entry_1a,
        entry_1b=config.entry_1b,
        payout_ratio=config.payout_ratio,
        target_profit=config.target_profit,
        target_profit_percent=target_profit_percent,
        max_entries=config.max_entries,
        strategy=config.strategy,
        wall_hit=table.wall_hit,
        wall_required_stake=table.wall_required_stake,
        wall_balance_available=table.wall_balance_available,
        losses_survived=table.losses_survived,
        entries=[
            SimulationEntry(
                position=position,
                label=row.label,
                stake=row.stake,
                cumulative_loss=row.cumulative_loss,
                balance=row.balance,
                balance_if_win=row.balance_if_win,
            )
            for position, row in enumerate(table.rows, start=1)
        ],
    )


def run_and_store(
    session: Session, payload: SimulationCreate, target_profit_percent: float | None = None
) -> Simulation:
    """Simulate one plan and persist the run with its full ladder.

    `target_profit_percent` is provenance only — the web form's record of
    what the reader actually typed — not a `SimulationCreate` field. A direct
    JSON API caller sends an absolute `target_profit` and leaves this unset,
    which is the truth for that call: no percentage was chosen.
    """
    config = StakingConfig(**payload.model_dump())
    table = StakingTable.build(config)
    simulation = _build_simulation(
        config, table, run_group=None, target_profit_percent=target_profit_percent
    )

    session.add(simulation)
    session.commit()
    return simulation


def run_and_store_group(
    session: Session,
    payloads: Sequence[SimulationCreate],
    target_profit_percent: float | None = None,
) -> list[Simulation]:
    """Simulate every strategy from one form submission and persist them together.

    Every `StakingConfig` is built — and can raise, same as `run_and_store` —
    before any row is added, so a rejection leaves nothing half-written. A
    shared `run_group` id is assigned only when there is more than one
    strategy to compare; a single selection behaves exactly like
    `run_and_store`. One `target_profit_percent` for the whole group: it's a
    shared input, same as capital or the openers, not per-strategy.
    """
    group_id = uuid.uuid4() if len(payloads) > 1 else None

    # Every config is built first — and can raise here, before any row exists —
    # so a rejection never leaves a partial group behind.
    configs = [StakingConfig(**payload.model_dump()) for payload in payloads]
    simulations = [
        _build_simulation(
            config,
            StakingTable.build(config),
            run_group=group_id,
            target_profit_percent=target_profit_percent,
        )
        for config in configs
    ]

    session.add_all(simulations)
    session.commit()
    return simulations


def get_simulation(session: Session, simulation_id: int) -> Simulation | None:
    """One live run with its ladder loaded, or None if it is absent or cleared."""
    statement = (
        live_simulations()
        .where(Simulation.id == simulation_id)
        .options(selectinload(Simulation.entries))
    )
    return session.scalars(statement).one_or_none()


def get_group(session: Session, run_group: uuid.UUID) -> Sequence[Simulation]:
    """Every live run from one multi-strategy comparison, oldest first.

    Oldest first, not `losses_survived` order: the group was submitted as one
    ladder per checked strategy, and the reader's checkbox order is what the
    result should walk back to.
    """
    statement = (
        live_simulations()
        .where(Simulation.run_group == run_group)
        .options(selectinload(Simulation.entries))
        .order_by(Simulation.id.asc())
    )
    return session.scalars(statement).all()


def list_simulations(session: Session, limit: int = 100) -> Sequence[Simulation]:
    """Live runs, newest first."""
    statement = live_simulations().order_by(Simulation.id.desc()).limit(limit)
    return session.scalars(statement).all()


def clear_simulation(session: Session, simulation_id: int) -> bool:
    """Soft-delete one run. False if it was already absent or cleared."""
    simulation = session.scalars(
        live_simulations().where(Simulation.id == simulation_id)
    ).one_or_none()
    if simulation is None:
        return False

    soft_delete(session, simulation)
    session.commit()
    return True


def clear_group(session: Session, run_group: uuid.UUID) -> int:
    """Soft-delete every live run in one comparison group. Returns how many."""
    simulations = session.scalars(live_simulations().where(Simulation.run_group == run_group)).all()
    for simulation in simulations:
        soft_delete(session, simulation)
    session.commit()
    return len(simulations)


def clear_all(session: Session) -> int:
    """Soft-delete every live run. Returns how many were cleared."""
    simulations = session.scalars(live_simulations()).all()
    for simulation in simulations:
        soft_delete(session, simulation)
    session.commit()
    return len(simulations)
