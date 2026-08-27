"""ORM mappings for a stored simulation and its entry ladder.

Two tables rather than one: the ladder is a child table, not a JSON blob, so the
schema behaves the same on SQLite, PostgreSQL, and MySQL.
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..models.base import Base, TimestampMixin, UtcDateTime


class Simulation(Base, TimestampMixin):
    """One run of the staking plan, stored with the inputs that produced it."""

    __tablename__ = "simulations"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Shared by every row a single form submission produced when more than one
    # strategy was compared side by side. Null for a single-strategy run,
    # including every run made through the JSON API, which only ever submits
    # one strategy per request.
    run_group: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True, default=None)

    # Inputs.
    capital: Mapped[float]
    entry_1a: Mapped[float]
    entry_1b: Mapped[float]
    second_entry: Mapped[float | None]
    payout_ratio: Mapped[float]
    target_profit: Mapped[float]
    # Set only when target_profit was entered as a percentage of capital —
    # the web form's only mode. Null for a row from the JSON API, or any
    # row recorded before this existed: an absolute target_profit with no
    # percentage basis to record.
    target_profit_percent: Mapped[float | None] = mapped_column(default=None)
    max_entries: Mapped[int]
    # One of the STRATEGIES names in `domain.staking_simulator`. Server-side
    # default so the rows recorded before this method existed read as what
    # they actually were computed with — adder_profit.
    strategy: Mapped[str] = mapped_column(
        String(20), default="adder_profit", server_default="adder_profit"
    )

    # Outcome.
    wall_hit: Mapped[bool]
    wall_required_stake: Mapped[float | None]
    wall_balance_available: Mapped[float | None]
    losses_survived: Mapped[int]

    # Null means live; a timestamp means cleared. Nothing is ever deleted.
    deleted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)

    entries: Mapped[list["SimulationEntry"]] = relationship(
        back_populates="simulation",
        cascade="all, delete-orphan",
        order_by="SimulationEntry.position",
    )


class SimulationEntry(Base, TimestampMixin):
    """One rung of the ladder. Reachability follows the parent, so no `deleted_at`."""

    __tablename__ = "simulation_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Indexed explicitly: every read loads a ladder by its parent, and neither
    # SQLite nor PostgreSQL indexes a foreign key on its own.
    simulation_id: Mapped[int] = mapped_column(ForeignKey("simulations.id"), index=True)

    # Explicit ordering: SQLite happens to return rows by rowid, PostgreSQL
    # promises nothing.
    position: Mapped[int]
    label: Mapped[str] = mapped_column(String(8))
    stake: Mapped[float]
    cumulative_loss: Mapped[float]
    balance: Mapped[float]
    balance_if_win: Mapped[float]

    simulation: Mapped[Simulation] = relationship(back_populates="entries")
