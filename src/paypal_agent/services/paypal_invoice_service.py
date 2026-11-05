import asyncio
import time
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

from paypal_agent.config import settings

# Statuses worth retrying, but only for requests that are safe to repeat.
RETRY_STATUSES = {429, 502, 503, 504}
MAX_ATTEMPTS = 3

# Wall-clock expiry on purpose: time.monotonic() stops while a laptop
# sleeps, which would keep serving an expired token after wake-up.
# Access tokens live ~9 hours; cache one per client id instead of asking
# PayPal for a new token on every call (the monitor makes many calls).
_token_cache: dict[str, tuple[str, float]] = {}


def _log_paypal_error(what: str, response: httpx.Response) -> None:
    """Log what failed without dumping the raw body (it can hold emails)."""

    try:
        body = response.json()
    except ValueError:
        body = {}

    if not isinstance(body, dict):
        body = {}

    issue = (body.get("details") or [{}])[0].get("issue")
    print(
        f"PayPal {what} failed: HTTP {response.status_code} "
        f"name={body.get('name') or body.get('error')} "
        f"issue={issue} debug_id={body.get('debug_id')}"
    )


async def send_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    idempotent: bool | None = None,
    **kwargs,
) -> httpx.Response:
    """Send a request, retrying only when repeating it cannot do harm.

    - Connection failures: the request never reached PayPal, so always retry.
    - Timeouts/5xx/429: the request may have been processed, so retry
      only idempotent calls (GET and the token request). A repeated
      "create invoice" or "refund" could otherwise happen twice.
    """

    if idempotent is None:
        idempotent = method.upper() == "GET"

    for attempt in range(MAX_ATTEMPTS):
        last = attempt == MAX_ATTEMPTS - 1

        try:
            response = await client.request(method, url, **kwargs)

        except (httpx.ConnectError, httpx.ConnectTimeout):
            if last:
                raise
            await asyncio.sleep(0.5 * 2**attempt)
            continue

        except httpx.TransportError:
            if last or not idempotent:
                raise
            await asyncio.sleep(0.5 * 2**attempt)
            continue

        if idempotent and not last and response.status_code in RETRY_STATUSES:
            await asyncio.sleep(0.5 * 2**attempt)
            continue

        return response

    raise RuntimeError("unreachable")  # pragma: no cover


class PayPalInvoiceService:
    """Create draft invoices using the PayPal Invoicing API."""

    def __init__(self):
        self.base_url = settings.paypal_base_url.rstrip("/")
        self.client_id = settings.paypal_client_id
        self.client_secret = settings.paypal_client_secret
        self.invoicer_email = settings.paypal_invoicer_email

    async def _get_access_token(self) -> str:
        """Obtain an OAuth access token from PayPal."""

        if not self.client_id or not self.client_secret:
            raise RuntimeError(
                "PayPal credentials are missing. "
                "Check PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env."
            )

        cached = _token_cache.get(self.client_id)

        if cached and cached[1] > time.time():
            return cached[0]

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await send_with_retry(
                client,
                "POST",
                f"{self.base_url}/v1/oauth2/token",
                idempotent=True,
                auth=(self.client_id, self.client_secret),
                headers={
                    "Accept": "application/json",
                    "Accept-Language": "en_US",
                },
                data={"grant_type": "client_credentials"},
            )

            if response.is_error:
                _log_paypal_error("OAuth", response)

            response.raise_for_status()

            body = response.json()
            token = body.get("access_token")

            if token:
                # Refresh a minute early so a token never expires mid-request.
                lifetime = float(body.get("expires_in", 300))
                _token_cache[self.client_id] = (
                    token,
                    time.time() + max(lifetime - 60, 0),
                )

            if not token:
                raise RuntimeError(
                    "PayPal OAuth response did not contain an access token."
                )

            return token

    async def create_draft_invoice(
        self,
        *,
        customer_email: str,
        amount: Decimal,
        currency: str,
        description: str,
        customer_name: str = "Acme",
        due_date: date | None = None,
    ) -> dict:
        """Create a PayPal invoice draft without emailing the customer."""

        # Validate customer details.
        customer_email = customer_email.strip()

        if (
            not customer_email
            or "@" not in customer_email
            or customer_email.startswith("@")
            or customer_email.endswith("@")
        ):
            raise ValueError("A valid customer email address is required.")

        if not customer_name.strip():
            raise ValueError("Customer name cannot be empty.")

        if not description.strip():
            raise ValueError("Invoice description cannot be empty.")

        # Validate and format the amount.
        try:
            amount = Decimal(str(amount))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("Invoice amount must be a valid number.") from exc

        if not amount.is_finite() or amount <= 0:
            raise ValueError("Invoice amount must be greater than zero.")

        if amount.as_tuple().exponent < -2:
            raise ValueError(
                "Invoice amount cannot have more than two decimal places."
            )

        # Validate currency.
        currency = currency.strip().upper()

        if len(currency) != 3 or not currency.isalpha():
            raise ValueError(
                "Currency must be a three-letter currency code, such as USD."
            )

        # The seller email should belong to the Sandbox business account.
        if not self.invoicer_email:
            raise RuntimeError(
                "PAYPAL_INVOICER_EMAIL is missing. "
                "Set it to your PayPal Sandbox business account email in .env."
            )

        amount_value = f"{amount:.2f}"

        # Obtain a PayPal access token.
        access_token = await self._get_access_token()

        # Build the invoice draft payload.
        payload = {
            "detail": {
                "currency_code": currency,
                "note": "Thank you for your business.",
            },
            "invoicer": {
                "email_address": self.invoicer_email,
                "name": {
                    "given_name": "Seller",
                    "surname": "Business",
                },
            },
            "primary_recipients": [
                {
                    "billing_info": {
                        "email_address": customer_email,
                        "name": {
                            "given_name": customer_name.strip(),
                        },
                    },
                },
            ],
            "items": [
                {
                    "name": description.strip(),
                    "quantity": "1",
                    "unit_amount": {
                        "currency_code": currency,
                        "value": amount_value,
                    },
                },
            ],
        }

        if due_date is not None:
            payload["detail"]["payment_term"] = {
                "term_type": "DUE_ON_DATE_SPECIFIED",
                "due_date": due_date.isoformat(),
            }

        # Create the invoice draft through PayPal.
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await send_with_retry(
                client,
                "POST",
                f"{self.base_url}/v2/invoicing/invoices",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Prefer": "return=representation",
                },
                json=payload,
            )

            if response.is_error:
                _log_paypal_error("invoice creation", response)

            response.raise_for_status()

            result = response.json()

            print(
                "PayPal invoice draft created. "
                f"Invoice ID: {result.get('id', 'not returned')}"
            )

            return result

    async def _invoice_request(
        self,
        method: str,
        path: str,
        json: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        """Call a PayPal Invoicing endpoint and return the JSON body."""

        return await self._request(
            method,
            f"/v2/invoicing/invoices{path}",
            json=json,
            params=params,
        )

    async def _request(
        self,
        method: str,
        path: str,
        json: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        """Call any PayPal REST endpoint and return the JSON body."""

        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(2):
                access_token = await self._get_access_token()

                response = await send_with_retry(
                    client,
                    method,
                    f"{self.base_url}{path}",
                    params=params,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    json=json,
                )

                # A 401 means PayPal did not process the call, so one retry
                # with a fresh token is safe even for POSTs.
                if response.status_code == 401 and attempt == 0:
                    _token_cache.pop(self.client_id, None)
                    continue

                break

            if response.is_error:
                _log_paypal_error(f"{method} {path}", response)

                # PayPal puts the exact reason in details[0].issue.
                try:
                    details = response.json().get("details") or [{}]
                    issue = details[0].get("issue", "")
                except ValueError:
                    issue = ""

                if issue == "INR_FOREIGN_CURRENCY_BLOCKED":
                    raise ValueError(
                        "PayPal cannot send invoices to customers in India. "
                        "Use a customer account outside India."
                    )

            response.raise_for_status()

            return response.json() if response.content else {}

    async def verify_webhook(self, headers: dict, event: dict) -> bool:
        """Ask PayPal whether a webhook really came from PayPal."""

        if not settings.paypal_webhook_id:
            return False

        result = await self._request(
            "POST",
            "/v1/notifications/verify-webhook-signature",
            json={
                "auth_algo": headers.get("paypal-auth-algo"),
                "cert_url": headers.get("paypal-cert-url"),
                "transmission_id": headers.get("paypal-transmission-id"),
                "transmission_sig": headers.get("paypal-transmission-sig"),
                "transmission_time": headers.get("paypal-transmission-time"),
                "webhook_id": settings.paypal_webhook_id,
                "webhook_event": event,
            },
        )

        return result.get("verification_status") == "SUCCESS"

    async def send_invoice(self, invoice_id: str) -> dict:
        """Email a draft invoice to the customer."""

        return await self._invoice_request(
            "POST",
            f"/{invoice_id}/send",
            json={"send_to_invoicer": True},
        )

    async def get_invoice(self, invoice_id: str) -> dict:
        """Fetch the latest invoice details, including its status."""

        return await self._invoice_request("GET", f"/{invoice_id}")

    async def send_reminder(self, invoice_id: str) -> dict:
        """Send a payment reminder for an invoice that is not yet paid."""

        return await self._invoice_request(
            "POST",
            f"/{invoice_id}/remind",
            json={
                "subject": "Reminder: your invoice is waiting",
                "note": "This is a friendly reminder to pay your invoice.",
            },
        )

    async def list_invoices(self, page_size: int = 20) -> list[dict]:
        """List the merchant's most recent invoices."""

        result = await self._invoice_request(
            "GET",
            "",
            params={"page": 1, "page_size": page_size},
        )

        return result.get("items", [])

    async def refund_invoice(
        self,
        invoice_id: str,
        amount: Decimal | None = None,
    ) -> dict:
        """Refund the PayPal payment made against an invoice.

        Refunds the full payment unless a smaller amount is given.
        """

        invoice = await self.get_invoice(invoice_id)

        # An invoice paid through PayPal stores the capture ID of that
        # payment. Refunds are made against this capture.
        capture_ids = [
            transaction["payment_id"]
            for transaction in invoice.get("payments", {}).get(
                "transactions", []
            )
            if transaction.get("type") == "PAYPAL"
            and transaction.get("payment_id")
        ]

        if not capture_ids:
            raise ValueError(
                "This invoice has no PayPal payment that can be refunded."
            )

        body = {}

        if amount is not None:
            amount = Decimal(str(amount))

            if not amount.is_finite() or amount <= 0:
                raise ValueError("Refund amount must be greater than zero.")

            body["amount"] = {
                "currency_code": invoice["detail"]["currency_code"],
                "value": f"{amount:.2f}",
            }

        return await self._request(
            "POST",
            f"/v2/payments/captures/{capture_ids[0]}/refund",
            json=body,
        )