"""Declarative base and the mixins shared by every table.

The naming convention is set on the metadata once. Without it Alembic cannot
autogenerate a reliable migration for a constraint, because an unnamed
constraint has a different name on every engine.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Dialect, MetaData, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    """Timezone-aware UTC now.

    Set in Python rather than by the database: SQLite, PostgreSQL, and MySQL
    each generate timestamps with different precision and time-zone handling.
    """
    return datetime.now(UTC)


class UtcDateTime(TypeDecorator[datetime]):
    """A timestamp that is timezone-aware UTC on the way in *and* on the way out.

    `DateTime(timezone=True)` is only half the story. PostgreSQL hands back an
    aware value; SQLite stores a naive string and hands back a naive value, so
    the same row would read differently on the two engines and a comparison
    against an aware datetime would raise `TypeError` on one of them.

    The DDL is unchanged — this renders as the underlying `DateTime(timezone=True)`
    — so migrations stay engine-neutral.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        # A naive value here means a caller bypassed `utcnow`; treat it as UTC
        # rather than storing an ambiguous timestamp.
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """Created/updated timestamps, timezone-aware UTC, set by the application."""

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime,
        default=utcnow,
        onupdate=utcnow,
    )
