"""Work out why an invoice has not been paid, from PayPal's own data.

Everything here is plain Python on purpose: the reasons and the suggested
next action are decided from facts, and the LLM is only asked to phrase them
(see CHECKPOINT.md #7). That keeps the agent from inventing a cause.
"""

from datetime import date

OPEN = {"SENT", "UNPAID", "PARTIALLY_PAID", "SCHEDULED"}


def _days(later: date, earlier: date) -> int:
    return (later - earlier).days


def build_facts(invoice: dict, record=None, today: date | None = None) -> dict:
    """Collect what we know about an invoice's payment situation."""

    today = today or date.today()
    detail = invoice.get("detail", {})
    recipients = invoice.get("primary_recipients") or [{}]
    billing = recipients[0].get("billing_info", {})

    due_text = detail.get("payment_term", {}).get("due_date")
    due = date.fromisoformat(due_text) if due_text else None

    sent_text = detail.get("invoice_date")
    sent_on = date.fromisoformat(sent_text) if sent_text else None

    payments = invoice.get("payments", {}) or {}

    facts = {
        "invoice_id": invoice.get("id"),
        "status": invoice.get("status"),
        "customer": billing.get("name", {}).get("given_name")
        or (record.customer_name if record else None),
        "customer_email": billing.get("email_address"),
        "amount": invoice.get("amount", {}).get("value"),
        "amount_due": invoice.get("due_amount", {}).get("value"),
        "currency": detail.get("currency_code"),
        "invoice_date": sent_text,
        "due_date": due_text,
        "days_since_invoice_date": _days(today, sent_on) if sent_on else None,
        "days_overdue": max(_days(today, due), 0) if due else None,
        "days_until_due": max(_days(due, today), 0) if due else None,
        # PayPal only reports this when it knows; None means "unknown".
        "viewed_by_customer": detail.get("viewed_by_recipient"),
        "payments_received": len(payments.get("transactions", []) or []),
        "reminders_sent": record.reminder_count if record else 0,
        "last_reminder_on": (
            record.last_reminder_on.isoformat()
            if record and record.last_reminder_on
            else None
        ),
    }

    if record and record.simulate_overdue:
        # Demo mode (CHECKPOINT.md #3): the explanation must agree with what
        # the monitor did, so treat the invoice as overdue here too.
        facts["days_overdue"] = max(facts["days_overdue"] or 0, 1)
        facts["days_until_due"] = 0

    reasons, action = _diagnose(facts)
    facts["likely_reasons"] = reasons
    facts["suggested_action"] = action

    return facts


def _diagnose(facts: dict) -> tuple[list[str], str]:
    """Return (likely reasons, the one next step to suggest)."""

    status = facts["status"]

    if status in {"PAID", "MARKED_AS_PAID"}:
        return ["The invoice has been paid."], "none"

    if status in {"REFUNDED", "PARTIALLY_REFUNDED", "MARKED_AS_REFUNDED"}:
        return ["The payment was refunded."], "none"

    if status == "CANCELLED":
        return ["The invoice was cancelled, so nothing is owed."], "none"

    if status == "DRAFT":
        return (
            ["The invoice is still a draft, so the customer has never received it."],
            "send_invoice",
        )

    reasons = []
    action = "wait"

    if status == "PARTIALLY_PAID":
        reasons.append(
            f"The customer paid part of it. {facts['amount_due']} "
            f"{facts['currency']} is still due."
        )
        action = "send_reminder"

    if facts["viewed_by_customer"] is False:
        reasons.append(
            "PayPal shows the customer has not opened the invoice yet. "
            "The email may be in spam or sent to the wrong address."
        )
        action = "send_reminder"

    elif facts["viewed_by_customer"] is True:
        reasons.append("The customer has opened the invoice but not paid yet.")

    if facts["days_overdue"]:
        reasons.append(f"It is {facts['days_overdue']} day(s) past the due date.")
        action = "send_reminder"

    elif facts["days_until_due"] is not None:
        reasons.append(
            f"It is not due yet ({facts['days_until_due']} day(s) left), "
            "so the customer is still within the agreed terms."
        )

    if facts["reminders_sent"]:
        reasons.append(
            f"{facts['reminders_sent']} reminder(s) already sent"
            + (f", the last on {facts['last_reminder_on']}." if facts["last_reminder_on"] else ".")
        )

    if not reasons:
        reasons.append("The invoice was sent and is waiting for the customer to pay.")

    return reasons, action


def plain_summary(facts: dict) -> str:
    """Deterministic explanation, used when the LLM is unavailable."""

    who = facts["customer"] or "The customer"
    head = (
        f"Invoice {facts['invoice_id']} ({facts['amount']} {facts['currency']}"
        f" to {who}) is {facts['status']}."
    )
    body = "\n".join(f"- {reason}" for reason in facts["likely_reasons"])
    tip = {
        "send_invoice": "Reply SEND to email it.",
        "send_reminder": "Reply REMIND and I'll chase them.",
        "wait": "Nothing to do yet; I'm still watching it.",
        "none": "",
    }[facts["suggested_action"]]

    return "\n".join(part for part in (head, body, tip) if part)
