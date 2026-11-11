import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from paypal_agent.agent import commerce_nodes, nodes
from paypal_agent.config import settings
from paypal_agent.main import app
from paypal_agent.services import paypal_mcp_client


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "monitor_enabled", False)

    with TestClient(app) as test_client:
        yield test_client


def test_other_websites_cannot_trigger_actions(client):
    response = client.post(
        "/api/monitor/run", headers={"Origin": "https://evil.example"}
    )

    assert response.status_code == 403


def test_our_frontend_and_non_browser_tools_are_allowed(client, monkeypatch):
    async def no_invoices():
        return []

    monkeypatch.setattr(
        "paypal_agent.api.routes.check_all_invoices", no_invoices
    )

    assert client.post(
        "/api/monitor/run", headers={"Origin": "http://localhost:3000"}
    ).status_code == 200
    assert client.post("/api/monitor/run").status_code == 200


def test_reads_and_webhooks_are_not_origin_checked(client):
    # GETs can't change anything, and webhooks are checked by signature.
    assert client.get(
        "/api/events", headers={"Origin": "https://evil.example"}
    ).status_code == 200
    assert client.post(
        "/api/webhooks/paypal", headers={"Origin": "https://evil.example"}
    ).status_code != 403


def test_bad_ids_are_rejected_before_reaching_paypal(client):
    assert client.post("/api/invoices/bad%20id!/send").status_code == 422
    assert client.get("/api/disputes/" + "x" * 65).status_code == 422


class ListLLM:
    async def chat(self, **kwargs):
        return SimpleNamespace(message=SimpleNamespace(content='["not", "an", "object"]'))


def test_llm_returning_a_list_does_not_crash(monkeypatch):
    monkeypatch.setattr(nodes, "get_llm", lambda: ListLLM())

    result = asyncio.run(
        nodes.understand_request({"user_message": "hi", "conversation_history": []})
    )

    assert "rephrase" in result["response"]


class RecordingLLM:
    seen = []

    async def chat(self, model, messages, format=None):
        RecordingLLM.seen = messages
        return SimpleNamespace(
            message=SimpleNamespace(content=json.dumps({"intent": "general", "response": "ok"}))
        )


def test_only_recent_history_goes_to_the_llm(monkeypatch):
    monkeypatch.setattr(nodes, "get_llm", lambda: RecordingLLM())
    history = [{"role": "user", "content": f"message {i}"} for i in range(200)]

    asyncio.run(nodes.understand_request({"user_message": "hi", "conversation_history": history}))

    # system prompt + recent history + the new message
    assert len(RecordingLLM.seen) == nodes.MAX_HISTORY_MESSAGES + 2


def test_llm_client_has_a_timeout(monkeypatch):
    monkeypatch.setattr(settings, "ollama_api_key", "test-key")

    assert nodes.get_llm()._client.timeout.read == nodes.LLM_TIMEOUT_SECONDS


def test_mcp_server_does_not_get_our_secrets(monkeypatch):
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "super-secret")
    monkeypatch.setenv("OLLAMA_API_KEY", "also-secret")
    monkeypatch.setenv("PATH", "/usr/bin")

    env = paypal_mcp_client._child_environment()

    assert "PAYPAL_CLIENT_SECRET" not in env
    assert "OLLAMA_API_KEY" not in env
    assert env["PATH"] == "/usr/bin"


def test_llm_supplied_dispute_ids_are_checked():
    assert commerce_nodes.valid_id("PP-D-12345") == "PP-D-12345"
    assert commerce_nodes.valid_id("../../v1/oauth2/token") is None
    assert commerce_nodes.valid_id("PP D 1; drop") is None


def test_model_out_of_credits_gives_a_clear_message(client, monkeypatch):
    class OutOfCredits(Exception):
        status_code = 402

    async def fail(*args, **kwargs):
        raise OutOfCredits("Add usage credits")

    monkeypatch.setattr(client.app.state.payment_agent, "ainvoke", fail)

    response = client.post("/api/chat", json={"message": "hi"})

    assert response.status_code == 503
    assert "Shortcuts still work" in response.json()["detail"]
