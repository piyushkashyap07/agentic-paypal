from typing import TypedDict, NotRequired


class PaymentAgentState(TypedDict):
    """State maintained throughout a payment-agent conversation."""

    user_message: str
    conversation_history: list[dict[str, str]]
    response: str
    needs_clarification: bool

    # Invoice details collected from the conversation.
    invoice_customer_name: NotRequired[str]
    invoice_customer_email: NotRequired[str]
    invoice_amount: NotRequired[str]
    invoice_currency: NotRequired[str]
    invoice_description: NotRequired[str]
    # ISO date (YYYY-MM-DD). Computed in Python from "due in N days".
    invoice_due_date: NotRequired[str]

    # Explicit confirmation workflow.
    pending_invoice_confirmation: NotRequired[bool]
    invoice_confirmation_requested: NotRequired[bool]

    # Result of the PayPal invoice operation.
    invoice_id: NotRequired[str]
    invoice_status: NotRequired[str]

    # Follow-up action on the created invoice: "send_invoice",
    # "check_status", "send_reminder" or "refund". Empty when none.
    requested_action: NotRequired[str]

    # Refunds move money back, so they need their own confirmation.
    pending_refund_confirmation: NotRequired[bool]

    # Details the LLM pulled out for the requested action, e.g.
    # {"dispute_id": ..., "tracking_number": ..., "amount": ...}.
    action_args: NotRequired[dict]

    # Cancelling an invoice and accepting a dispute (which refunds the
    # buyer) need their own confirmation too.
    pending_cancel_confirmation: NotRequired[bool]
    pending_dispute_accept: NotRequired[str]

    # Last pay link (PayPal order) made in this conversation.
    order_id: NotRequired[str]
