import asyncio
import os

import httpx
from dotenv import load_dotenv

load_dotenv()


async def main():
    """Diagnose PayPal Sandbox invoice API authorization."""

    client_id = os.getenv("PAYPAL_CLIENT_ID")
    client_secret = os.getenv("PAYPAL_CLIENT_SECRET")

    base_url = os.getenv(
        "PAYPAL_BASE_URL",
        "https://api-m.sandbox.paypal.com",
    ).rstrip("/")

    # Step 1: Validate configuration.
    if not client_id or not client_secret:
        raise RuntimeError(
            "PayPal credentials are missing. "
            "Check PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env."
        )

    print("=" * 60)
    print("PAYPAL SANDBOX INVOICE DIAGNOSTIC")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=30.0) as client:

        # Step 2: Request an OAuth access token.
        print("\n[1] Requesting OAuth access token...")

        token_response = await client.post(
            f"{base_url}/v1/oauth2/token",
            auth=(client_id, client_secret),
            headers={
                "Accept": "application/json",
                "Accept-Language": "en_US",
            },
            data={
                "grant_type": "client_credentials",
            },
        )

        print("OAuth HTTP status:", token_response.status_code)

        if token_response.is_error:
            print("OAuth error response:", token_response.text)
            token_response.raise_for_status()

        token_data = token_response.json()

        access_token = token_data.get("access_token")

        if not access_token:
            raise RuntimeError(
                "PayPal OAuth response did not contain an access token."
            )

        # Step 3: Display safe token metadata.
        print("\n[2] OAuth token information")
        print("Token type:", token_data.get("token_type", "Not provided"))
        print("Token expires in:", token_data.get("expires_in", "Not provided"))

        granted_scope = token_data.get("scope")

        if granted_scope:
            print("Granted scope:", granted_scope)

            required_scope = (
                "https://uri.paypal.com/services/"
                "invoicing/invoices/readwrite"
            )

            scope_list = granted_scope.split()

            if required_scope in scope_list:
                print("Invoice read/write scope: PRESENT")
            else:
                print(
                    "Invoice read/write scope: NOT FOUND "
                    "as an exact scope match"
                )
        else:
            print("Granted scope: Not returned in OAuth response")

        # Step 4: Prepare a minimal Sandbox draft invoice.
        # This creates a draft if successful; it does not send it.
        print("\n[3] Testing invoice creation...")

        payload = {
            "detail": {
                "currency_code": "USD",
                "note": "Sandbox API diagnostic test",
            },
            "invoicer": {
                "name": {
                    "given_name": "Seller",
                    "surname": "Business",
                },
            },
            "primary_recipients": [
                {
                    "billing_info": {
                        "email_address": (
                            "sb-us3m4753550124@personal.example.com"
                        ),
                    },
                },
            ],
            "items": [
                {
                    "name": "Test service",
                    "quantity": "1",
                    "unit_amount": {
                        "currency_code": "USD",
                        "value": "5.00",
                    },
                },
            ],
        }

        invoice_response = await client.post(
            f"{base_url}/v2/invoicing/invoices",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Prefer": "return=representation",
            },
            json=payload,
        )

        print("Invoice HTTP status:", invoice_response.status_code)

        try:
            response_data = invoice_response.json()
        except ValueError:
            response_data = {"raw_response": invoice_response.text}

        # Print the response, not the OAuth token.
        print("Invoice response:")

        import json

        print(json.dumps(response_data, indent=2))

        # Step 5: Summarize the result.
        print("\n[4] Diagnostic result")

        if invoice_response.status_code in (200, 201):
            invoice_id = response_data.get("id", "Not returned")

            print("SUCCESS: PayPal accepted the invoice request.")
            print("Invoice ID:", invoice_id)
            print("The invoice draft has not been emailed.")
        elif invoice_response.status_code == 403:
            print("AUTHORIZATION FAILURE: PayPal rejected the request.")
            print(
                "Check Sandbox app permissions and account authorization."
            )
            print(
                "Save the PayPal debug_id for Developer Support."
            )
        elif invoice_response.status_code == 401:
            print("AUTHENTICATION FAILURE: PayPal rejected the token.")
        elif invoice_response.status_code == 400:
            print("INVALID REQUEST: Inspect PayPal's response details.")
        else:
            print(
                "PayPal returned an unexpected status. "
                "Inspect the response above."
            )

    print("\nDiagnostic finished.")


if __name__ == "__main__":
    asyncio.run(main())