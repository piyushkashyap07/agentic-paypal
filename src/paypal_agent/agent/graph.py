from langgraph.graph import END, START, StateGraph

from paypal_agent.agent.nodes import (
    confirmation_gate,
    create_invoice_draft,
    understand_request,
)
from paypal_agent.agent.state import PaymentAgentState


def route_before_understanding(state: PaymentAgentState) -> str:
    """Route confirmation replies directly to the confirmation gate."""

    if state.get("pending_invoice_confirmation"):
        message = state.get("user_message", "").strip().casefold()

        if message in {"confirm", "cancel", "no", "stop"}:
            return "confirmation_gate"

    return "understand_request"


def route_after_understanding(state: PaymentAgentState) -> str:
    """Wait for the user's next message after preparing the invoice summary."""
    return END


def route_after_confirmation(state: PaymentAgentState) -> str:
    """Proceed only when the Python confirmation gate approves."""

    if (
        state.get("response") == "Confirmation received. Preparing the invoice."
        and state.get("pending_invoice_confirmation")
        and state.get("invoice_confirmation_requested")
    ):
        return "create_invoice_draft"

    return END


def build_graph(checkpointer):
    """Build the payment-agent conversation graph."""

    graph = StateGraph(PaymentAgentState)

    graph.add_node("understand_request", understand_request)
    graph.add_node("confirmation_gate", confirmation_gate)
    graph.add_node("create_invoice_draft", create_invoice_draft)

    graph.add_conditional_edges(
        START,
        route_before_understanding,
        {
            "understand_request": "understand_request",
            "confirmation_gate": "confirmation_gate",
        },
    )

    graph.add_conditional_edges(
        "understand_request",
        route_after_understanding,
        {
            END: END,
        },
    )

    graph.add_conditional_edges(
        "confirmation_gate",
        route_after_confirmation,
        {
            "create_invoice_draft": "create_invoice_draft",
            END: END,
        },
    )

    graph.add_edge("create_invoice_draft", END)

    return graph.compile(checkpointer=checkpointer)