import json
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from ollama import AsyncClient

from paypal_agent.agent.prompts import SYSTEM_PROMPT
from paypal_agent.agent.state import PaymentAgentState
from paypal_agent.config import settings
from paypal_agent.database import repositories


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


# Seconds to wait for the model, and how many past messages it sees.
LLM_TIMEOUT_SECONDS = 60
MAX_HISTORY_MESSAGES = 20


def get_llm() -> AsyncClient:
    """Create an authenticated Ollama Cloud client."""

    if not settings.ollama_api_key:
        raise RuntimeError(
            "OLLAMA_API_KEY is missing. Add it to your .env file."
        )

    return AsyncClient(
        host=settings.ollama_base_url,
        # Never let a stalled model hang the chat forever.
        timeout=LLM_TIMEOUT_SECONDS,
        headers={
            "Authorization": f"Bearer {settings.ollama_api_key}",
        },
    )


def normalize_reply(text: str) -> str:
    """Make short replies comparable: "Confirm!", " CONFIRM. " -> "confirm"."""

    return " ".join(text.casefold().strip(" \t\n.!?").split())


PLAN_STEPS = [
    "Create a draft invoice",
    "Send it to the customer",
    "Watch for payment and chase it if it goes overdue",
]


def plan_text(done: int) -> str:
    """Show the agent's plan with progress: done steps, the current one, the rest."""

    lines = []

    for index, step in enumerate(PLAN_STEPS):
        mark = "done" if index < done else "next" if index == done else "later"
        symbol = {"done": "[x]", "next": "[>]", "later": "[ ]"}[mark]
        lines.append(f"{symbol} {index + 1}. {step}")

    return "My plan:\n" + "\n".join(lines)


async def best_effort(coro) -> None:
    """Run a persistence call; a database problem must not break the chat."""

    try:
        await coro
    except Exception as exc:
        print(f"Could not save to the database: {type(exc).__name__}: {exc}")


INVOICE_ACTIONS = {
    "send_invoice",
    "check_status",
    "send_reminder",
    "refund",
    "cancel_invoice",
    "qr_code",
    "refund_status",
    "add_tracking",
    "get_tracking",
}

# Actions about the whole PayPal account, not one invoice.
ACCOUNT_ACTIONS = {
    "earnings",
    "list_disputes",
    "explain_dispute",
    "accept_dispute",
    "create_payment_link",
    "check_payment_link",
}

# Extracted fields passed on to the action nodes as action_args.
ACTION_ARG_KEYS = (
    "amount",
    "currency",
    "description",
    "dispute_id",
    "tracking_number",
    "carrier",
    "period_days",
)


CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}


def currency_from_symbol(text: str) -> str | None:
    """Return the currency implied by a symbol next to a number, if any."""

    match = re.search(r"([$€£])\s?\d", text)

    return CURRENCY_SYMBOLS[match.group(1)] if match else None


async def understand_request(state: PaymentAgentState) -> dict:
    """Understand the message and clear any stale follow-up action."""

    updates = await _understand_message(state)
    updates.setdefault("requested_action", "")

    return updates


async def _understand_message(state: PaymentAgentState) -> dict:
    """Extract user intent and invoice fields using Ollama Cloud."""

    history = state.get("conversation_history", [])

    extraction_prompt = """
Return only a valid JSON object with these fields:
{
  "intent": "create_invoice", "send_invoice", "check_status",
            "send_reminder", "refund", "explain_unpaid",
            "cancel_invoice", "qr_code", "refund_status",
            "add_tracking", "get_tracking", "earnings",
            "list_disputes", "explain_dispute", "accept_dispute",
            "create_payment_link", "check_payment_link" or "general",
  "customer_name": string or null,
  "customer_email": string or null,
  "amount": string or null,
  "currency": string or null,
  "description": string or null,
  "due_in_days": integer or null,
  "dispute_id": string or null,
  "tracking_number": string or null,
  "carrier": string or null,
  "period_days": integer or null,
  "response": string
}

Rules:
- Extract only facts supplied by the user.
- Never invent invoice details.
- Use null for fields not supplied in the conversation.
- The description is the work or goods the user mentions, however casually.
  "I finished the logo for Bluebird" -> "Logo design";
  "Acme owes me for the website" -> "Website work".
  This is a fact the user supplied, not an invented detail.
- The customer is who the work was for or who owes the money
  ("for Bluebird Cafe", "Acme owes me").
- Use a three-letter currency code when explicitly provided.
- If the conversation is already about preparing an invoice,
  continue processing the invoice when the user supplies missing details.
- If the user asks to create an invoice, use intent "create_invoice".
- If the user asks to send or email the invoice, use "send_invoice".
- If the user asks whether the invoice is paid or its status,
  use "check_status".
- If the user asks to remind or chase the customer, use "send_reminder".
- If the user asks to refund or return the money, use "refund".
- If the user asks why they have not been paid, why the customer has not
  paid, or what is going on with an unpaid invoice, use "explain_unpaid".
- If the user asks to cancel or void the invoice, use "cancel_invoice".
- If the user asks for a QR code, use "qr_code".
- If the user asks whether a refund went through or its status,
  use "refund_status".
- If the user gives a shipment tracking number, use "add_tracking"
  (tracking_number, carrier such as UPS, FEDEX, USPS, DHL).
- If the user asks where a shipment is or for tracking info,
  use "get_tracking".
- If the user asks how much they earned, received or made, use "earnings".
  period_days: "this week" -> 7, "this month" -> 30, "this year" -> 365.
- If the user asks about disputes, claims or chargebacks in general,
  use "list_disputes". About one dispute (or "explain the dispute"),
  use "explain_dispute"; to accept or give in on one, use
  "accept_dispute". Put an id like "PP-D-12345" in dispute_id.
- If the user wants a payment link, checkout link or a quick way to get
  paid without an invoice or customer email, use "create_payment_link"
  (amount, currency, description). If they ask whether the link was paid,
  or to collect that payment, use "check_payment_link".
- due_in_days is how many days from today the invoice is due, e.g. "net 30"
  or "due in two weeks". Use null when the user did not say.
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

    # Only recent turns: long chats would otherwise grow every request
    # until the model gets slow or rejects it.
    for item in history[-MAX_HISTORY_MESSAGES:]:
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

        # Valid JSON can still be a list or a string; we need an object.
        if not isinstance(extracted, dict):
            raise TypeError("expected a JSON object")
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

    # Explaining an unpaid invoice also works for invoices from earlier chats.
    if extracted.get("intent") == "explain_unpaid":
        return {
            "requested_action": "explain_unpaid",
            "needs_clarification": False,
        }

    action_args = {
        key: extracted.get(key)
        for key in ACTION_ARG_KEYS
        if extracted.get(key) not in (None, "")
    }

    # Account-wide actions don't need an invoice in this conversation.
    if extracted.get("intent") in ACCOUNT_ACTIONS:
        return {
            "requested_action": extracted["intent"],
            "action_args": action_args,
            "needs_clarification": False,
        }

    # Follow-up actions work on the invoice created in this conversation.
    if extracted.get("intent") in INVOICE_ACTIONS:
        if not state.get("invoice_id"):
            response = (
                "There is no invoice in this conversation yet. "
                "Tell me who to invoice and for how much."
            )

            return {
                "response": response,
                "needs_clarification": True,
                "conversation_history": save_conversation_turn(
                    state, response
                ),
            }

        return {
            "requested_action": extracted["intent"],
            "action_args": action_args,
            "needs_clarification": False,
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

    # "$450" already says the currency; don't make the user repeat it.
    if not updates.get("invoice_currency") and not state.get("invoice_currency"):
        symbol_currency = currency_from_symbol(state["user_message"])

        if symbol_currency:
            updates["invoice_currency"] = symbol_currency

    due_in_days = extracted.get("due_in_days")

    if isinstance(due_in_days, (int, float)) and 0 <= due_in_days <= 365:
        updates["invoice_due_date"] = (
            date.today() + timedelta(days=int(due_in_days))
        ).isoformat()

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

    remembered = False

    if customer_name and not customer_email:
        known_email = await repositories.find_customer_email(customer_name)

        if known_email:
            customer_email = known_email
            updates["invoice_customer_email"] = known_email
            remembered = True

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

    due_date = updates.get(
        "invoice_due_date", state.get("invoice_due_date")
    )

    if not due_date:
        due_date = (
            date.today() + timedelta(days=settings.default_due_days)
        ).isoformat()
        due_note = f" (default {settings.default_due_days} days; tell me if you want different terms)"
        updates["invoice_due_date"] = due_date
    else:
        due_note = ""

    email_note = (
        " (remembered from a previous invoice)" if remembered else ""
    )

    # All details are present. Ask for confirmation, but do not call PayPal.
    updates["needs_clarification"] = False
    updates["pending_invoice_confirmation"] = True
    updates["invoice_confirmation_requested"] = True

    response = (
        "Please review the invoice details:\n"
        f"- Customer: {customer_name}\n"
        f"- Email: {customer_email}{email_note}\n"
        f"- Amount: {amount_text} {currency.upper()}\n"
        f"- Due: {due_date}{due_note}\n"
        f"- Description: {description}\n\n"
        f"{plan_text(0)}\n\n"
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

    confirmation = normalize_reply(state["user_message"])

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

    if normalize_reply(state.get("user_message", "")) != "confirm":
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
            due_date=(
                date.fromisoformat(state["invoice_due_date"])
                if state.get("invoice_due_date")
                else None
            ),
        )

        invoice_id = result.get("id")

        if not invoice_id:
            raise RuntimeError(
                "PayPal did not return an invoice ID."
            )

        invoice_status = result.get("status", "DRAFT")

        await best_effort(
            repositories.upsert_invoice(
                invoice_id,
                customer_name=state["invoice_customer_name"],
                customer_email=state["invoice_customer_email"],
                amount=state["invoice_amount"],
                currency=state["invoice_currency"].upper(),
                description=state["invoice_description"],
                status=invoice_status,
                due_date=(
                    date.fromisoformat(state["invoice_due_date"])
                    if state.get("invoice_due_date")
                    else None
                ),
            )
        )
        await best_effort(
            repositories.remember_customer(
                state["invoice_customer_name"],
                state["invoice_customer_email"],
            )
        )

        response = (
            "PayPal draft invoice created successfully.\n"
            f"Invoice ID: {invoice_id}\n"
            f"Status: {invoice_status}\n"
            "The invoice has not been emailed to the customer.\n\n"
            f"{plan_text(1)}\n\n"
            "Reply SEND to email it."
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

STATUS_EXPLANATIONS = {
    "DRAFT": "is a draft and has not been sent yet",
    "SENT": "has been sent and is waiting for payment",
    "UNPAID": "has been sent and is waiting for payment",
    "PARTIALLY_PAID": "has been partly paid",
    "PAID": "has been paid",
    "MARKED_AS_PAID": "has been marked as paid",
    "CANCELLED": "has been cancelled",
    "REFUNDED": "has been refunded",
    "PARTIALLY_REFUNDED": "has been partly refunded",
}


def describe_invoice(summary: dict) -> str:
    """Explain an invoice status in plain language."""

    status = summary.get("status") or "UNKNOWN"
    explanation = STATUS_EXPLANATIONS.get(
        status, f"has status {status}"
    )

    text = (
        f"Invoice {summary['invoice_id']} {explanation}.\n"
        f"Amount due: {summary.get('amount_due')} "
        f"{summary.get('currency')}"
    )

    if summary.get("next_action") == "send_reminder":
        text += "\nThe due date has passed. Reply REMIND to chase it."

    return text


def action_result(
    state: PaymentAgentState,
    response: str,
    **updates,
) -> dict:
    """Build the state update for a finished follow-up action."""

    return {
        **updates,
        "requested_action": "",
        "response": response,
        "needs_clarification": False,
        "conversation_history": save_conversation_turn(state, response),
    }


async def send_invoice_node(state: PaymentAgentState) -> dict:
    """Email the conversation's draft invoice to the customer."""

    from paypal_agent.services.paypal_invoice_service import (
        PayPalInvoiceService,
    )
    from paypal_agent.workers.payment_monitor import check_invoice

    invoice_id = state["invoice_id"]

    try:
        await PayPalInvoiceService().send_invoice(invoice_id)
        summary = await check_invoice(invoice_id)

    except ValueError as exc:
        return action_result(state, f"I couldn't send the invoice: {exc}")

    except Exception as exc:
        print(f"PayPal invoice send failed: {type(exc).__name__}: {exc}")

        return action_result(
            state,
            "I couldn't confirm that the invoice was sent. "
            "Please check it in PayPal before retrying.",
        )

    response = (
        f"Invoice {invoice_id} was emailed to the customer.\n"
        f"Payment link: {summary.get('pay_link')}\n\n"
        f"{plan_text(2)}\n"
        "I'll post here when it's paid or if I have to chase it."
    )

    await best_effort(
        repositories.upsert_invoice(
            invoice_id, status=summary.get("status", "SENT")
        )
    )

    return action_result(
        state,
        response,
        invoice_status=summary.get("status", "SENT"),
    )


async def check_status_node(state: PaymentAgentState) -> dict:
    """Look up the latest PayPal status of the conversation's invoice."""

    from paypal_agent.workers.payment_monitor import check_invoice

    try:
        summary = await check_invoice(state["invoice_id"])

    except Exception as exc:
        print(f"PayPal invoice lookup failed: {type(exc).__name__}: {exc}")

        return action_result(
            state,
            "I couldn't reach PayPal to check the invoice. Try again soon.",
        )

    return action_result(
        state,
        describe_invoice(summary),
        invoice_status=summary.get("status", ""),
    )


async def send_reminder_node(state: PaymentAgentState) -> dict:
    """Send a payment reminder for the conversation's invoice."""

    from paypal_agent.services.paypal_invoice_service import (
        PayPalInvoiceService,
    )
    from paypal_agent.workers.payment_monitor import check_invoice

    invoice_id = state["invoice_id"]

    try:
        summary = await check_invoice(invoice_id)

        if summary.get("status") not in {"SENT", "UNPAID", "PARTIALLY_PAID"}:
            return action_result(
                state,
                "A reminder isn't needed. " + describe_invoice(summary),
            )

        await PayPalInvoiceService().send_reminder(invoice_id)

    except Exception as exc:
        print(f"PayPal reminder failed: {type(exc).__name__}: {exc}")

        return action_result(
            state,
            "I couldn't confirm that the reminder was sent.",
        )

    return action_result(
        state,
        f"Reminder sent to the customer for invoice {invoice_id}.",
    )


async def request_refund_node(state: PaymentAgentState) -> dict:
    """Ask the user to confirm before any money is refunded."""

    from paypal_agent.workers.payment_monitor import check_invoice

    try:
        summary = await check_invoice(state["invoice_id"])

    except Exception as exc:
        print(f"PayPal invoice lookup failed: {type(exc).__name__}: {exc}")

        return action_result(
            state,
            "I couldn't reach PayPal to check the invoice. Try again soon.",
        )

    if summary.get("status") not in {"PAID", "PARTIALLY_REFUNDED"}:
        return action_result(
            state,
            "Only paid invoices can be refunded. "
            + describe_invoice(summary),
        )

    response = (
        f"This will refund the payment for invoice {summary['invoice_id']} "
        f"({summary.get('amount')} {summary.get('currency')}) "
        "back to the customer.\n"
        "Reply CONFIRM REFUND to continue, or CANCEL to stop."
    )

    return action_result(
        state,
        response,
        pending_refund_confirmation=True,
    )


async def refund_node(state: PaymentAgentState) -> dict:
    """Refund the invoice payment after explicit confirmation."""

    from paypal_agent.services.paypal_invoice_service import (
        PayPalInvoiceService,
    )

    message = normalize_reply(state.get("user_message", ""))

    if message != "confirm refund":
        return action_result(
            state,
            "Refund cancelled. No money was moved.",
            pending_refund_confirmation=False,
        )

    if not state.get("pending_refund_confirmation"):
        return action_result(
            state,
            "There is no refund waiting for confirmation.",
        )

    try:
        result = await PayPalInvoiceService().refund_invoice(
            state["invoice_id"]
        )

    except ValueError as exc:
        return action_result(
            state,
            f"I couldn't refund the payment: {exc}",
            pending_refund_confirmation=False,
        )

    except Exception as exc:
        print(f"PayPal refund failed: {type(exc).__name__}: {exc}")

        return action_result(
            state,
            "I couldn't confirm that the refund went through. "
            "Please check PayPal before retrying.",
            pending_refund_confirmation=False,
        )

    return action_result(
        state,
        f"Refund {result.get('id')} is {result.get('status')}. "
        "The money is on its way back to the customer.",
        pending_refund_confirmation=False,
    )


async def explain_unpaid_node(state: PaymentAgentState) -> dict:
    """Explain, from PayPal's data, why an invoice has not been paid."""

    from paypal_agent.services.payment_explainer import (
        build_facts,
        plain_summary,
    )
    from paypal_agent.services.paypal_invoice_service import (
        PayPalInvoiceService,
    )

    invoice_id = state.get("invoice_id")

    if not invoice_id:
        latest = await repositories.latest_open_invoice()
        invoice_id = latest.invoice_id if latest else None

    if not invoice_id:
        return action_result(
            state,
            "I don't see any unpaid invoice right now. "
            "Tell me who to invoice and for how much.",
        )

    try:
        invoice = await PayPalInvoiceService().get_invoice(invoice_id)
        record = await repositories.get_invoice_record(invoice_id)
        facts = build_facts(invoice, record)

    except Exception as exc:
        print(f"PayPal invoice lookup failed: {type(exc).__name__}: {exc}")

        return action_result(
            state,
            "I couldn't reach PayPal to look into that. Try again soon.",
        )

    # The LLM only rewords facts we already worked out. If it fails,
    # the plain summary is just as correct.
    try:
        result = await get_llm().chat(
            model=settings.ollama_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You explain to a freelancer why an invoice has not "
                        "been paid. Use ONLY the facts in the JSON. Do not "
                        "invent causes, dates or amounts. No greeting. Be brief "
                        "(at most 4 sentences) and friendly. End with one "
                        "sentence for the suggested action: send_invoice -> "
                        "'Reply SEND to email it.'; send_reminder -> 'Reply "
                        "REMIND and I'll chase them.'; wait -> 'Nothing to do "
                        "yet; I'm still watching it.'"
                    ),
                },
                {"role": "user", "content": json.dumps(facts)},
            ],
        )
        response = (result.message.content or "").strip() or plain_summary(facts)

    except Exception as exc:
        print(f"Explainer LLM failed: {type(exc).__name__}: {exc}")
        response = plain_summary(facts)

    return action_result(state, response, invoice_id=invoice_id)


async def nothing_pending_node(state: PaymentAgentState) -> dict:
    """Answer a stray CONFIRM/CANCEL so it can never restart a workflow."""

    response = (
        "Nothing is waiting for your confirmation right now. "
        "Tell me who to invoice and for how much to start one."
    )

    return {
        "response": response,
        "needs_clarification": False,
        "conversation_history": save_conversation_turn(state, response),
    }
