from paypal_agent.agent.nodes import action_result, normalize_reply
from paypal_agent.agent.state import PaymentAgentState
from paypal_agent.database import repositories
from paypal_agent.services.paypal_commerce_service import (
    PayPalCommerceService,
    summarize_dispute,
    user_error,
)

# Dispute reasons in plain language, with what the seller can do.
DISPUTE_REASONS = {
    "MERCHANDISE_OR_SERVICE_NOT_RECEIVED": (
        "the buyer says they never received it",
        "If you delivered, send proof (tracking or delivery files) in "
        "PayPal's Resolution Center.",
    ),
    "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED": (
        "the buyer says it wasn't as described",
        "Talk to the buyer first; a partial refund often settles it.",
    ),
    "UNAUTHORISED": (
        "the account holder says they didn't make this payment",
        "Send any proof that the buyer ordered the work (emails, sign-off).",
    ),
    "CREDIT_NOT_PROCESSED": (
        "the buyer says a promised refund never arrived",
        "If you already refunded, share the refund details.",
    ),
    "DUPLICATE_TRANSACTION": (
        "the buyer says they were charged twice",
        "If it really is a duplicate, accepting is the quickest fix.",
    ),
    "INCORRECT_AMOUNT": (
        "the buyer says the amount was wrong",
        "Check the invoice amount against what you agreed.",
    ),
}


def friendly(exc: Exception, fallback: str) -> str:
    """The user-facing reason a PayPal action failed."""

    print(f"PayPal action failed: {type(exc).__name__}: {exc}")

    return user_error(exc) or fallback


def args(state: PaymentAgentState) -> dict:
    return state.get("action_args") or {}


# --- Invoice actions -------------------------------------------------------


async def request_cancel_node(state: PaymentAgentState) -> dict:
    """Cancelling tells the customer, so ask first."""

    return action_result(
        state,
        f"This will cancel invoice {state['invoice_id']} and email the "
        "customer that no payment is needed.\n"
        "Reply CONFIRM CANCEL to continue, or STOP to keep it.",
        pending_cancel_confirmation=True,
    )


async def cancel_invoice_node(state: PaymentAgentState) -> dict:
    """Cancel the invoice after CONFIRM CANCEL."""

    if normalize_reply(state.get("user_message", "")) != "confirm cancel":
        return action_result(
            state,
            "Okay, the invoice was not cancelled.",
            pending_cancel_confirmation=False,
        )

    invoice_id = state["invoice_id"]

    try:
        await PayPalCommerceService().cancel_invoice(invoice_id)

    except Exception as exc:
        return action_result(
            state,
            friendly(exc, "I couldn't confirm the invoice was cancelled."),
            pending_cancel_confirmation=False,
        )

    await repositories.upsert_invoice(invoice_id, status="CANCELLED")
    await repositories.add_event(invoice_id, f"Invoice {invoice_id} was cancelled.")

    return action_result(
        state,
        f"Invoice {invoice_id} is cancelled and the customer was told.",
        pending_cancel_confirmation=False,
        invoice_status="CANCELLED",
    )


async def qr_code_node(state: PaymentAgentState) -> dict:
    """Give a QR code that opens the invoice's pay page."""

    invoice_id = state["invoice_id"]

    try:
        # Made here only to check PayPal can produce it; the link
        # below serves the image.
        await PayPalCommerceService().invoice_qr_code(invoice_id)

    except Exception as exc:
        return action_result(state, friendly(exc, "I couldn't make a QR code."))

    return action_result(
        state,
        f"Here's the QR code for invoice {invoice_id}. Your customer can scan "
        f"it to pay:\n/api/invoices/{invoice_id}/qr.png",
    )


async def refund_status_node(state: PaymentAgentState) -> dict:
    """Report the refunds made on the invoice."""

    try:
        refunds = await PayPalCommerceService().refund_status(state["invoice_id"])

    except Exception as exc:
        return action_result(state, friendly(exc, "I couldn't check the refunds."))

    if not refunds:
        return action_result(state, "No refunds have been made on this invoice.")

    lines = [
        f"- {refund['amount']} {refund['currency']}: {refund['status']}"
        for refund in refunds
    ]

    return action_result(state, "Refunds on this invoice:\n" + "\n".join(lines))


async def add_tracking_node(state: PaymentAgentState) -> dict:
    """Attach a tracking number to the invoice's payment."""

    tracking_number = args(state).get("tracking_number")

    if not tracking_number:
        return action_result(
            state, "What's the tracking number (and carrier, e.g. UPS)?"
        )

    try:
        await PayPalCommerceService().add_tracking(
            state["invoice_id"], tracking_number, args(state).get("carrier")
        )

    except Exception as exc:
        return action_result(
            state, friendly(exc, "I couldn't add the tracking number.")
        )

    return action_result(
        state,
        f"Tracking {tracking_number} is added to the payment. PayPal shows it "
        "to the buyer, which also helps if they ever open a dispute.",
    )


async def get_tracking_node(state: PaymentAgentState) -> dict:
    try:
        result = await PayPalCommerceService().get_tracking(state["invoice_id"])

    except Exception as exc:
        return action_result(state, friendly(exc, "I couldn't find the tracking."))

    trackers = result.get("trackers") or [result]
    lines = [
        f"- {item.get('tracking_number')} ({item.get('carrier', 'carrier unknown')}): "
        f"{item.get('status')}"
        for item in trackers
        if item.get("tracking_number")
    ]

    if not lines:
        return action_result(state, "No tracking has been added for this payment.")

    return action_result(state, "Shipment tracking:\n" + "\n".join(lines))


# --- Account actions -------------------------------------------------------


async def earnings_node(state: PaymentAgentState) -> dict:
    """How much money came in over a period."""

    days = args(state).get("period_days") or 30

    try:
        result = await PayPalCommerceService().earnings(days)

    except Exception as exc:
        return action_result(state, friendly(exc, "I couldn't work out your earnings."))

    currency = result["currency"]
    text = (
        f"In the last {result['days']} days ({result['from']} to {result['to']}) "
        f"you received {result['received']} {currency} from "
        f"{result['payments']} payment(s)."
    )

    if result["refunded"] != "0.00":
        text += (
            f" {result['refunded']} {currency} was refunded, so you kept "
            f"{result['net']} {currency}."
        )

    return action_result(state, text)


async def list_disputes_node(state: PaymentAgentState) -> dict:
    try:
        disputes = await PayPalCommerceService().list_disputes()

    except Exception as exc:
        return action_result(state, friendly(exc, "I couldn't check for disputes."))

    if not disputes:
        return action_result(state, "Good news: you have no disputes.")

    lines = [
        f"- {d['dispute_id']}: {d['amount']} {d['currency']}, {d['status']}"
        + (" ⚠ needs your response" if d["needs_action"] else "")
        for d in disputes
    ]

    return action_result(
        state,
        "Your disputes:\n" + "\n".join(lines)
        + "\nAsk me to explain one, e.g. \"explain dispute "
        + disputes[0]["dispute_id"] + "\".",
    )


async def _pick_dispute(state: PaymentAgentState, service) -> str | None:
    """The dispute the user named, else the first one needing action."""

    if args(state).get("dispute_id"):
        return args(state)["dispute_id"]

    disputes = await service.list_disputes()
    waiting = [d for d in disputes if d["needs_action"]] or disputes

    return waiting[0]["dispute_id"] if waiting else None


async def explain_dispute_node(state: PaymentAgentState) -> dict:
    """Explain a dispute in plain words and suggest what to do."""

    try:
        service = PayPalCommerceService()
        dispute_id = await _pick_dispute(state, service)

        if not dispute_id:
            return action_result(state, "Good news: you have no disputes.")

        dispute = summarize_dispute(await service.get_dispute(dispute_id))

    except Exception as exc:
        return action_result(state, friendly(exc, "I couldn't look up the dispute."))

    reason, advice = DISPUTE_REASONS.get(
        dispute["reason"],
        ("the buyer raised a problem with the payment", "Check the details in PayPal."),
    )
    text = (
        f"Dispute {dispute_id} is about {dispute['amount']} {dispute['currency']}: "
        f"{reason}. Status: {dispute['status']}."
    )

    if dispute["respond_by"]:
        text += f" Respond by {dispute['respond_by'][:10]}."

    text += f"\nWhat I suggest: {advice}"

    if dispute["needs_action"]:
        text += (
            f"\nTo give the buyer their money back, say \"accept dispute {dispute_id}\"."
        )

    return action_result(state, text)


async def request_accept_dispute_node(state: PaymentAgentState) -> dict:
    """Accepting refunds the buyer, so ask first."""

    try:
        dispute_id = await _pick_dispute(state, PayPalCommerceService())

    except Exception as exc:
        return action_result(state, friendly(exc, "I couldn't look up the dispute."))

    if not dispute_id:
        return action_result(state, "There is no dispute to accept.")

    return action_result(
        state,
        f"Accepting dispute {dispute_id} means PayPal refunds the buyer.\n"
        "Reply CONFIRM ACCEPT to continue, or STOP to keep fighting it.",
        pending_dispute_accept=dispute_id,
    )


async def accept_dispute_node(state: PaymentAgentState) -> dict:
    """Accept the dispute after CONFIRM ACCEPT."""

    dispute_id = state.get("pending_dispute_accept")

    if normalize_reply(state.get("user_message", "")) != "confirm accept":
        return action_result(
            state, "Okay, I didn't accept the dispute.", pending_dispute_accept=""
        )

    try:
        await PayPalCommerceService().accept_dispute(
            dispute_id, "We accept the claim and agree to refund the buyer."
        )

    except Exception as exc:
        return action_result(
            state,
            friendly(exc, "I couldn't confirm the dispute was accepted."),
            pending_dispute_accept="",
        )

    await repositories.add_event(
        dispute_id, f"Dispute {dispute_id} accepted. PayPal will refund the buyer."
    )

    return action_result(
        state,
        f"Dispute {dispute_id} is accepted. PayPal will refund the buyer.",
        pending_dispute_accept="",
    )


async def create_payment_link_node(state: PaymentAgentState) -> dict:
    """Make a PayPal checkout link without an invoice."""

    details = args(state)

    if not details.get("amount") or not details.get("description"):
        return action_result(
            state,
            "Sure. How much, and what is it for? e.g. "
            "\"payment link for $50 for a consultation\".",
        )

    try:
        order = await PayPalCommerceService().create_payment_link(
            details["amount"], details.get("currency") or "USD", details["description"]
        )

    except Exception as exc:
        return action_result(state, friendly(exc, "I couldn't create the payment link."))

    return action_result(
        state,
        f"Payment link for {order['amount']} {order['currency']} "
        f"({details['description']}):\n{order['pay_link']}\n"
        "Share it with your customer. Once they've paid, ask me "
        "\"was the payment link paid?\" and I'll collect the money.",
        order_id=order["order_id"],
    )


async def check_payment_link_node(state: PaymentAgentState) -> dict:
    """Check the pay link; collect the money once the buyer approved it."""

    order_id = state.get("order_id")

    if not order_id:
        return action_result(
            state, "There's no payment link in this conversation yet."
        )

    try:
        service = PayPalCommerceService()
        order = await service.get_payment_link(order_id)

        if order["status"] == "APPROVED":
            order = await service.capture_payment(order_id)

    except Exception as exc:
        return action_result(state, friendly(exc, "I couldn't check the payment link."))

    if order["status"] == "COMPLETED":
        return action_result(state, "🎉 The payment link was paid and the money is in your PayPal account.")

    return action_result(
        state,
        "The customer hasn't paid the link yet. Link:\n" + str(order["pay_link"]),
    )
