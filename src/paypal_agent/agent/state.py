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

    # Explicit confirmation workflow.
    pending_invoice_confirmation: NotRequired[bool]
    invoice_confirmation_requested: NotRequired[bool]

    # Result of the PayPal invoice operation.
    invoice_id: NotRequired[str]
    invoice_status: NotRequired[str]