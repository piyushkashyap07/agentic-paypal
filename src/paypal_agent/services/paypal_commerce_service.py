import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from paypal_agent.config import settings
from paypal_agent.services.paypal_invoice_service import PayPalInvoiceService
from paypal_agent.services import paypal_mcp_client
from paypal_agent.services.paypal_mcp_client import PayPalMCPError

# Invoice statuses where money has come in (possibly partly refunded since).
PAID_STATUSES = {
    "PAID",
    "MARKED_AS_PAID",
    "PARTIALLY_PAID",
    "PARTIALLY_REFUNDED",
    "REFUNDED",
}

# Disputes waiting on the seller.
ACTION_NEEDED = "REQUIRED_ACTION"


def _money(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _capture_ids(invoice: dict) -> list[str]:
    """PayPal capture ids of the payments made against an invoice."""

    return [
        transaction["payment_id"]
        for transaction in invoice.get("payments", {}).get("transactions", [])
        if transaction.get("type") == "PAYPAL" and transaction.get("payment_id")
    ]


def summarize_dispute(dispute: dict) -> dict:
    """Pick out the dispute fields the agent and UI need."""

    amount = dispute.get("dispute_amount") or {}
    transactions = dispute.get("disputed_transactions") or [{}]

    return {
        "dispute_id": dispute.get("dispute_id"),
        "reason": dispute.get("reason"),
        "status": dispute.get("status"),
        "stage": dispute.get("dispute_life_cycle_stage"),
        "amount": amount.get("value"),
        "currency": amount.get("currency_code"),
        "created": dispute.get("create_time"),
        "respond_by": dispute.get("seller_response_due_date"),
        "transaction_id": transactions[0].get("seller_transaction_id"),
        "needs_action": dispute.get("status") == ACTION_NEEDED,
    }


def user_error(exc: Exception) -> str | None:
    """A message the user can act on, or None for unexpected failures."""

    if isinstance(exc, ValueError):
        return str(exc)

    if isinstance(exc, PayPalMCPError):
        if exc.status == 403:
            return (
                "Your PayPal app doesn't have permission for this. Turn the "
                "feature on in the PayPal developer dashboard (Apps & "
                "Credentials → your app → Features), then try again."
            )

        if exc.status in {400, 404, 409, 422}:
            return f"PayPal said: {exc.reason}"

    return None


def qr_png_base64(result) -> str:
    """Pull the base64 PNG out of PayPal's multipart QR-code response."""

    match = re.search(r"(iVBORw0KGgo[A-Za-z0-9+/=\s]+)", str(result))

    if not match:
        raise ValueError("PayPal did not return a QR code image.")

    return "".join(match.group(1).split())


class PayPalCommerceService:
    """Disputes, earnings, cancel, QR, refunds, pay links and shipments.

    These go through the PayPal MCP server only (no REST copies), so they
    need PAYPAL_TRANSPORT=mcp.
    """

    def __init__(self):
        if settings.paypal_transport != "mcp":
            raise RuntimeError(
                "This feature uses the PayPal MCP server. "
                "Set PAYPAL_TRANSPORT=mcp in .env."
            )

        self.invoices = PayPalInvoiceService()

    async def _call(self, tool: str, arguments: dict):
        return await paypal_mcp_client.mcp_client.call(tool, arguments)

    # --- Invoices ---------------------------------------------------------

    async def cancel_invoice(self, invoice_id: str) -> dict:
        """Cancel a sent invoice and tell the customer."""

        return await self._call(
            "cancel_sent_invoice",
            {
                "invoice_id": invoice_id,
                "send_to_recipient": True,
                "note": "This invoice has been cancelled. No payment is needed.",
            },
        )

    async def invoice_qr_code(self, invoice_id: str) -> str:
        """Return a QR code (base64 PNG) that opens the invoice's pay page."""

        result = await self._call(
            "generate_invoice_qr_code",
            {"invoice_id": invoice_id, "width": 300, "height": 300},
        )

        return qr_png_base64(result)

    async def refund_status(self, invoice_id: str) -> list[dict]:
        """Status of every refund made on an invoice."""

        invoice = await self.invoices.get_invoice(invoice_id)
        # PayPal stores the refund id as recipient_transaction_id here.
        refund_ids = [
            transaction.get("refund_id") or transaction["recipient_transaction_id"]
            for transaction in invoice.get("refunds", {}).get("transactions", [])
            if transaction.get("type") == "PAYPAL"
            and (transaction.get("refund_id") or transaction.get("recipient_transaction_id"))
        ]

        refunds = []

        for refund_id in refund_ids:
            refund = await self._call("get_refund", {"refund_id": refund_id})
            amount = refund.get("amount") or {}
            refunds.append(
                {
                    "refund_id": refund_id,
                    "status": refund.get("status"),
                    "amount": amount.get("value"),
                    "currency": amount.get("currency_code"),
                    "time": refund.get("create_time"),
                }
            )

        return refunds

    # --- Earnings ---------------------------------------------------------

    async def earnings(self, days: int = 30) -> dict:
        """Money received in the last `days` days.

        Uses PayPal transactions when the app has the Transaction Search
        permission, otherwise works it out from paid invoices.
        """

        days = max(1, min(int(days or 30), 365))
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)

        try:
            return await self._earnings_from_transactions(start, end, days)

        except PayPalMCPError as exc:
            if exc.status != 403:
                raise

            # 403 = the app lacks "Transaction Search" in the PayPal
            # developer dashboard. Invoices still tell us what was paid.
            return await self._earnings_from_invoices(start, end, days)

    async def _earnings_from_transactions(self, start, end, days) -> dict:
        result = await self._call(
            "list_transactions",
            {
                "start_date": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end_date": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "page_size": 500,
            },
        )

        received = refunded = Decimal(0)
        count = 0
        currency = "USD"

        for item in result.get("transaction_details", []):
            info = item.get("transaction_info", {})

            if info.get("transaction_status") != "S":
                continue

            amount = info.get("transaction_amount", {})
            value = _money(amount.get("value"))
            currency = amount.get("currency_code") or currency

            if value > 0:
                received += value
                count += 1
            else:
                refunded += -value

        return self._earnings_result(days, start, end, received, refunded, count, currency, "transactions")

    async def _earnings_from_invoices(self, start, end, days) -> dict:
        received = refunded = Decimal(0)
        count = 0
        currency = "USD"

        for invoice in await self.invoices.list_invoices(page_size=100):
            if invoice.get("status") not in PAID_STATUSES:
                continue

            invoice_date = invoice.get("detail", {}).get("invoice_date")

            if invoice_date and invoice_date < start.date().isoformat():
                continue

            paid = _money(invoice.get("payments", {}).get("paid_amount", {}).get("value"))

            if not paid:
                paid = _money(invoice.get("amount", {}).get("value")) - _money(
                    invoice.get("due_amount", {}).get("value")
                )

            received += paid
            refunded += _money(
                invoice.get("refunds", {}).get("refund_amount", {}).get("value")
            )
            currency = invoice.get("detail", {}).get("currency_code") or currency
            count += 1

        return self._earnings_result(days, start, end, received, refunded, count, currency, "invoices")

    @staticmethod
    def _earnings_result(days, start, end, received, refunded, count, currency, source) -> dict:
        return {
            "days": days,
            "from": start.date().isoformat(),
            "to": end.date().isoformat(),
            "received": f"{received:.2f}",
            "refunded": f"{refunded:.2f}",
            "net": f"{received - refunded:.2f}",
            "payments": count,
            "currency": currency,
            "source": source,
        }

    # --- Disputes ---------------------------------------------------------

    async def list_disputes(self) -> list[dict]:
        result = await self._call("list_disputes", {"page_size": 20})

        return [summarize_dispute(item) for item in result.get("items", [])]

    async def get_dispute(self, dispute_id: str) -> dict:
        return await self._call("get_dispute", {"dispute_id": dispute_id})

    async def accept_dispute(self, dispute_id: str, note: str) -> dict:
        """Accept the buyer's claim. PayPal then refunds the buyer."""

        return await self._call(
            "accept_dispute_claim", {"dispute_id": dispute_id, "note": note}
        )

    # --- Pay links (orders) -----------------------------------------------

    async def create_payment_link(
        self, amount, currency: str, description: str
    ) -> dict:
        """Create a PayPal order and return its pay link."""

        try:
            amount = Decimal(str(amount))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("The amount must be a number.") from exc

        if not amount.is_finite() or amount <= 0:
            raise ValueError("The amount must be greater than zero.")

        currency = (currency or "USD").upper()

        # The PayPal MCP create_order tool only accepts USD.
        if currency != "USD":
            raise ValueError("Payment links support USD only.")

        if not (description or "").strip():
            raise ValueError("Say what the payment is for.")

        value = float(f"{amount:.2f}")
        order = await self._call(
            "create_order",
            {
                "currencyCode": "USD",
                "items": [
                    {
                        "name": description.strip()[:127],
                        "quantity": 1,
                        "itemCost": value,
                        "itemTotal": value,
                    }
                ],
            },
        )

        # create_order's reply leaves out the amount; we know it.
        return {**summarize_order(order), "amount": f"{amount:.2f}", "currency": "USD"}

    async def get_payment_link(self, order_id: str) -> dict:
        return summarize_order(await self._call("get_order", {"id": order_id}))

    async def capture_payment(self, order_id: str) -> dict:
        """Collect the money once the buyer has approved the order."""

        return summarize_order(await self._call("pay_order", {"id": order_id}))

    # --- Shipment tracking ------------------------------------------------

    async def add_tracking(
        self, invoice_id: str, tracking_number: str, carrier: str | None
    ) -> dict:
        """Attach a shipment tracking number to an invoice's payment."""

        capture_ids = _capture_ids(await self.invoices.get_invoice(invoice_id))

        if not capture_ids:
            raise ValueError(
                "Tracking can only be added after the invoice is paid."
            )

        arguments = {
            "transaction_id": capture_ids[0],
            "tracking_number": tracking_number,
            "status": "SHIPPED",
        }

        if carrier:
            arguments["carrier"] = carrier.upper().replace(" ", "_")

        return await self._call("create_shipment_tracking", arguments)

    async def get_tracking(self, invoice_id: str) -> dict:
        capture_ids = _capture_ids(await self.invoices.get_invoice(invoice_id))

        if not capture_ids:
            raise ValueError("This invoice has no payment to track yet.")

        return await self._call(
            "get_shipment_tracking", {"transaction_id": capture_ids[0]}
        )


def summarize_order(order: dict) -> dict:
    """Order id, status, amount and the link the buyer pays at."""

    links = {link.get("rel"): link.get("href") for link in order.get("links", [])}
    units = order.get("purchase_units") or [{}]
    amount = units[0].get("amount") or {}

    return {
        "order_id": order.get("id"),
        "status": order.get("status"),
        "amount": amount.get("value"),
        "currency": amount.get("currency_code"),
        "pay_link": links.get("payer-action") or links.get("approve"),
    }
