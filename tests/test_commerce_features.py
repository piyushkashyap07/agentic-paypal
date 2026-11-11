import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from paypal_agent.agent import commerce_nodes, nodes
from paypal_agent.agent.graph import build_graph
from paypal_agent.config import settings
from paypal_agent.main import app
from paypal_agent.services import paypal_commerce_service, paypal_mcp_client
from paypal_agent.services.paypal_commerce_service import (
    PayPalCommerceService,
    qr_png_base64,
    user_error,
)
from paypal_agent.services.paypal_mcp_client import PayPalMCPError

PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="

INVOICE = {
    "id": "INV2-X",
    "status": "SENT",
    "detail": {"currency_code": "USD", "invoice_date": "2099-01-01"},
    "amount": {"value": "60.00"},
    "due_amount": {"value": "60.00"},
}

PAID_INVOICE = {
    "id": "INV2-PAID",
    "status": "PARTIALLY_REFUNDED",
    "detail": {"currency_code": "USD", "invoice_date": "2099-01-01"},
    "amount": {"value": "100.00"},
    "due_amount": {"value": "0.00"},
    "payments": {
        "paid_amount": {"value": "100.00"},
        "transactions": [{"type": "PAYPAL", "payment_id": "CAPTURE1"}],
    },
    "refunds": {
        "refund_amount": {"value": "10.00"},
        "transactions": [{"type": "PAYPAL", "recipient_transaction_id": "REFUND1"}],
    },
}

DISPUTE = {
    "dispute_id": "PP-D-1",
    "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
    "status": "REQUIRED_ACTION",
    "dispute_amount": {"value": "100.00", "currency_code": "USD"},
    "seller_response_due_date": "2099-01-10T00:00:00Z",
}


class FakeMCP:
    """Answers PayPal MCP tool calls from a table; errors can be scripted."""

    def __init__(self):
        self.calls = []
        self.errors = {}
        self.results = {
            "get_invoice": INVOICE,
            "list_invoices": {"items": [INVOICE, PAID_INVOICE]},
            "cancel_sent_invoice": {},
            "generate_invoice_qr_code": f"--boundary\r\nContent-Type: text/plain\r\n\r\n{PNG}\r\n--boundary--",
            "get_refund": {"status": "COMPLETED", "amount": {"value": "10.00", "currency_code": "USD"}},
            "list_disputes": {"items": [DISPUTE]},
            "get_dispute": DISPUTE,
            "accept_dispute_claim": {},
            "create_order": {
                "id": "ORDER1",
                "status": "PAYER_ACTION_REQUIRED",
                "links": [{"rel": "payer-action", "href": "https://pay.example/ORDER1"}],
            },
            "get_order": {"id": "ORDER1", "status": "APPROVED", "links": []},
            "pay_order": {"id": "ORDER1", "status": "COMPLETED", "links": []},
            "create_shipment_tracking": {},
        }

    async def call(self, tool, arguments):
        self.calls.append((tool, arguments))

        if tool in self.errors:
            raise self.errors[tool]

        if tool == "get_invoice" and arguments["invoice_id"] == "INV2-PAID":
            return json.loads(json.dumps(PAID_INVOICE))

        return json.loads(json.dumps(self.results[tool]))


@pytest.fixture
def mcp(monkeypatch):
    monkeypatch.setattr(settings, "paypal_transport", "mcp")
    fake = FakeMCP()
    monkeypatch.setattr(paypal_mcp_client, "mcp_client", fake)
    # PayPalInvoiceService imported mcp_client by name.
    from paypal_agent.services import paypal_invoice_service

    monkeypatch.setattr(paypal_invoice_service, "mcp_client", fake)
    return fake


# --- Service ---------------------------------------------------------------


def test_commerce_service_needs_mcp():
    with pytest.raises(RuntimeError, match="PAYPAL_TRANSPORT=mcp"):
        PayPalCommerceService()


def test_qr_png_is_pulled_out_of_multipart_text():
    assert qr_png_base64(f"--b\r\nContent-Type: text/plain\r\n\r\n{PNG}\r\n--b--") == PNG


@pytest.mark.asyncio
async def test_earnings_fall_back_to_invoices_without_transaction_search(mcp):
    mcp.errors["list_transactions"] = PayPalMCPError("list_transactions", 403, "denied")

    result = await PayPalCommerceService().earnings(30)

    assert result["source"] == "invoices"
    assert result["received"] == "100.00"
    assert result["refunded"] == "10.00"
    assert result["net"] == "90.00"
    assert result["payments"] == 1


@pytest.mark.asyncio
async def test_earnings_from_transactions_when_allowed(mcp):
    mcp.results["list_transactions"] = {
        "transaction_details": [
            {"transaction_info": {"transaction_status": "S", "transaction_amount": {"value": "50.00", "currency_code": "USD"}}},
            {"transaction_info": {"transaction_status": "S", "transaction_amount": {"value": "-5.00", "currency_code": "USD"}}},
            {"transaction_info": {"transaction_status": "P", "transaction_amount": {"value": "99.00", "currency_code": "USD"}}},
        ]
    }

    result = await PayPalCommerceService().earnings(7)

    assert (result["source"], result["received"], result["refunded"], result["net"]) == (
        "transactions", "50.00", "5.00", "45.00",
    )


@pytest.mark.asyncio
async def test_refund_status_reads_refund_ids_from_invoice(mcp):
    refunds = await PayPalCommerceService().refund_status("INV2-PAID")

    assert refunds[0]["refund_id"] == "REFUND1"
    assert ("get_refund", {"refund_id": "REFUND1"}) in mcp.calls


@pytest.mark.asyncio
async def test_payment_link_is_usd_only_and_returns_link(mcp):
    with pytest.raises(ValueError, match="USD"):
        await PayPalCommerceService().create_payment_link("10", "EUR", "Sketch")

    order = await PayPalCommerceService().create_payment_link("40", "usd", "Logo sketch")

    create_args = mcp.calls[-1][1]
    assert create_args["returnUrl"].endswith("/dashboard")

    assert order == {
        "order_id": "ORDER1",
        "status": "PAYER_ACTION_REQUIRED",
        "amount": "40.00",
        "currency": "USD",
        "pay_link": "https://pay.example/ORDER1",
    }


@pytest.mark.asyncio
async def test_tracking_uses_the_invoice_capture_id(mcp):
    with pytest.raises(ValueError, match="paid"):
        await PayPalCommerceService().add_tracking("INV2-X", "1Z9", "UPS")

    await PayPalCommerceService().add_tracking("INV2-PAID", "1Z9", "ups")

    assert mcp.calls[-1] == (
        "create_shipment_tracking",
        {"transaction_id": "CAPTURE1", "tracking_number": "1Z9", "status": "SHIPPED", "carrier": "UPS"},
    )


def test_user_error_explains_permissions_and_paypal_reasons():
    assert "developer dashboard" in user_error(PayPalMCPError("t", 403, "Unknown error"))
    assert user_error(
        PayPalMCPError("t", 422, "Business validation failed: Draft invoice cannot be canceled.")
    ) == "PayPal said: Draft invoice cannot be canceled."
    assert user_error(PayPalMCPError("t", 500, "boom")) is None


# --- API -------------------------------------------------------------------


def test_api_endpoints(mcp, monkeypatch):
    monkeypatch.setattr(settings, "monitor_enabled", False)

    with TestClient(app) as client:
        assert client.get("/api/disputes").json()[0]["needs_action"] is True

        qr = client.get("/api/invoices/INV2-X/qr.png")
        assert qr.headers["content-type"] == "image/png"
        assert qr.content.startswith(b"\x89PNG")

        assert client.post("/api/invoices/INV2-X/cancel").json()["status"] == "cancelled"
        assert client.post("/api/payment-links", json={"amount": "40", "description": "Sketch"}).json()["order_id"] == "ORDER1"

        mcp.errors["create_shipment_tracking"] = PayPalMCPError("t", 403, "Unknown error")
        denied = client.post("/api/invoices/INV2-PAID/tracking", json={"tracking_number": "1Z9"})
        assert denied.status_code == 400
        assert "developer dashboard" in denied.json()["detail"]


# --- Chat ------------------------------------------------------------------


class FakeLLM:
    replies = {}

    async def chat(self, model, messages, format=None):
        return SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(FakeLLM.replies[messages[-1]["content"]]))
        )


@pytest.fixture
def chat(mcp, monkeypatch):
    monkeypatch.setattr(nodes, "get_llm", lambda: FakeLLM())
    FakeLLM.replies = {
        "any disputes?": {"intent": "list_disputes", "response": ""},
        "explain it": {"intent": "explain_dispute", "response": ""},
        "accept the dispute": {"intent": "accept_dispute", "dispute_id": "PP-D-1", "response": ""},
        "how much did I earn this week?": {"intent": "earnings", "period_days": 7, "response": ""},
        "payment link for $40 for a sketch": {
            "intent": "create_payment_link", "amount": "40", "currency": "USD",
            "description": "Sketch", "response": "",
        },
        "was it paid?": {"intent": "check_payment_link", "response": ""},
        "cancel this invoice": {"intent": "cancel_invoice", "response": ""},
        "qr code": {"intent": "qr_code", "response": ""},
    }
    mcp.errors["list_transactions"] = PayPalMCPError("list_transactions", 403, "denied")
    graph = build_graph(MemorySaver())

    async def say(text, thread="t1", **state):
        result = await graph.ainvoke(
            {"user_message": text, **state}, config={"configurable": {"thread_id": thread}}
        )
        return result["response"]

    return say


@pytest.mark.asyncio
async def test_chat_disputes_explain_and_accept_needs_confirmation(chat, mcp):
    assert "PP-D-1" in await chat("any disputes?")

    explanation = await chat("explain it")
    assert "never received" in explanation and "2099-01-10" in explanation

    assert "CONFIRM ACCEPT" in await chat("accept the dispute")
    assert not any(tool == "accept_dispute_claim" for tool, _ in mcp.calls)

    assert "accepted" in await chat("CONFIRM ACCEPT")
    assert any(tool == "accept_dispute_claim" for tool, _ in mcp.calls)


@pytest.mark.asyncio
async def test_chat_stop_does_not_accept_dispute(chat, mcp):
    await chat("accept the dispute")

    assert "didn't accept" in await chat("stop")
    assert not any(tool == "accept_dispute_claim" for tool, _ in mcp.calls)


@pytest.mark.asyncio
async def test_chat_earnings(chat):
    reply = await chat("how much did I earn this week?")

    assert "last 7 days" in reply and "100.00 USD" in reply and "kept 90.00 USD" in reply


@pytest.mark.asyncio
async def test_chat_payment_link_then_collect(chat, mcp):
    assert "https://pay.example/ORDER1" in await chat("payment link for $40 for a sketch")

    assert "paid" in await chat("was it paid?")
    assert ("pay_order", {"id": "ORDER1"}) in mcp.calls


@pytest.mark.asyncio
async def test_chat_cancel_needs_confirmation_and_qr(chat, mcp):
    assert "CONFIRM CANCEL" in await chat("cancel this invoice", invoice_id="INV2-X")
    assert not any(tool == "cancel_sent_invoice" for tool, _ in mcp.calls)

    assert "cancelled" in await chat("CONFIRM CANCEL")
    assert any(tool == "cancel_sent_invoice" for tool, _ in mcp.calls)

    assert "/api/invoices/INV2-X/qr.png" in await chat("qr code")


@pytest.mark.asyncio
async def test_invoice_actions_need_an_invoice(chat):
    assert "no invoice in this conversation" in await chat("qr code", thread="empty")


def test_commerce_nodes_exist_for_every_action():
    from paypal_agent.agent.graph import ACTION_NODES, CONFIRMED_NODES

    for node in [*ACTION_NODES.values(), *CONFIRMED_NODES]:
        assert hasattr(nodes, node) or hasattr(commerce_nodes, node), node

    assert paypal_commerce_service.PAID_STATUSES
