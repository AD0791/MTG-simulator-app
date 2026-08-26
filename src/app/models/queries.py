"""The shared read path for soft-deleted rows.

Every query that reads simulations starts from `live_simulations()`. The soft
delete pattern fails the moment one hand-written `select(Simulation)` forgets
the filter and starts returning cleared rows, so there is exactly one place the
filter lives.

An unfiltered select is legitimate only for inspection or restore — never for a
route or a service that answers a user's read.
"""

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from ..models.base import utcnow
from ..models.simulation import Simulation


def live_simulations() -> Select[tuple[Simulation]]:
    """Simulations that have not been cleared."""
    return select(Simulation).where(Simulation.deleted_at.is_(None))


def soft_delete(session: Session, simulation: Simulation) -> None:
    """Mark one simulation as cleared. Never issues DELETE."""
    simulation.deleted_at = utcnow()
    session.add(simulation)
