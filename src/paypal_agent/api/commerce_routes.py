import base64
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Response

from paypal_agent.api.security import DisputeId, InvoiceId, OrderId
from paypal_agent.api.schemas import (
    AcceptDisputeRequest,
    PaymentLinkRequest,
    TrackingRequest,
)
from paypal_agent.config import settings
from paypal_agent.database import repositories
from paypal_agent.services.paypal_commerce_service import (
    PayPalCommerceService,
    user_error,
)

router = APIRouter(prefix="/api")


async def run(what: str, call):
    """Run a PayPal call and turn failures into clean HTTP errors."""

    try:
        return await call(PayPalCommerceService())

    except Exception as exc:
        print(f"PayPal {what} failed: {type(exc).__name__}: {exc}")
        message = user_error(exc)

        if message:
            # The request or the account setup is the problem; retrying won't help.
            raise HTTPException(status_code=400, detail=message) from exc

        # A network problem, an unexpected PayPal error or missing
        # configuration (e.g. PAYPAL_TRANSPORT is not mcp).
        raise HTTPException(
            status_code=502, detail=f"PayPal could not {what}."
        ) from exc


# --- Invoices -------------------------------------------------------------


@router.post("/invoices/{invoice_id}/cancel", tags=["Invoices"])
async def cancel_invoice(invoice_id: InvoiceId, delete: bool = False):
    """Cancel a sent invoice; with delete=true also remove it from the dashboard."""

    await run("cancel the invoice", lambda s: s.cancel_invoice(invoice_id))
    await repositories.upsert_invoice(invoice_id, status="CANCELLED")
    await repositories.add_event(invoice_id, f"Invoice {invoice_id} was cancelled.")

    if delete:
        await repositories.hide_invoices([invoice_id])

    return {"status": "cancelled", "invoice_id": invoice_id, "deleted": delete}


@router.post("/invoices/delete-cancelled", tags=["Invoices"])
async def delete_cancelled_invoices():
    """Remove every cancelled invoice from the dashboard."""

    items = await run("list the invoices", lambda s: s.invoices.list_invoices(page_size=100))
    cancelled = [item["id"] for item in items if item.get("status") == "CANCELLED"]
    await repositories.hide_invoices(cancelled)

    return {"status": "deleted", "count": len(cancelled)}


@router.post("/invoices/{invoice_id}/delete", tags=["Invoices"])
async def delete_invoice(invoice_id: InvoiceId):
    """Delete a draft (in PayPal too) or remove a cancelled invoice from the dashboard."""

    invoice = await run("find the invoice", lambda s: s.invoices.get_invoice(invoice_id))
    status = invoice.get("status")

    if status == "DRAFT":
        await run("delete the draft", lambda s: s.invoices.delete_draft_invoice(invoice_id))
    elif status != "CANCELLED":
        raise HTTPException(
            status_code=400,
            detail="Only drafts and cancelled invoices can be deleted. Cancel it first.",
        )

    await repositories.hide_invoices([invoice_id])

    return {"status": "deleted", "invoice_id": invoice_id}


@router.post("/invoices/{invoice_id}/reopen", tags=["Invoices"])
async def reopen_invoice(invoice_id: InvoiceId):
    """Replace a cancelled invoice with a fresh draft copy."""

    new = await run("reopen the invoice", lambda s: s.reopen_invoice(invoice_id))
    new_id = new.get("id")
    billing = (new.get("primary_recipients") or [{}])[0].get("billing_info", {})

    # PayPal MCP can't store a due date, so the monitor reads ours.
    await repositories.upsert_invoice(
        new_id,
        status=new.get("status", "DRAFT"),
        customer_name=billing.get("name", {}).get("given_name"),
        customer_email=billing.get("email_address"),
        amount=new.get("amount", {}).get("value"),
        currency=new.get("detail", {}).get("currency_code"),
        due_date=date.today() + timedelta(days=settings.default_due_days),
    )
    await repositories.hide_invoices([invoice_id])
    await repositories.add_event(
        new_id or invoice_id, f"Invoice {invoice_id} reopened as new draft {new_id}."
    )

    return {"status": "reopened", "invoice_id": new_id, "replaces": invoice_id}


@router.get("/invoices/{invoice_id}/qr.png", tags=["Invoices"])
async def invoice_qr_code(invoice_id: InvoiceId):
    """QR code image that opens the invoice's PayPal pay page."""

    png = await run("make a QR code", lambda s: s.invoice_qr_code(invoice_id))

    return Response(content=base64.b64decode(png), media_type="image/png")


@router.get("/invoices/{invoice_id}/refunds", tags=["Invoices"])
async def refund_status(invoice_id: InvoiceId):
    return await run("check the refunds", lambda s: s.refund_status(invoice_id))


@router.post("/invoices/{invoice_id}/tracking", tags=["Shipping"])
async def add_tracking(invoice_id: InvoiceId, tracking: TrackingRequest):
    await run(
        "add the tracking number",
        lambda s: s.add_tracking(invoice_id, tracking.tracking_number, tracking.carrier),
    )

    return {"status": "tracking_added", "invoice_id": invoice_id}


@router.get("/invoices/{invoice_id}/tracking", tags=["Shipping"])
async def get_tracking(invoice_id: InvoiceId):
    return await run("find the tracking", lambda s: s.get_tracking(invoice_id))


# --- Earnings -------------------------------------------------------------


@router.get("/earnings", tags=["Earnings"])
async def earnings(days: int = 30):
    return await run("work out earnings", lambda s: s.earnings(days))


# --- Disputes -------------------------------------------------------------


@router.get("/disputes", tags=["Disputes"])
async def list_disputes():
    return await run("list disputes", lambda s: s.list_disputes())


@router.get("/disputes/{dispute_id}", tags=["Disputes"])
async def get_dispute(dispute_id: DisputeId):
    return await run("find the dispute", lambda s: s.get_dispute(dispute_id))


@router.post("/disputes/{dispute_id}/accept", tags=["Disputes"])
async def accept_dispute(dispute_id: DisputeId, request: AcceptDisputeRequest):
    """Accept the buyer's claim. PayPal refunds the buyer."""

    await run("accept the claim", lambda s: s.accept_dispute(dispute_id, request.note))
    await repositories.add_event(
        dispute_id, f"Dispute {dispute_id} accepted. PayPal will refund the buyer."
    )

    return {"status": "accepted", "dispute_id": dispute_id}


# --- Pay links (orders) ---------------------------------------------------


@router.post("/payment-links", tags=["Pay links"])
async def create_payment_link(request: PaymentLinkRequest):
    return await run(
        "create the payment link",
        lambda s: s.create_payment_link(request.amount, request.currency, request.description),
    )


@router.get("/payment-links/{order_id}", tags=["Pay links"])
async def get_payment_link(order_id: OrderId):
    return await run("find the payment link", lambda s: s.get_payment_link(order_id))


@router.post("/payment-links/{order_id}/capture", tags=["Pay links"])
async def capture_payment(order_id: OrderId):
    """Collect the money after the buyer has approved the payment."""

    return await run("collect the payment", lambda s: s.capture_payment(order_id))
