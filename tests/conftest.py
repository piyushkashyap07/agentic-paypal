import pytest

from paypal_agent.config import settings
from paypal_agent.database import session


@pytest.fixture(autouse=True)
def temp_database(tmp_path, monkeypatch):
    """Every test gets its own empty SQLite file, never the real one."""

    monkeypatch.setattr(
        settings, "database_url", f"sqlite+aiosqlite:///{tmp_path}/test.db"
    )
    session._engine = session._factory = None
    session._ready = False

    yield

    session._engine = session._factory = None
    session._ready = False
