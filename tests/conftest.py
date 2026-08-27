"""Test fixtures.

Every test gets a throwaway SQLite file whose schema is built by the real
migrations, so the suite fails if a migration stops producing the schema the
application expects.
"""

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import Session, sessionmaker

from app.db import create_app_engine, get_session
from app.main import app

APP_ROOT = Path(__file__).resolve().parents[1]

REFERENCE_BODY = {
    "capital": 1000.0,
    "entry_1a": 5.0,
    "entry_1b": 5.0,
    "payout_ratio": 0.92,
    "target_profit": 0.0,
}

REFERENCE_FORM = {
    "capital": "1000",
    "payout_percent": "92",
    "entry_1a": "5",
    "entry_1b": "5",
    "target_profit_percent": "0",
    "max_entries": "50",
    # Required: an unchecked checkbox is simply absent from a real POST, so
    # `RawSimulationForm.strategies` defaults to empty rather than to some
    # pre-picked set, and an empty selection is a validation error, not a
    # run. One strategy here keeps this form behaving as a single run, not a
    # comparison. breakeven and profit recovery are identical at this form's
    # $0 target, so the resulting ladder is the same 910/163/8 case either way.
    "strategies": ["adder_breakeven"],
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    """A session factory over a fresh database at `head`."""
    url = f"sqlite:///{tmp_path / 'test.db'}"

    config = Config(str(APP_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")

    engine = create_app_engine(url)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def session(sessions: sessionmaker[Session]) -> Iterator[Session]:
    """A session for asserting directly against the database."""
    with sessions() as open_session:
        yield open_session


@pytest.fixture
async def client(sessions: sessionmaker[Session]) -> AsyncIterator[AsyncClient]:
    """The app, driven over its ASGI interface with no network in the way."""

    def use_test_session() -> Iterator[Session]:
        with sessions() as open_session:
            yield open_session

    app.dependency_overrides[get_session] = use_test_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as open_client:
        yield open_client
    app.dependency_overrides.clear()
