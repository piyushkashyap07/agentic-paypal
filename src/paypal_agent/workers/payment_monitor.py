import asyncio
from datetime import date

from paypal_agent.services.paypal_invoice_service import PayPalInvoiceService

# Statuses after which there is nothing left to watch.
FINAL_STATUSES = {"PAID", "MARKED_AS_PAID", "CANCELLED", "REFUNDED"}


def decide_next_action(invoice: dict) -> str:
    """Decide what the agent should do next for an invoice."""

    status = invoice.get("status", "")

    if status in {"PAID", "MARKED_AS_PAID"}:
        return "notify_paid"

    if status in {"CANCELLED", "REFUNDED"}:
        return "notify_closed"

    if status == "DRAFT":
        return "send_invoice"

    due_date = (
        invoice.get("detail", {})
        .get("payment_term", {})
        .get("due_date")
    )

    if due_date and date.fromisoformat(due_date) < date.today():
        return "send_reminder"

    return "wait"


async def check_invoice(invoice_id: str) -> dict:
    """Check an invoice once and return its status and next action."""

    invoice = await PayPalInvoiceService().get_invoice(invoice_id)

    return {
        "invoice_id": invoice_id,
        "status": invoice.get("status"),
        "amount_due": invoice.get("due_amount", {}).get("value"),
        "next_action": decide_next_action(invoice),
    }


async def monitor_invoice(
    invoice_id: str,
    interval_seconds: int = 30,
    max_checks: int = 20,
) -> dict:
    """Poll PayPal until the invoice reaches a final status."""

    result = {}

    for check_number in range(1, max_checks + 1):
        result = await check_invoice(invoice_id)

        print(
            f"[monitor] check {check_number}: "
            f"{invoice_id} is {result['status']} "
            f"-> {result['next_action']}"
        )

        if result["status"] in FINAL_STATUSES:
            return result

        await asyncio.sleep(interval_seconds)

    return result
