import json
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import MemorySaver

from paypal_agent.agent import nodes
from paypal_agent.agent.graph import (
    build_graph,
    route_after_understanding,
    route_before_understanding,
)
from paypal_agent.services import paypal_invoice_service
from paypal_agent.workers import payment_monitor


class FakePayPal:
    """Stands in for PayPal and remembers what was asked of it."""

    status = "DRAFT"
    calls = []

    async def create_draft_invoice(self, **invoice):
        FakePayPal.calls.append("create")
        return {"id": "INV2-FAKE", "status": "DRAFT"}

    async def send_invoice(self, invoice_id):
        FakePayPal.calls.append("send")
        FakePayPal.status = "SENT"

    async def send_reminder(self, invoice_id):
        FakePayPal.calls.append("remind")

    async def refund_invoice(self, invoice_id, amount=None):
        FakePayPal.calls.append("refund")
        return {"id": "REFUND1", "status": "COMPLETED"}

    async def get_invoice(self, invoice_id):
        return {
            "id": invoice_id,
            "status": FakePayPal.status,
            "detail": {"currency_code": "USD"},
            "amount": {"value": "50.00"},
            "due_amount": {"value": "50.00"},
        }


class FakeLLM:
    """Returns a scripted extraction for each user message."""

    replies = {}

    async def chat(self, model, messages, format):
        reply = FakeLLM.replies[messages[-1]["content"]]
        return SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(reply))
        )


@pytest.fixture
def agent(monkeypatch):
    FakePayPal.status = "DRAFT"
    FakePayPal.calls = []
    FakeLLM.replies = {
        "Invoice Acme $50 USD for a logo, buyer@example.com": {
            "intent": "create_invoice",
            "customer_name": "Acme",
            "customer_email": "buyer@example.com",
            "amount": "50.00",
            "currency": "USD",
            "description": "Logo",
            "response": "",
        },
        "has it been paid?": {"intent": "check_status", "response": ""},
    }

    monkeypatch.setattr(nodes, "get_llm", lambda: FakeLLM())
    monkeypatch.setattr(
        paypal_invoice_service, "PayPalInvoiceService", FakePayPal
    )
    monkeypatch.setattr(payment_monitor, "PayPalInvoiceService", FakePayPal)

    graph = build_graph(MemorySaver())
    config = {"configurable": {"thread_id": "test"}}

    async def say(message):
        result = await graph.ainvoke({"user_message": message}, config=config)
        return result["response"]

    return say


def test_shortcuts_need_an_existing_invoice():
    assert route_before_understanding({"user_message": "send"}) == (
        "understand_request"
    )
    assert route_before_understanding(
        {"user_message": "SEND", "invoice_id": "INV2-1"}
    ) == "send_invoice_node"


def test_refund_confirmation_goes_to_refund_node():
    state = {
        "user_message": "confirm refund",
        "invoice_id": "INV2-1",
        "pending_refund_confirmation": True,
    }

    assert route_before_understanding(state) == "refund_node"


def test_requested_action_routes_to_its_node():
    assert route_after_understanding({"requested_action": "send_reminder"}) == (
        "send_reminder_node"
    )
    assert route_after_understanding({"requested_action": ""}) == "__end__"


@pytest.mark.asyncio
async def test_create_send_and_check_status(agent):
    reply = await agent("Invoice Acme $50 USD for a logo, buyer@example.com")
    assert "Reply CONFIRM" in reply
    assert FakePayPal.calls == []

    reply = await agent("confirm")
    assert "INV2-FAKE" in reply

    reply = await agent("send")
    assert "emailed to the customer" in reply

    reply = await agent("has it been paid?")
    assert "waiting for payment" in reply

    assert FakePayPal.calls == ["create", "send"]


@pytest.mark.asyncio
async def test_refund_needs_paid_invoice_and_confirmation(agent):
    await agent("Invoice Acme $50 USD for a logo, buyer@example.com")
    await agent("confirm")

    reply = await agent("refund")
    assert "Only paid invoices" in reply

    FakePayPal.status = "PAID"
    reply = await agent("refund")
    assert "CONFIRM REFUND" in reply
    assert "refund" not in FakePayPal.calls

    reply = await agent("confirm refund")
    assert "COMPLETED" in reply
    assert FakePayPal.calls[-1] == "refund"


@pytest.mark.asyncio
async def test_refund_can_be_cancelled(agent):
    await agent("Invoice Acme $50 USD for a logo, buyer@example.com")
    await agent("confirm")
    FakePayPal.status = "PAID"
    await agent("refund")

    reply = await agent("cancel")

    assert "No money was moved" in reply
    assert "refund" not in FakePayPal.calls
