from typing import Annotated

from fastapi import Path, Request
from fastapi.responses import JSONResponse

from paypal_agent.config import settings

# PayPal ids are letters, digits, "-" and "_" (e.g. INV2-ABCD-..., PP-D-123).
# Checking them before use keeps odd values out of PayPal URLs and tools.
ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"

InvoiceId = Annotated[str, Path(pattern=ID_PATTERN)]
DisputeId = Annotated[str, Path(pattern=ID_PATTERN)]
OrderId = Annotated[str, Path(pattern=ID_PATTERN)]

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


async def block_cross_site_requests(request: Request, call_next):
    """Refuse state-changing API calls made by other websites.

    A browser adds an Origin header to every cross-site POST, even a
    "no-cors" one a malicious page can send without our permission. Our
    own frontend's origin is allowed; tools without a browser (curl,
    Postman, tests) send no Origin and are allowed. PayPal webhooks are
    checked by signature instead.
    """

    path = request.url.path
    origin = request.headers.get("origin")

    if (
        request.method not in SAFE_METHODS
        and path.startswith("/api/")
        and not path.startswith("/api/webhooks/")
        and origin
        and origin not in settings.allowed_origin_list
    ):
        print(f"[security] blocked {request.method} {path} from origin {origin}")

        return JSONResponse(
            status_code=403,
            content={"detail": "Requests from other websites are not allowed."},
        )

    return await call_next(request)
