"""Engine, session factory, and the per-request session dependency.

This module is the only place that knows which database engine is in use, and it
knows it solely from the URL in `Settings`. Moving to PostgreSQL or MySQL is a
`DATABASE_URL` change plus `alembic upgrade head`.
"""

from collections.abc import Generator
from typing import Annotated, Any

from alembic import command
from alembic.config import Config
from fastapi import Depends
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings


def _connect_args(url: str) -> dict[str, Any]:
    """Engine-specific connection arguments, derived from the URL.

    SQLite refuses to reuse a connection across threads by default, and FastAPI
    serves synchronous endpoints from a threadpool, so the pool has to be
    allowed to hand a connection to a different worker. No server-based engine
    needs this.
    """
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def create_app_engine(url: str) -> Engine:
    return create_engine(url, connect_args=_connect_args(url))


engine = create_app_engine(get_settings().database_url)

SessionFactory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Generator[Session]:
    """One session per request, closed when the request ends.

    Services receive this session; they never create one. The schema itself is
    owned by Alembic — nothing here calls `create_all`.
    """
    with SessionFactory() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def upgrade_to_head() -> None:
    """Bring the configured database to the latest migration.

    Run at startup because a hosted deploy has no pre-start step, and its SQLite
    file begins empty. A no-op on a database already at head.

    `alembic/` resolves against the working directory, like `./app.db` and
    `.env`: start the app from the repository root. The `Config` deliberately
    has no ini file: `alembic/env.py` then skips `fileConfig`, which would
    otherwise replace the structlog handlers `log.configure` installed.
    """
    config = Config()
    config.set_main_option("script_location", "alembic")
    command.upgrade(config, "head")
