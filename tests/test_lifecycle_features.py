import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from paypal_agent.agent import nodes
from paypal_agent.agent.graph import build_graph
from paypal_agent.api import routes
from paypal_agent.config import settings
from paypal_agent.database import repositories
from paypal_agent.main import app
from paypal_agent.services import paypal_invoice_service
from paypal_agent.services.payment_explainer import build_facts
from paypal_agent.workers import payment_monitor


class FakePayPal:
    status = "DRAFT"
    due_date = None
    viewed = None
    created = []
    reminders = []

    async def create_draft_invoice(self, **invoice):
        FakePayPal.created.append(invoice)
        return {"id": "INV2-FAKE", "status": "DRAFT"}

    async def send_invoice(self, invoice_id):
        FakePayPal.status = "SENT"

    async def send_reminder(self, invoice_id):
        FakePayPal.reminders.append(invoice_id)

    async def get_invoice(self, invoice_id):
        detail = {"currency_code": "USD", "invoice_date": "2026-10-01"}
        if FakePayPal.due_date:
            detail["payment_term"] = {"due_date": FakePayPal.due_date}
        if FakePayPal.viewed is not None:
            detail["viewed_by_recipient"] = FakePayPal.viewed
        return {
            "id": invoice_id,
            "status": FakePayPal.status,
            "detail": detail,
            "primary_recipients": [
                {"billing_info": {"email_address": "b@example.com", "name": {"given_name": "Acme"}}}
            ],
            "amount": {"value": "50.00"},
            "due_amount": {"value": "50.00"},
        }

    async def list_invoices(self, page_size=20):
        return [await self.get_invoice("INV2-FAKE")]


class FakeLLM:
    replies = {}

    async def chat(self, model, messages, format=None):
        if format is None:  # the explainer call: plain text, not JSON
            return SimpleNamespace(message=SimpleNamespace(content="LLM-WORDING"))
        reply = FakeLLM.replies[messages[-1]["content"]]
        return SimpleNamespace(message=SimpleNamespace(content=json.dumps(reply)))


CREATE = "Invoice Acme $50 USD for a logo, buyer@example.com, net 30"
CREATE_NO_EMAIL = "Invoice Acme $70 USD for a banner"


@pytest.fixture
def agent(monkeypatch):
    FakePayPal.status, FakePayPal.due_date, FakePayPal.viewed = "DRAFT", None, None
    FakePayPal.created, FakePayPal.reminders = [], []
    FakeLLM.replies = {
        CREATE: {
            "intent": "create_invoice", "customer_name": "Acme",
            "customer_email": "buyer@example.com", "amount": "50.00",
            "currency": "USD", "description": "Logo", "due_in_days": 30,
        },
        CREATE_NO_EMAIL: {
            "intent": "create_invoice", "customer_name": "Acme",
            "customer_email": None, "amount": "70.00",
            "currency": "USD", "description": "Banner", "due_in_days": None,
        },
        "why haven't I been paid?": {"intent": "explain_unpaid"},
    }

    monkeypatch.setattr(nodes, "get_llm", lambda: FakeLLM())
    monkeypatch.setattr(paypal_invoice_service, "PayPalInvoiceService", FakePayPal)
    monkeypatch.setattr(payment_monitor, "PayPalInvoiceService", FakePayPal)

    graph = build_graph(MemorySaver())

    def talker(thread):
        config = {"configurable": {"thread_id": thread}}

        async def say(message):
            result = await graph.ainvoke({"user_message": message}, config=config)
            return result["response"]

        return say

    return talker


# --- #1 plan ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_plan_is_shown_and_progresses(agent):
    say = agent("t1")

    reply = await say(CREATE)
    assert "My plan:" in reply and "[>] 1. Create a draft invoice" in reply

    reply = await say("confirm")
    assert "[x] 1. Create a draft invoice" in reply and "[>] 2." in reply

    reply = await say("send")
    assert "[x] 2. Send it to the customer" in reply and "[>] 3." in reply


# --- #4 due date + customer lookup ----------------------------------------------

@pytest.mark.asyncio
async def test_due_date_from_net_terms_reaches_paypal(agent):
    say = agent("t2")
    reply = await say(CREATE)
    expected = (date.today() + timedelta(days=30)).isoformat()
    assert f"Due: {expected}" in reply

    await say("confirm")
    assert FakePayPal.created[0]["due_date"].isoformat() == expected


@pytest.mark.asyncio
async def test_default_due_date_is_used_and_disclosed(agent):
    await repositories.remember_customer("Acme", "known@example.com")
    say = agent("t3")
    reply = await say(CREATE_NO_EMAIL)

    assert f"default {settings.default_due_days} days" in reply
    assert "known@example.com (remembered from a previous invoice)" in reply


@pytest.mark.asyncio
async def test_unknown_customer_without_email_is_still_asked(agent):
    say = agent("t4")
    reply = await say(CREATE_NO_EMAIL)

    assert "customer billing email" in reply


@pytest.mark.asyncio
async def test_created_invoice_is_saved_and_customer_remembered(agent):
    say = agent("t5")
    await say(CREATE)
    await say("confirm")

    record = await repositories.get_invoice_record("INV2-FAKE")
    assert record.customer_name == "Acme" and record.status == "DRAFT"
    assert await repositories.find_customer_email("  acme ") == "buyer@example.com"

    await say("send")
    assert (await repositories.get_invoice_record("INV2-FAKE")).status == "SENT"


# --- #5 events persisted ----------------------------------------------------------

@pytest.mark.asyncio
async def test_events_persist_and_can_be_read_after_an_id():
    first = await repositories.add_event("INV-1", "one")
    await repositories.add_event("INV-1", "two")

    assert [e["message"] for e in await repositories.list_events()] == ["one", "two"]
    assert [e["message"] for e in await repositories.list_events(after=first["id"])] == ["two"]


# --- #6 workflow state drives the monitor -------------------------------------------

@pytest.mark.asyncio
async def test_status_change_is_detected_across_restarts(agent):
    await repositories.upsert_invoice(
        "INV2-FAKE", customer_name="Acme", amount="50.00", currency="USD", status="SENT"
    )
    FakePayPal.status = "PAID"

    await payment_monitor.check_all_invoices()

    events = await repositories.list_events()
    assert [e["message"] for e in events] == ["Acme paid invoice INV2-FAKE (50.00 USD)."]

    await payment_monitor.check_all_invoices()  # nothing changed -> no duplicate
    assert len(await repositories.list_events()) == 1


@pytest.mark.asyncio
async def test_unknown_invoice_is_learned_quietly(agent):
    FakePayPal.status = "SENT"
    await payment_monitor.check_all_invoices()

    assert await repositories.list_events() == []
    assert (await repositories.get_invoice_record("INV2-FAKE")).status == "SENT"


# --- #3 overdue ------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_overdue_invoice_gets_one_reminder_per_day(agent):
    FakePayPal.status = "SENT"
    FakePayPal.due_date = (date.today() - timedelta(days=3)).isoformat()

    await payment_monitor.check_all_invoices()
    await payment_monitor.check_all_invoices()

    assert FakePayPal.reminders == ["INV2-FAKE"]
    record = await repositories.get_invoice_record("INV2-FAKE")
    assert record.reminder_count == 1


def test_simulate_overdue_endpoint(agent, monkeypatch):
    FakePayPal.status = "SENT"
    monkeypatch.setattr(settings, "monitor_enabled", False)
    monkeypatch.setattr(routes, "PayPalInvoiceService", FakePayPal)

    with TestClient(app) as client:
        response = client.post("/api/demo/invoices/INV2-FAKE/simulate-overdue")
        assert response.status_code == 200
        assert FakePayPal.reminders == ["INV2-FAKE"]

        events = client.get("/api/events").json()
        assert "INV2-FAKE" in events[-1]["message"]
        assert events[-1]["message"].endswith("is overdue. Reminder sent.")
        assert client.get(f"/api/events?after={events[-1]['id']}").json() == []

        invoices = client.get("/api/invoices").json()
        assert invoices[0]["simulated_overdue"] is True


def test_demo_endpoints_are_hidden_outside_development(agent, monkeypatch):
    monkeypatch.setattr(settings, "monitor_enabled", False)
    monkeypatch.setattr(settings, "app_env", "production")

    with TestClient(app) as client:
        assert client.post("/api/demo/invoices/X/simulate-overdue").status_code == 404
        assert client.post("/api/monitor/run").status_code == 404


# --- #7 why haven't I been paid? -------------------------------------------------------

def test_explainer_facts_pick_the_right_reason():
    today = date(2026, 11, 10)
    base = {
        "id": "I", "status": "SENT", "amount": {"value": "50.00"},
        "due_amount": {"value": "50.00"},
        "detail": {"currency_code": "USD", "invoice_date": "2026-10-01",
                   "payment_term": {"due_date": "2026-11-01"}, "viewed_by_recipient": False},
    }
    facts = build_facts(base, today=today)
    assert facts["days_overdue"] == 9 and facts["suggested_action"] == "send_reminder"
    assert any("not opened" in r for r in facts["likely_reasons"])

    base["detail"]["payment_term"]["due_date"] = "2026-11-30"
    base["detail"]["viewed_by_recipient"] = True
    facts = build_facts(base, today=today)
    assert facts["suggested_action"] == "wait" and facts["days_overdue"] == 0

    record = SimpleNamespace(
        simulate_overdue=True, reminder_count=0, last_reminder_on=None, customer_name="Acme"
    )
    facts = build_facts(base, record, today=today)
    assert facts["days_overdue"] == 1 and facts["suggested_action"] == "send_reminder"

    base["status"] = "DRAFT"
    assert build_facts(base, today=today)["suggested_action"] == "send_invoice"


@pytest.mark.asyncio
async def test_why_not_paid_works_in_a_fresh_chat_and_enables_remind(agent):
    FakePayPal.status = "SENT"
    await repositories.upsert_invoice("INV2-FAKE", status="SENT")

    say = agent("fresh-thread")
    assert await say("why haven't I been paid?") == "LLM-WORDING"

    assert "Reminder sent" in await say("remind")  # invoice_id was adopted


@pytest.mark.asyncio
async def test_why_not_paid_without_invoices(agent):
    reply = await agent("empty")("why haven't I been paid?")
    assert "don't see any unpaid invoice" in reply
