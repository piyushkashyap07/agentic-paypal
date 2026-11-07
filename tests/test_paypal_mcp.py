import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from paypal_agent.config import settings
from paypal_agent.database import repositories
from paypal_agent.services import paypal_invoice_service, paypal_mcp_client
from paypal_agent.services.paypal_invoice_service import PayPalInvoiceService
from paypal_agent.services.paypal_mcp_client import PayPalMCPClient, PayPalMCPError


class FakeMCP:
    """Records tool calls and answers with canned results."""

    def __init__(self, results: dict):
        self.results = results
        self.calls = []

    async def call(self, tool: str, arguments: dict) -> dict:
        self.calls.append((tool, arguments))
        return json.loads(json.dumps(self.results.get(tool, {})))


@pytest.fixture
def fake_mcp(monkeypatch):
    monkeypatch.setattr(settings, "paypal_transport", "mcp")
    monkeypatch.setattr(settings, "paypal_invoicer_email", "seller@example.com")

    def install(results: dict) -> FakeMCP:
        fake = FakeMCP(results)
        monkeypatch.setattr(paypal_invoice_service, "mcp_client", fake)
        return fake

    return install


@pytest.mark.asyncio
async def test_create_invoice_uses_mcp_tool_with_due_date_in_note(fake_mcp):
    fake = fake_mcp({
        "create_invoice": {
            "rel": "self",
            "href": "https://api.sandbox.paypal.com/v2/invoicing/invoices/INV2-MCP",
            "method": "GET",
        },
        "get_invoice": {"id": "INV2-MCP", "status": "DRAFT"},
    })

    result = await PayPalInvoiceService().create_draft_invoice(
        customer_email="buyer@example.com",
        customer_name="Acme",
        amount=Decimal("150"),
        currency="usd",
        description="Logo design",
        due_date=date(2026, 12, 7),
    )

    assert result["id"] == "INV2-MCP"
    tool, args = fake.calls[0]
    assert tool == "create_invoice"
    assert args["currency_code"] == "USD"
    assert args["invoicer_email_address"] == "seller@example.com"
    assert args["items"][0]["unit_amount"] == {"currency_code": "USD", "value": "150.00"}
    assert args["primary_recipients"][0]["billing_info"]["email_address"] == "buyer@example.com"
    assert "2026-12-07" in args["note"]
    assert fake.calls[1] == ("get_invoice", {"invoice_id": "INV2-MCP"})


@pytest.mark.asyncio
async def test_get_invoice_fills_due_date_from_our_record(fake_mcp):
    fake_mcp({"get_invoice": {"id": "INV2-MCP", "status": "SENT", "detail": {}}})
    await repositories.upsert_invoice("INV2-MCP", due_date=date(2026, 12, 7))

    invoice = await PayPalInvoiceService().get_invoice("INV2-MCP")

    assert invoice["detail"]["payment_term"]["due_date"] == "2026-12-07"


@pytest.mark.asyncio
async def test_paypal_due_date_wins_over_our_record(fake_mcp):
    fake_mcp({
        "get_invoice": {
            "id": "INV2-MCP",
            "detail": {"payment_term": {"due_date": "2026-11-30"}},
        }
    })
    await repositories.upsert_invoice("INV2-MCP", due_date=date(2026, 12, 7))

    invoice = await PayPalInvoiceService().get_invoice("INV2-MCP")

    assert invoice["detail"]["payment_term"]["due_date"] == "2026-11-30"


@pytest.mark.asyncio
async def test_send_remind_list_go_through_mcp(fake_mcp):
    fake = fake_mcp({"list_invoices": {"items": [{"id": "INV2-A"}]}})
    service = PayPalInvoiceService()

    await service.send_invoice("INV2-A")
    await service.send_reminder("INV2-A")
    items = await service.list_invoices(page_size=5)

    assert [tool for tool, _ in fake.calls] == [
        "send_invoice",
        "send_invoice_reminder",
        "list_invoices",
    ]
    assert fake.calls[0][1] == {"invoice_id": "INV2-A", "send_to_recipient": True}
    assert items == [{"id": "INV2-A", "detail": {}}]


@pytest.mark.asyncio
async def test_refund_uses_mcp_create_refund_with_capture_id(fake_mcp):
    fake = fake_mcp({
        "get_invoice": {
            "id": "INV2-PAID",
            "detail": {"currency_code": "USD"},
            "payments": {"transactions": [{"type": "PAYPAL", "payment_id": "CAPTURE123"}]},
        },
        "create_refund": {"id": "REFUND1", "status": "COMPLETED"},
    })

    result = await PayPalInvoiceService().refund_invoice("INV2-PAID", Decimal("1"))

    assert result["status"] == "COMPLETED"
    assert fake.calls[-1] == (
        "create_refund",
        {
            "capture_id": "CAPTURE123",
            "invoice_id": "INV2-PAID",
            "amount": {"currency_code": "USD", "value": "1.00"},
        },
    )


def _session_returning(text: str, is_error: bool = False):
    async def call_tool(name, arguments, read_timeout_seconds=None):
        return SimpleNamespace(
            content=[SimpleNamespace(text=text)], is_error=is_error
        )

    return SimpleNamespace(call_tool=call_tool)


@pytest.mark.asyncio
async def test_mcp_client_parses_json_result(monkeypatch):
    client = PayPalMCPClient()

    async def session():
        return _session_returning('{"id": "INV2-X", "status": "SENT"}')

    monkeypatch.setattr(client, "_ensure_session", session)

    assert await client.call("get_invoice", {"invoice_id": "INV2-X"}) == {
        "id": "INV2-X",
        "status": "SENT",
    }


@pytest.mark.asyncio
async def test_mcp_client_raises_on_ok_false(monkeypatch):
    client = PayPalMCPClient()

    async def session():
        return _session_returning(
            '{"ok": false, "status": 404, "message": "The specified resource does not exist."}'
        )

    monkeypatch.setattr(client, "_ensure_session", session)

    with pytest.raises(PayPalMCPError) as error:
        await client.call("get_invoice", {"invoice_id": "INV2-NOPE"})

    assert error.value.status == 404


@pytest.mark.asyncio
async def test_mcp_client_explains_india_block(monkeypatch):
    client = PayPalMCPClient()

    async def session():
        return _session_returning(
            '{"ok": false, "status": 422, "message": "INR_FOREIGN_CURRENCY_BLOCKED"}'
        )

    monkeypatch.setattr(client, "_ensure_session", session)

    with pytest.raises(ValueError, match="India"):
        await client.call("send_invoice", {"invoice_id": "INV2-X"})


def test_mcp_is_the_default_transport():
    assert type(settings).model_fields["paypal_transport"].default == "mcp"
    assert paypal_mcp_client.mcp_client is not None
