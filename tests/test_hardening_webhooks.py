import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from paypal_agent.agent.graph import route_before_understanding
from paypal_agent.agent.nodes import normalize_reply
from paypal_agent.api import routes, webhooks
from paypal_agent.config import settings
from paypal_agent.database import repositories
from paypal_agent.main import app
from paypal_agent.services import paypal_invoice_service as service_module
from paypal_agent.services.paypal_invoice_service import (
    PayPalInvoiceService,
    _log_paypal_error,
    send_with_retry,
)
from paypal_agent.workers import payment_monitor


# --- reply normalisation -----------------------------------------------------

@pytest.mark.parametrize(
    "text", ["confirm", "CONFIRM", "Confirm!", " confirm. ", "confirm?!"]
)
def test_confirm_variants_are_equal(text):
    assert normalize_reply(text) == "confirm"


def test_confirm_with_punctuation_reaches_the_gate():
    state = {"user_message": "Confirm!", "pending_invoice_confirmation": True}
    assert route_before_understanding(state) == "confirmation_gate"

    state = {
        "user_message": "CONFIRM  REFUND.",
        "pending_refund_confirmation": True,
    }
    assert route_before_understanding(state) == "refund_node"


# --- retries -------------------------------------------------------------------

class Script:
    """A fake httpx client that plays back a list of outcomes."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def request(self, method, url, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(outcome, request=httpx.Request(method, url))


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant)


@pytest.mark.asyncio
async def test_get_is_retried_on_503_then_succeeds():
    client = Script(503, 503, 200)
    response = await send_with_retry(client, "GET", "http://x")
    assert response.status_code == 200 and client.calls == 3


@pytest.mark.asyncio
async def test_post_is_not_retried_on_503():
    client = Script(503, 200)
    response = await send_with_retry(client, "POST", "http://x")
    assert response.status_code == 503 and client.calls == 1


@pytest.mark.asyncio
async def test_post_is_retried_when_connection_never_opened():
    client = Script(httpx.ConnectError("no route"), 200)
    response = await send_with_retry(client, "POST", "http://x")
    assert response.status_code == 200 and client.calls == 2


@pytest.mark.asyncio
async def test_post_is_not_retried_after_a_read_timeout():
    # The request may already have been processed; repeating could double-create.
    client = Script(httpx.ReadTimeout("slow"), 200)
    with pytest.raises(httpx.ReadTimeout):
        await send_with_retry(client, "POST", "http://x")
    assert client.calls == 1


@pytest.mark.asyncio
async def test_gives_up_after_three_attempts():
    client = Script(503, 503, 503)
    response = await send_with_retry(client, "GET", "http://x")
    assert response.status_code == 503 and client.calls == 3


# --- logging + token cache ----------------------------------------------------

def test_error_log_omits_the_raw_body(capsys):
    response = httpx.Response(
        422,
        json={
            "name": "UNPROCESSABLE_ENTITY",
            "debug_id": "abc123",
            "details": [{"issue": "BAD_THING", "value": "secret@customer.test"}],
        },
        request=httpx.Request("POST", "http://x"),
    )

    _log_paypal_error("test", response)
    out = capsys.readouterr().out

    assert "BAD_THING" in out and "abc123" in out
    assert "secret@customer.test" not in out


@pytest.mark.asyncio
async def test_access_token_is_cached(monkeypatch):
    service_module._token_cache.clear()
    calls = []

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def request(self, method, url, **kwargs):
            calls.append(url)
            return httpx.Response(
                200,
                json={"access_token": "tok", "expires_in": 3600},
                request=httpx.Request(method, url),
            )

    monkeypatch.setattr(service_module.httpx, "AsyncClient", lambda **kw: FakeClient())
    monkeypatch.setattr(settings, "paypal_client_id", "id")
    monkeypatch.setattr(settings, "paypal_client_secret", "secret")

    service = PayPalInvoiceService()
    assert await service._get_access_token() == "tok"
    assert await service._get_access_token() == "tok"
    assert len(calls) == 1

    service_module._token_cache.clear()


# --- monitor isolation -----------------------------------------------------------

class FakePayPal:
    statuses = {}
    broken = set()
    reminders = []
    webhook_ok = True

    async def list_invoices(self, page_size=20):
        return [{"id": i, "status": s} for i, s in FakePayPal.statuses.items()]

    async def get_invoice(self, invoice_id):
        if invoice_id in FakePayPal.broken:
            raise RuntimeError("boom")
        return {
            "id": invoice_id,
            "status": FakePayPal.statuses[invoice_id],
            "detail": {"currency_code": "USD"},
            "amount": {"value": "10.00"},
            "due_amount": {"value": "10.00"},
        }

    async def send_reminder(self, invoice_id):
        FakePayPal.reminders.append(invoice_id)

    async def verify_webhook(self, headers, event):
        return FakePayPal.webhook_ok


@pytest.fixture
def paypal(monkeypatch):
    FakePayPal.statuses = {}
    FakePayPal.broken = set()
    FakePayPal.reminders = []
    FakePayPal.webhook_ok = True
    monkeypatch.setattr(payment_monitor, "PayPalInvoiceService", FakePayPal)
    monkeypatch.setattr(webhooks, "PayPalInvoiceService", FakePayPal)
    monkeypatch.setattr(routes, "PayPalInvoiceService", FakePayPal)
    monkeypatch.setattr(settings, "monitor_enabled", False)
    return FakePayPal


@pytest.mark.asyncio
async def test_one_failing_invoice_does_not_stop_the_others(paypal):
    paypal.statuses = {"BAD": "SENT", "GOOD": "SENT"}
    paypal.broken = {"BAD"}
    await repositories.upsert_invoice("BAD", status="SENT")
    await repositories.upsert_invoice("GOOD", status="SENT", simulate_overdue=True)

    failed = await payment_monitor.check_all_invoices()

    assert failed == ["BAD"]
    assert paypal.reminders == ["GOOD"]


def test_simulate_overdue_reports_failure_for_its_own_invoice(paypal):
    paypal.statuses = {"INV-1": "SENT"}
    paypal.broken = {"INV-1"}

    with TestClient(app) as client:
        response = client.post("/api/demo/invoices/INV-1/simulate-overdue")

    assert response.status_code == 502


# --- webhooks -----------------------------------------------------------------------

PAID_EVENT = {
    "event_type": "INVOICING.INVOICE.PAID",
    "resource": {"invoice": {"id": "INV-9"}},
}


def test_webhook_refused_when_not_configured(paypal, monkeypatch):
    monkeypatch.setattr(settings, "paypal_webhook_id", "")
    monkeypatch.setattr(settings, "webhook_allow_unverified", False)

    with TestClient(app) as client:
        assert client.post("/api/webhooks/paypal", json=PAID_EVENT).status_code == 503


def test_webhook_with_bad_signature_is_rejected(paypal, monkeypatch):
    monkeypatch.setattr(settings, "paypal_webhook_id", "WH-1")
    paypal.webhook_ok = False

    with TestClient(app) as client:
        assert client.post("/api/webhooks/paypal", json=PAID_EVENT).status_code == 401


def test_verified_paid_webhook_updates_state_and_events(paypal, monkeypatch):
    monkeypatch.setattr(settings, "paypal_webhook_id", "WH-1")
    paypal.statuses = {"INV-9": "PAID"}

    with TestClient(app) as client:
        asyncio.run(
            repositories.upsert_invoice(
                "INV-9", customer_name="Acme", amount="10.00", currency="USD", status="SENT"
            )
        )
        response = client.post("/api/webhooks/paypal", json=PAID_EVENT)
        events = client.get("/api/events").json()

    assert response.json() == {"status": "synced", "invoice_id": "INV-9"}
    assert events[-1]["message"] == "Acme paid invoice INV-9 (10.00 USD)."


def test_duplicate_webhook_delivery_adds_no_second_event(paypal, monkeypatch):
    monkeypatch.setattr(settings, "paypal_webhook_id", "WH-1")
    paypal.statuses = {"INV-9": "PAID"}

    with TestClient(app) as client:
        asyncio.run(repositories.upsert_invoice("INV-9", status="SENT"))
        client.post("/api/webhooks/paypal", json=PAID_EVENT)
        client.post("/api/webhooks/paypal", json=PAID_EVENT)
        assert len(client.get("/api/events").json()) == 1


def test_webhook_uses_paypals_invoice_not_the_event_body(paypal, monkeypatch):
    """A forged 'PAID' body must not fake a payment: we re-read PayPal."""

    monkeypatch.setattr(settings, "paypal_webhook_id", "WH-1")
    paypal.statuses = {"INV-9": "SENT"}  # PayPal says unpaid

    with TestClient(app) as client:
        asyncio.run(repositories.upsert_invoice("INV-9", status="SENT"))
        client.post("/api/webhooks/paypal", json=PAID_EVENT)
        assert client.get("/api/events").json() == []


def test_other_events_and_bad_json_are_handled(paypal, monkeypatch):
    monkeypatch.setattr(settings, "webhook_allow_unverified", True)

    with TestClient(app) as client:
        other = client.post("/api/webhooks/paypal", json={"event_type": "PAYMENT.SALE.COMPLETED"})
        assert other.json()["status"] == "ignored"
        assert client.post("/api/webhooks/paypal", content="not json").status_code == 400
