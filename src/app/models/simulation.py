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
    # Null means one opener, labelled "1" rather than "1a"/"1b" (roadmap item C).
    entry_1b: Mapped[float | None]
    second_entry: Mapped[float | None]
    payout_ratio: Mapped[float]
    # The share of capital each opener was sized at: entry_1a (and entry_1b,
    # when there is one) = capital * risk_percent / 100, rounded to the cent.
    # Null for a row recorded before openers were sized this way.
    risk_percent: Mapped[float | None] = mapped_column(default=None)
    # Legacy, no longer written: the target profit that drove the removed
    # adder_profit strategy. Kept nullable, like second_entry, so stored rows
    # keep their data.
    target_profit: Mapped[float | None] = mapped_column(default=None)
    target_profit_percent: Mapped[float | None] = mapped_column(default=None)
    max_entries: Mapped[int]
    # One of the STRATEGIES names in `domain.staking_simulator`.
    strategy: Mapped[str] = mapped_column(
        String(20), default="adder_breakeven", server_default="adder_breakeven"
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
