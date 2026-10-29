from fastapi import APIRouter, HTTPException, Request
from paypal_agent.api.schemas import (
    ChatRequest,
    ChatResponse,
    CreateInvoiceRequest,
)

from uuid import uuid4
from paypal_agent.services.paypal_invoice_service import PayPalInvoiceService

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