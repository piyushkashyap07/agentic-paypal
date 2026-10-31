import asyncio
from datetime import date, datetime, timezone

from paypal_agent.config import settings
from paypal_agent.services.paypal_invoice_service import PayPalInvoiceService

# Statuses after which there is nothing left to watch.
FINAL_STATUSES = {
    "PAID",
    "MARKED_AS_PAID",
    "CANCELLED",
    "REFUNDED",
    "PARTIALLY_REFUNDED",
    "MARKED_AS_REFUNDED",
}

# Statuses where the customer still owes money.
OPEN_STATUSES = {"SENT", "UNPAID", "PARTIALLY_PAID", "SCHEDULED"}

# Recent things the monitor noticed or did, newest last.
# Kept in memory, so the list resets when the server restarts.
events: list[dict] = []

# Last status seen for each invoice, used to spot changes.
_last_status: dict[str, str] = {}

# Date each invoice was last reminded, so we remind at most once a day.
_last_reminder: dict[str, date] = {}


def record_event(invoice_id: str, message: str) -> None:
    """Remember something the monitor noticed or did."""

    events.append(
        {
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "invoice_id": invoice_id,
            "message": message,
        }
    )

    del events[:-100]
    print(f"[monitor] {invoice_id}: {message}")


def decide_next_action(invoice: dict) -> str:
    """Decide what the agent should do next for an invoice."""

    status = invoice.get("status", "")

    if status in {"PAID", "MARKED_AS_PAID"}:
        return "notify_paid"

    if status in FINAL_STATUSES:
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


def summarize_invoice(invoice: dict) -> dict:
    """Pick out the invoice fields the agent and UI need."""

    detail = invoice.get("detail", {})
    recipients = invoice.get("primary_recipients") or [{}]

    return {
        "invoice_id": invoice.get("id"),
        "status": invoice.get("status"),
        "customer_email": recipients[0]
        .get("billing_info", {})
        .get("email_address"),
        "amount": invoice.get("amount", {}).get("value"),
        "currency": detail.get("currency_code"),
        "amount_due": invoice.get("due_amount", {}).get("value"),
        "due_date": detail.get("payment_term", {}).get("due_date"),
        "pay_link": detail.get("metadata", {}).get("recipient_view_url"),
        "next_action": decide_next_action(invoice),
    }


async def check_invoice(invoice_id: str) -> dict:
    """Check an invoice once and return its status and next action."""

    invoice = await PayPalInvoiceService().get_invoice(invoice_id)

    return summarize_invoice(invoice)


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


async def check_all_invoices() -> None:
    """Check every open invoice once and act on what has changed."""

    service = PayPalInvoiceService()

    for item in await service.list_invoices(page_size=50):
        invoice_id = item["id"]
        status = item.get("status", "")
        previous = _last_status.get(invoice_id)
        _last_status[invoice_id] = status

        # The first pass only learns the current statuses.
        if previous is not None and previous != status:
            record_event(
                invoice_id,
                f"Status changed from {previous} to {status}.",
            )

        if status not in OPEN_STATUSES:
            continue

        # The list response leaves out the due date, so fetch the
        # full invoice before deciding whether it is overdue.
        invoice = await service.get_invoice(invoice_id)

        if decide_next_action(invoice) != "send_reminder":
            continue

        if not settings.monitor_auto_remind:
            continue

        if _last_reminder.get(invoice_id) == date.today():
            continue

        await service.send_reminder(invoice_id)
        _last_reminder[invoice_id] = date.today()
        record_event(invoice_id, "Invoice is overdue. Reminder sent.")


async def run_monitor_loop() -> None:
    """Keep checking invoices in the background until cancelled."""

    print(
        "[monitor] started, checking every "
        f"{settings.monitor_interval_seconds} seconds"
    )

    while True:
        try:
            await check_all_invoices()

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            # One failed check should not stop future checks.
            print(f"[monitor] check failed: {type(exc).__name__}: {exc}")

        await asyncio.sleep(settings.monitor_interval_seconds)
