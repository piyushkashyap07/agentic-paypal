import json

from fastapi import APIRouter, HTTPException, Request

from paypal_agent.config import settings
from paypal_agent.services.paypal_invoice_service import PayPalInvoiceService
from paypal_agent.workers.payment_monitor import sync_invoice

router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])


def invoice_id_from_event(event: dict) -> str | None:
    """Invoice events carry the invoice at resource.invoice.id (or resource.id)."""

    resource = event.get("resource") or {}
    invoice = resource.get("invoice") or {}

    return invoice.get("id") or resource.get("id")


@router.post("/paypal")
async def paypal_webhook(request: Request):
    """React to PayPal invoice events immediately instead of waiting for the poll.

    The event is never trusted: we verify it with PayPal, then re-read the
    invoice from PayPal and sync from that, so a forged body cannot fake a payment.
    """

    raw = await request.body()

    try:
        event = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON.") from exc

    service = PayPalInvoiceService()

    if settings.paypal_webhook_id:
        try:
            verified = await service.verify_webhook(
                {key.lower(): value for key, value in request.headers.items()},
                event,
            )
        except Exception as exc:
            print(f"Webhook verification failed: {type(exc).__name__}: {exc}")
            raise HTTPException(
                status_code=502, detail="Could not verify the webhook."
            ) from exc

        if not verified:
            raise HTTPException(status_code=401, detail="Invalid webhook signature.")

    elif not settings.webhook_allow_unverified:
        raise HTTPException(
            status_code=503,
            detail="Webhooks are not configured. Set PAYPAL_WEBHOOK_ID.",
        )

    event_type = str(event.get("event_type", ""))

    if not event_type.startswith("INVOICING.INVOICE."):
        return {"status": "ignored", "event_type": event_type}

    invoice_id = invoice_id_from_event(event)

    if not invoice_id:
        return {"status": "ignored", "reason": "no invoice id"}

    try:
        invoice = await service.get_invoice(invoice_id)
        await sync_invoice(service, invoice_id, invoice.get("status", ""))

    except Exception as exc:
        print(f"Webhook sync failed: {type(exc).__name__}: {exc}")
        # 5xx makes PayPal retry the delivery later.
        raise HTTPException(status_code=502, detail="Could not sync the invoice.") from exc

    return {"status": "synced", "invoice_id": invoice_id}
