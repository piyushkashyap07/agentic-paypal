import pytest

from paypal_agent.config import settings
from paypal_agent.database import session


@pytest.fixture(autouse=True)
def temp_database(tmp_path, monkeypatch):
    """Every test gets its own empty SQLite file, never the real one."""

    monkeypatch.setattr(
        settings, "database_url", f"sqlite+aiosqlite:///{tmp_path}/test.db"
    )
    # Tests never start the real PayPal MCP server; MCP tests fake mcp_client.
    monkeypatch.setattr(settings, "paypal_transport", "rest")
    session._engine = session._factory = None
    session._ready = False

    yield

    session._engine = session._factory = None
    session._ready = False
