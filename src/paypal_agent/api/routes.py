from fastapi import APIRouter, HTTPException, Request
from paypal_agent.api.security import InvoiceId
from paypal_agent.api.schemas import (
    ChatRequest,
    ChatResponse,
    CreateInvoiceRequest,
    RefundRequest,
)

from uuid import uuid4
from paypal_agent.config import settings
from paypal_agent.database import repositories
from paypal_agent.services.paypal_invoice_service import PayPalInvoiceService
from paypal_agent.workers.payment_monitor import (
    check_all_invoices,
    check_invoice,
    summarize_invoice,
)

router = APIRouter(prefix="/api", tags=["Agent"])

@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    http_request: Request,
) -> ChatResponse:
    thread_id = request.thread_id or str(uuid4())
    payment_agent = http_request.app.state.payment_agent

    try:
        result = await payment_agent.ainvoke(
            {
                "user_message": request.message,
            },
            config={
                "configurable": {
                    "thread_id": thread_id,
                }
            },
        )

        return ChatResponse(
            message=result["response"],
            thread_id=thread_id,
            status="success",
        )

    except Exception as exc:
        print(
            f"Agent request failed: {type(exc).__name__}: {exc}"
        )

        # Out of model credits / rate limited / model down: say so plainly,
        # and point to the shortcuts that work without the AI.
        if getattr(exc, "status_code", None) in {402, 429, 502, 503}:
            raise HTTPException(
                status_code=503,
                detail=(
                    "The AI model is unavailable right now (usage limit or "
                    "outage). Shortcuts still work: SEND, STATUS, REMIND, "
                    "REFUND, WHY, QR."
                ),
            ) from exc

        raise HTTPException(
            status_code=500,
            detail="The AI agent could not process the request.",
        ) from exc
        
@router.post("/invoices/draft", tags=["Invoices"])
async def create_invoice_draft(
    invoice: CreateInvoiceRequest,
):
    service = PayPalInvoiceService()

    try:
        result = await service.create_draft_invoice(
            customer_email=str(invoice.customer_email),
            amount=invoice.amount,
            currency=invoice.currency,
            description=invoice.description,
            customer_name=invoice.customer_name,
        )

        if result.get("id"):
            try:
                await repositories.upsert_invoice(
                    result["id"],
                    customer_name=invoice.customer_name,
                    customer_email=str(invoice.customer_email),
                    amount=f"{invoice.amount:.2f}",
                    currency=invoice.currency.upper(),
                    description=invoice.description,
                    status=result.get("status", "DRAFT"),
                )
                await repositories.remember_customer(
                    invoice.customer_name, str(invoice.customer_email)
                )
            except Exception as exc:
                print(f"Could not save to the database: {type(exc).__name__}: {exc}")

        return {
            "status": "created",
            "invoice_id": result.get("id"),
            "paypal_status": result.get("status", "DRAFT"),
            "message": "PayPal draft invoice created successfully.",
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        # Log details for local debugging without returning secrets
        # or raw PayPal responses to the API caller.
        print(
            f"PayPal invoice creation failed: "
            f"{type(exc).__name__}: {exc}"
        )

        raise HTTPException(
            status_code=502,
            detail="PayPal could not create the invoice draft.",
        ) from exc


@router.post("/invoices/{invoice_id}/send", tags=["Invoices"])
async def send_invoice(invoice_id: InvoiceId):
    try:
        await PayPalInvoiceService().send_invoice(invoice_id)
        return await check_invoice(invoice_id)

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except Exception as exc:
        print(f"PayPal invoice send failed: {type(exc).__name__}: {exc}")

        raise HTTPException(
            status_code=502,
            detail="PayPal could not send the invoice.",
        ) from exc


@router.get("/invoices/{invoice_id}", tags=["Invoices"])
async def get_invoice_status(invoice_id: InvoiceId):
    try:
        return await check_invoice(invoice_id)

    except Exception as exc:
        print(f"PayPal invoice lookup failed: {type(exc).__name__}: {exc}")

        raise HTTPException(
            status_code=502,
            detail="PayPal could not return the invoice status.",
        ) from exc


@router.post("/invoices/{invoice_id}/remind", tags=["Invoices"])
async def send_invoice_reminder(invoice_id: InvoiceId):
    try:
        await PayPalInvoiceService().send_reminder(invoice_id)

        return {
            "status": "reminder_sent",
            "invoice_id": invoice_id,
        }

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except Exception as exc:
        print(f"PayPal reminder failed: {type(exc).__name__}: {exc}")

        raise HTTPException(
            status_code=502,
            detail="PayPal could not send the reminder.",
        ) from exc


@router.get("/invoices", tags=["Invoices"])
async def list_invoices():
    try:
        items = await PayPalInvoiceService().list_invoices()
        simulated = await repositories.simulated_overdue_ids()

        return [
            {
                **summarize_invoice(item),
                "simulated_overdue": item.get("id") in simulated,
            }
            for item in items
        ]

    except Exception as exc:
        print(f"PayPal invoice list failed: {type(exc).__name__}: {exc}")

        raise HTTPException(
            status_code=502,
            detail="PayPal could not list the invoices.",
        ) from exc


@router.post("/invoices/{invoice_id}/refund", tags=["Invoices"])
async def refund_invoice(invoice_id: InvoiceId, refund: RefundRequest):
    try:
        result = await PayPalInvoiceService().refund_invoice(
            invoice_id,
            amount=refund.amount,
        )

        return {
            "status": "refunded",
            "invoice_id": invoice_id,
            "refund_id": result.get("id"),
            "refund_status": result.get("status"),
        }

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except Exception as exc:
        print(f"PayPal refund failed: {type(exc).__name__}: {exc}")

        raise HTTPException(
            status_code=502,
            detail="PayPal could not refund the payment.",
        ) from exc


@router.get("/events", tags=["Monitor"])
async def list_events(after: int = 0):
    """Events newer than `after` (an event id). Omit it for the latest ones."""

    return await repositories.list_events(after=after)


def require_demo_mode() -> None:
    if settings.app_env != "development":
        raise HTTPException(status_code=404, detail="Not found.")


@router.post("/monitor/run", tags=["Monitor"])
async def run_monitor_now():
    """Run one monitor pass immediately instead of waiting for the timer."""

    require_demo_mode()

    try:
        failed = await check_all_invoices()
        return {"status": "checked", "failed": failed}

    except Exception as exc:
        print(f"Monitor run failed: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=502, detail="The check failed.") from exc


@router.post("/demo/invoices/{invoice_id}/simulate-overdue", tags=["Demo"])
async def simulate_overdue(invoice_id: InvoiceId):
    """Demo only: treat this invoice as overdue and let the monitor react.

    We cannot wait days in a live demo. The monitor then does exactly what
    it would do for a really overdue invoice: send a real PayPal reminder.
    """

    require_demo_mode()

    await repositories.upsert_invoice(invoice_id, simulate_overdue=True)

    try:
        failed = await check_all_invoices()

    except Exception as exc:
        print(f"Monitor run failed: {type(exc).__name__}: {exc}")
        failed = [invoice_id]

    if invoice_id in failed:
        raise HTTPException(
            status_code=502,
            detail="The invoice is marked overdue, but the check failed.",
        )

    return {"status": "overdue_simulated", "invoice_id": invoice_id}
