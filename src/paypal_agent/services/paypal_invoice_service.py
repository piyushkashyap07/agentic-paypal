from decimal import Decimal, InvalidOperation

import httpx

from paypal_agent.config import settings


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

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/v1/oauth2/token",
                auth=(self.client_id, self.client_secret),
                headers={
                    "Accept": "application/json",
                    "Accept-Language": "en_US",
                },
                data={"grant_type": "client_credentials"},
            )

            if response.is_error:
                print("PayPal OAuth HTTP status:", response.status_code)
                print("PayPal OAuth error response:", response.text)

            response.raise_for_status()

            token = response.json().get("access_token")

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

        # Create the invoice draft through PayPal.
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
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
                print("PayPal invoice HTTP status:", response.status_code)
                print("PayPal invoice error response:", response.text)
                print(
                    "Check PayPal Sandbox app permissions, "
                    "account access, and the API error details."
                )

            response.raise_for_status()

            result = response.json()

            print(
                "PayPal invoice draft created. "
                f"Invoice ID: {result.get('id', 'not returned')}"
            )

            return result