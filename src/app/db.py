"""Engine, session factory, and the per-request session dependency.

This module is the only place that knows which database engine is in use, and it
knows it solely from the URL in `Settings`. Moving to PostgreSQL or MySQL is a
`DATABASE_URL` change plus `alembic upgrade head`.
"""

from collections.abc import Generator
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


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
