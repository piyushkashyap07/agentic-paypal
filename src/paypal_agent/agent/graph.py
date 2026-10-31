from langgraph.graph import END, START, StateGraph

from paypal_agent.agent.nodes import (
    check_status_node,
    confirmation_gate,
    create_invoice_draft,
    refund_node,
    request_refund_node,
    send_invoice_node,
    send_reminder_node,
    understand_request,
)
from paypal_agent.agent.state import PaymentAgentState

# Node that handles each follow-up action on an existing invoice.
ACTION_NODES = {
    "send_invoice": "send_invoice_node",
    "check_status": "check_status_node",
    "send_reminder": "send_reminder_node",
    "refund": "request_refund_node",
}

# One-word shortcuts that skip the LLM once an invoice exists.
KEYWORD_ACTIONS = {
    "send": "send_invoice",
    "status": "check_status",
    "remind": "send_reminder",
    "refund": "refund",
}


def route_before_understanding(state: PaymentAgentState) -> str:
    """Route confirmation replies and shortcuts past the LLM."""

    message = state.get("user_message", "").strip().casefold()

    if state.get("pending_invoice_confirmation"):
        if message in {"confirm", "cancel", "no", "stop"}:
            return "confirmation_gate"

    if state.get("pending_refund_confirmation"):
        if message in {"confirm refund", "cancel", "no", "stop"}:
            return "refund_node"

    if state.get("invoice_id") and message in KEYWORD_ACTIONS:
        return ACTION_NODES[KEYWORD_ACTIONS[message]]

    return "understand_request"


def route_after_understanding(state: PaymentAgentState) -> str:
    """Run a requested follow-up action, otherwise wait for the user."""

    return ACTION_NODES.get(state.get("requested_action", ""), END)


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
    graph.add_node("send_invoice_node", send_invoice_node)
    graph.add_node("check_status_node", check_status_node)
    graph.add_node("send_reminder_node", send_reminder_node)
    graph.add_node("request_refund_node", request_refund_node)
    graph.add_node("refund_node", refund_node)

    graph.add_conditional_edges(
        START,
        route_before_understanding,
        {
            "understand_request": "understand_request",
            "confirmation_gate": "confirmation_gate",
            "refund_node": "refund_node",
            **{node: node for node in ACTION_NODES.values()},
        },
    )

    graph.add_conditional_edges(
        "understand_request",
        route_after_understanding,
        {
            END: END,
            **{node: node for node in ACTION_NODES.values()},
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

    for node in [*ACTION_NODES.values(), "refund_node"]:
        graph.add_edge(node, END)

    return graph.compile(checkpointer=checkpointer)
