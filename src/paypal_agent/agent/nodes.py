import json
from decimal import Decimal, InvalidOperation

from ollama import AsyncClient

from paypal_agent.agent.prompts import SYSTEM_PROMPT
from paypal_agent.agent.state import PaymentAgentState
from paypal_agent.config import settings


def save_conversation_turn(
    state: PaymentAgentState,
    response: str,
) -> list[dict[str, str]]:
    """Append the current user message and assistant response to history."""
    history = list(state.get("conversation_history", []))

    history.append(
        {
            "role": "user",
            "content": state["user_message"],
        }
    )
    history.append(
        {
            "role": "assistant",
            "content": response,
        }
    )

    return history


def get_llm() -> AsyncClient:
    """Create an authenticated Ollama Cloud client."""

    if not settings.ollama_api_key:
        raise RuntimeError(
            "OLLAMA_API_KEY is missing. Add it to your .env file."
        )

    return AsyncClient(
        host=settings.ollama_base_url,
        headers={
            "Authorization": f"Bearer {settings.ollama_api_key}",
        },
    )


async def understand_request(state: PaymentAgentState) -> dict:
    """Extract user intent and invoice fields using Ollama Cloud."""

    history = state.get("conversation_history", [])

    extraction_prompt = """
Return only a valid JSON object with these fields:
{
  "intent": "create_invoice" or "general",
  "customer_name": string or null,
  "customer_email": string or null,
  "amount": string or null,
  "currency": string or null,
  "description": string or null,
  "response": string
}

Rules:
- Extract only facts supplied by the user.
- Never invent invoice details.
- Use null for fields not supplied in the conversation.
- Use a three-letter currency code when explicitly provided.
- If the conversation is already about preparing an invoice,
  continue processing the invoice when the user supplies missing details.
- If the user asks to create an invoice, use intent "create_invoice".
- For unrelated requests, use intent "general".
- Do not claim an invoice has been created.
- The response should be concise.
"""

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT + "\n\n" + extraction_prompt,
        }
    ]

    for item in history:
        messages.append(
            {
                "role": item["role"],
                "content": item["content"],
            }
        )

    messages.append(
        {
            "role": "user",
            "content": state["user_message"],
        }
    )

    result = await get_llm().chat(
        model=settings.ollama_model,
        messages=messages,
        format="json",
    )

    try:
        extracted = json.loads(result.message.content or "{}")
    except (json.JSONDecodeError, TypeError):
        response = (
            "I couldn't reliably understand that request. "
            "Please rephrase it."
        )

        return {
            "response": response,
            "needs_clarification": True,
            "conversation_history": save_conversation_turn(
                state, response
            ),
        }

    updates = {}

    # If an invoice is already being prepared, a follow-up message
    # should continue that workflow instead of starting a general chat.
    existing_invoice = any(
        state.get(key)
        for key in (
            "invoice_customer_name",
            "invoice_customer_email",
            "invoice_amount",
            "invoice_currency",
            "invoice_description",
        )
    )

    if (
        extracted.get("intent") != "create_invoice"
        and not existing_invoice
    ):
        response = (
            extracted.get("response")
            or "How can I help with your PayPal payments?"
        )

        return {
            "response": response,
            "needs_clarification": False,
            "conversation_history": save_conversation_turn(
                state, response
            ),
        }

    # Store only nonempty values supplied by the model.
    field_mapping = {
        "customer_name": "invoice_customer_name",
        "customer_email": "invoice_customer_email",
        "amount": "invoice_amount",
        "currency": "invoice_currency",
        "description": "invoice_description",
    }

    for extracted_key, state_key in field_mapping.items():
        value = extracted.get(extracted_key)

        if value is not None and str(value).strip():
            updates[state_key] = str(value).strip()

    # Existing values remain in graph state when not overwritten.
    customer_name = updates.get(
        "invoice_customer_name",
        state.get("invoice_customer_name"),
    )
    customer_email = updates.get(
        "invoice_customer_email",
        state.get("invoice_customer_email"),
    )
    amount_text = updates.get(
        "invoice_amount",
        state.get("invoice_amount"),
    )
    currency = updates.get(
        "invoice_currency",
        state.get("invoice_currency"),
    )
    description = updates.get(
        "invoice_description",
        state.get("invoice_description"),
    )

    missing = []

    if not customer_name:
        missing.append("customer or business name")

    if not customer_email:
        missing.append("customer billing email")
    elif "@" not in customer_email:
        missing.append("a valid customer billing email")

    if not amount_text:
        missing.append("invoice amount")
    else:
        try:
            amount = Decimal(amount_text)

            if not amount.is_finite() or amount <= 0:
                missing.append("a positive invoice amount")
            elif amount.as_tuple().exponent < -2:
                missing.append(
                    "an amount with at most two decimal places"
                )

        except (InvalidOperation, ValueError):
            missing.append("a valid invoice amount")

    if not currency:
        missing.append("currency, such as USD")
    elif (
        len(currency) != 3
        or not currency.isalpha()
        or not currency.isascii()
    ):
        missing.append("a valid three-letter currency code")

    if not description:
        missing.append("a description of goods or services")

    if missing:
        updates["needs_clarification"] = True
        updates["pending_invoice_confirmation"] = False
        updates["invoice_confirmation_requested"] = False

        response = (
            "I can help prepare a PayPal draft invoice. "
            "Please provide: " + ", ".join(missing) + "."
        )

        updates["response"] = response
        updates["conversation_history"] = save_conversation_turn(
            state, response
        )

        return updates

    # All details are present. Ask for confirmation, but do not call PayPal.
    updates["needs_clarification"] = False
    updates["pending_invoice_confirmation"] = True
    updates["invoice_confirmation_requested"] = True

    response = (
        "Please review the invoice details:\n"
        f"- Customer: {customer_name}\n"
        f"- Email: {customer_email}\n"
        f"- Amount: {amount_text} {currency.upper()}\n"
        f"- Description: {description}\n\n"
        "Reply CONFIRM to create this PayPal draft invoice. "
        "No email will be sent to the customer at this stage."
    )

    updates["response"] = response
    updates["conversation_history"] = save_conversation_turn(
        state, response
    )

    return updates


async def confirmation_gate(state: PaymentAgentState) -> dict:
    """Enforce explicit confirmation in Python before invoice creation."""

    if not state.get("pending_invoice_confirmation"):
        response = (
            "There is no invoice awaiting confirmation. "
            "Tell me if you would like to prepare one."
        )

        return {
            "response": response,
            "needs_clarification": True,
            "conversation_history": save_conversation_turn(
                state, response
            ),
        }

    if not state.get("invoice_confirmation_requested"):
        response = "Please review the invoice details first."

        return {
            "response": response,
            "needs_clarification": True,
            "conversation_history": save_conversation_turn(
                state, response
            ),
        }

    confirmation = state["user_message"].strip().casefold()

    if confirmation != "confirm":
        if confirmation in {"cancel", "no", "stop"}:
            response = (
                "Invoice creation cancelled. "
                "No PayPal invoice was created."
            )

            return {
                "pending_invoice_confirmation": False,
                "invoice_confirmation_requested": False,
                "response": response,
                "needs_clarification": False,
                "conversation_history": save_conversation_turn(
                    state, response
                ),
            }

        response = (
            "Please reply CONFIRM to create the draft, "
            "or CANCEL to stop."
        )

        return {
            "response": response,
            "needs_clarification": True,
            "conversation_history": save_conversation_turn(
                state, response
            ),
        }

    # Do not append history here. The invoice-creation node will
    # save the final response for this CONFIRM message.
    return {
        "response": "Confirmation received. Preparing the invoice.",
        "needs_clarification": False,
    }


async def create_invoice_draft(state: PaymentAgentState) -> dict:
    """Create a PayPal draft after the confirmation gate passes."""

    from paypal_agent.services.paypal_invoice_service import (
        PayPalInvoiceService,
    )

    if state.get("user_message", "").strip().casefold() != "confirm":
        response = (
            "Invoice creation was not authorized. "
            "No invoice was created."
        )

        return {
            "response": response,
            "needs_clarification": True,
            "conversation_history": save_conversation_turn(
                state, response
            ),
        }

    if (
        not state.get("pending_invoice_confirmation")
        or not state.get("invoice_confirmation_requested")
    ):
        response = (
            "There is no confirmed invoice awaiting creation. "
            "No invoice was created."
        )

        return {
            "response": response,
            "needs_clarification": True,
            "conversation_history": save_conversation_turn(
                state, response
            ),
        }

    try:
        service = PayPalInvoiceService()

        result = await service.create_draft_invoice(
            customer_name=state["invoice_customer_name"],
            customer_email=state["invoice_customer_email"],
            amount=Decimal(state["invoice_amount"]),
            currency=state["invoice_currency"].upper(),
            description=state["invoice_description"],
        )

        invoice_id = result.get("id")

        if not invoice_id:
            raise RuntimeError(
                "PayPal did not return an invoice ID."
            )

        invoice_status = result.get("status", "DRAFT")

        response = (
            "PayPal draft invoice created successfully.\n"
            f"Invoice ID: {invoice_id}\n"
            f"Status: {invoice_status}\n"
            "The invoice has not been emailed to the customer."
        )

        return {
            "invoice_id": invoice_id,
            "invoice_status": invoice_status,
            "pending_invoice_confirmation": False,
            "invoice_confirmation_requested": False,
            "response": response,
            "needs_clarification": False,
            "conversation_history": save_conversation_turn(
                state, response
            ),
        }

    except Exception as exc:
        # Log the exception server-side without exposing credentials
        # or raw PayPal error details to the user.
        print(
            f"PayPal draft invoice creation failed: "
            f"{type(exc).__name__}: {exc}"
        )

        response = (
            "I couldn't confirm that the PayPal draft invoice "
            "was created. Please check the server logs and "
            "verify the invoice in PayPal before retrying."
        )

        return {
            "pending_invoice_confirmation": False,
            "invoice_confirmation_requested": False,
            "response": response,
            "needs_clarification": True,
            "conversation_history": save_conversation_turn(
                state, response
            ),
        }