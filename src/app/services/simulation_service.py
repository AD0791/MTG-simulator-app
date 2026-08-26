"""Use cases: run a plan, store it, read it back, clear it.

Services receive a session and never create one, so a request is one
transaction. Each use case commits at its own end — not the router, and not per
mutation.

Domain rejections are not caught here. `StakingConfig` raises `ValueError` for an
invalid plan and that propagates to the single exception handler in `main.py`,
which is the one place a domain error becomes an HTTP response.
"""

from collections.abc import Sequence

from sqlalchemy.orm import Session, selectinload

from ..domain.staking_simulator import StakingConfig, StakingTable
from ..models import Simulation, SimulationEntry
from ..models.queries import live_simulations, soft_delete
from ..schemas import SimulationCreate


def run_and_store(session: Session, payload: SimulationCreate) -> Simulation:
    """Simulate the plan and persist the run with its full ladder."""
    config = StakingConfig(**payload.model_dump())
    table = StakingTable.build(config)

    simulation = Simulation(
        capital=config.capital,
        entry_1a=config.entry_1a,
        entry_1b=config.entry_1b,
        payout_ratio=config.payout_ratio,
        target_profit=config.target_profit,
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

    session.add(simulation)
    session.commit()
    return simulation


def get_simulation(session: Session, simulation_id: int) -> Simulation | None:
    """One live run with its ladder loaded, or None if it is absent or cleared."""
    statement = (
        live_simulations()
        .where(Simulation.id == simulation_id)
        .options(selectinload(Simulation.entries))
    )
    return session.scalars(statement).one_or_none()


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


def clear_all(session: Session) -> int:
    """Soft-delete every live run. Returns how many were cleared."""
    simulations = session.scalars(live_simulations()).all()
    for simulation in simulations:
        soft_delete(session, simulation)
    session.commit()
    return len(simulations)
