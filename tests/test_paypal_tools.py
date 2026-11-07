from datetime import date, timedelta

import httpx
import pytest

from paypal_agent.services import paypal_invoice_service
from paypal_agent.services.paypal_invoice_service import PayPalInvoiceService
from paypal_agent.workers.payment_monitor import (
    decide_next_action,
    summarize_invoice,
)


def invoice_with(status, due_date=None, payments=None):
    detail = {"currency_code": "USD"}

    if due_date:
        detail["payment_term"] = {"due_date": due_date.isoformat()}

    return {
        "id": "INV2-TEST",
        "status": status,
        "detail": detail,
        "amount": {"value": "50.00"},
        "due_amount": {"value": "50.00"},
        "payments": payments or {},
    }


@pytest.mark.parametrize(
    ("invoice", "expected"),
    [
        (invoice_with("DRAFT"), "send_invoice"),
        (invoice_with("SENT"), "wait"),
        (invoice_with("SENT", date.today() + timedelta(days=3)), "wait"),
        (invoice_with("SENT", date.today() - timedelta(days=1)), "send_reminder"),
        (invoice_with("PAID"), "notify_paid"),
        (invoice_with("REFUNDED"), "notify_closed"),
    ],
)
def test_decide_next_action(invoice, expected):
    assert decide_next_action(invoice) == expected


def test_summarize_invoice_reads_customer_and_link():
    invoice = invoice_with("SENT")
    invoice["primary_recipients"] = [
        {"billing_info": {"email_address": "buyer@example.com"}}
    ]
    invoice["detail"]["metadata"] = {"recipient_view_url": "https://pay"}

    summary = summarize_invoice(invoice)

    assert summary["customer_email"] == "buyer@example.com"
    assert summary["pay_link"] == "https://pay"
    assert summary["next_action"] == "wait"


@pytest.mark.asyncio
async def test_refund_uses_capture_id_from_invoice(monkeypatch):
    service = PayPalInvoiceService()
    calls = []

    async def fake_get_invoice(invoice_id):
        return invoice_with(
            "PAID",
            payments={
                "transactions": [{"type": "PAYPAL", "payment_id": "CAP123"}]
            },
        )

    async def fake_request(method, path, json=None, params=None):
        calls.append((method, path, json))
        return {"id": "REFUND1", "status": "COMPLETED"}

    monkeypatch.setattr(service, "get_invoice", fake_get_invoice)
    monkeypatch.setattr(service, "_request", fake_request)

    result = await service.refund_invoice("INV2-TEST", amount="1.00")

    assert result["status"] == "COMPLETED"
    assert calls == [
        (
            "POST",
            "/v2/payments/captures/CAP123/refund",
            {"amount": {"currency_code": "USD", "value": "1.00"}},
        )
    ]


@pytest.mark.asyncio
async def test_refund_without_paypal_payment_is_rejected(monkeypatch):
    service = PayPalInvoiceService()

    async def fake_get_invoice(invoice_id):
        return invoice_with("SENT")

    monkeypatch.setattr(service, "get_invoice", fake_get_invoice)

    with pytest.raises(ValueError, match="no PayPal payment"):
        await service.refund_invoice("INV2-TEST")


@pytest.mark.asyncio
async def test_india_customer_error_is_explained(monkeypatch):
    def handler(request):
        return httpx.Response(
            406,
            json={"details": [{"issue": "INR_FOREIGN_CURRENCY_BLOCKED"}]},
        )

    real_client = httpx.AsyncClient

    monkeypatch.setattr(
        paypal_invoice_service.httpx,
        "AsyncClient",
        lambda timeout: real_client(transport=httpx.MockTransport(handler)),
    )

    service = PayPalInvoiceService()

    async def fake_token():
        return "token"

    monkeypatch.setattr(service, "_get_access_token", fake_token)

    with pytest.raises(ValueError, match="customers in India"):
        await service.send_invoice("INV2-TEST")
