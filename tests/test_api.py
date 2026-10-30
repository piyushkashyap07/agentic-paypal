import pytest
from fastapi.testclient import TestClient

from paypal_agent.api import routes
from paypal_agent.config import settings
from paypal_agent.main import app
from paypal_agent.workers import payment_monitor


class FakePayPal:
    async def get_invoice(self, invoice_id):
        return {
            "id": invoice_id,
            "status": "SENT",
            "detail": {"currency_code": "USD"},
            "amount": {"value": "50.00"},
            "due_amount": {"value": "50.00"},
        }

    async def list_invoices(self, page_size=20):
        return [await self.get_invoice("INV2-1")]

    async def refund_invoice(self, invoice_id, amount=None):
        raise ValueError("This invoice has no PayPal payment that can be refunded.")


@pytest.fixture
def client(monkeypatch):
    # Keep the background monitor from calling the real PayPal API.
    monkeypatch.setattr(settings, "monitor_enabled", False)
    monkeypatch.setattr(routes, "PayPalInvoiceService", FakePayPal)
    monkeypatch.setattr(payment_monitor, "PayPalInvoiceService", FakePayPal)

    with TestClient(app) as test_client:
        yield test_client


def test_health(client):
    assert client.get("/health").json() == {"status": "healthy"}


def test_invoice_status(client):
    body = client.get("/api/invoices/INV2-1").json()

    assert body["status"] == "SENT"
    assert body["next_action"] == "wait"


def test_list_invoices(client):
    body = client.get("/api/invoices").json()

    assert [invoice["invoice_id"] for invoice in body] == ["INV2-1"]


def test_refund_error_is_a_clear_400(client):
    response = client.post("/api/invoices/INV2-1/refund", json={})

    assert response.status_code == 400
    assert "no PayPal payment" in response.json()["detail"]


def test_chat_ui_is_served(client):
    response = client.get("/ui")

    assert response.status_code == 200
    assert "PayPal AI Agent" in response.text
