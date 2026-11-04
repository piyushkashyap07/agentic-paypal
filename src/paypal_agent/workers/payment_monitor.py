import asyncio
from datetime import date

from paypal_agent.config import settings
from paypal_agent.database import repositories
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

async def record_event(invoice_id: str, message: str) -> None:
    """Remember something the monitor noticed or did (stored in SQLite)."""

    print(f"[monitor] {invoice_id}: {message}")

    try:
        await repositories.add_event(invoice_id, message)
    except Exception as exc:
        # Losing an activity line must never stop the monitor.
        print(f"[monitor] could not save event: {type(exc).__name__}: {exc}")


def decide_next_action(invoice: dict, simulate_overdue: bool = False) -> str:
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

    if simulate_overdue:
        return "send_reminder"

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


def status_message(record, invoice_id: str, status: str, previous: str) -> str:
    """Plain-language line for a status change."""

    who = (record.customer_name if record else None) or "The customer"
    money = ""

    if record and record.amount:
        money = f" ({record.amount} {record.currency})"

    if status in {"PAID", "MARKED_AS_PAID"}:
        return f"{who} paid invoice {invoice_id}{money}."

    if status in {"REFUNDED", "PARTIALLY_REFUNDED", "MARKED_AS_REFUNDED"}:
        return f"Invoice {invoice_id}{money} was refunded."

    if status == "CANCELLED":
        return f"Invoice {invoice_id} was cancelled."

    return f"Invoice {invoice_id} changed from {previous} to {status}."


async def check_all_invoices() -> None:
    """Check every open invoice once and act on what has changed."""

    service = PayPalInvoiceService()

    for item in await service.list_invoices(page_size=50):
        invoice_id = item["id"]
        status = item.get("status", "")
        record = await repositories.get_invoice_record(invoice_id)

        if record is None:
            # An invoice we haven't seen (e.g. made in PayPal directly):
            # learn it quietly, no "changed" event.
            record = await repositories.upsert_invoice(invoice_id, status=status)
        elif record.status != status:
            previous = record.status
            await repositories.upsert_invoice(invoice_id, status=status)
            await record_event(
                invoice_id, status_message(record, invoice_id, status, previous)
            )

        if status not in OPEN_STATUSES:
            continue

        # The list response leaves out the due date, so fetch the
        # full invoice before deciding whether it is overdue.
        invoice = await service.get_invoice(invoice_id)

        if decide_next_action(invoice, record.simulate_overdue) != "send_reminder":
            continue

        if not settings.monitor_auto_remind:
            continue

        # Persisted, so a restart cannot cause a second reminder the same day.
        if record.last_reminder_on == date.today():
            continue

        await service.send_reminder(invoice_id)
        await repositories.mark_reminded(invoice_id, date.today())
        await record_event(invoice_id, "Invoice is overdue. Reminder sent.")


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
