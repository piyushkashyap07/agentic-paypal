import asyncio
import json
import os
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from paypal_agent.config import settings

# The PayPal MCP server takes a ready-made access token, not the client
# secret. Tokens live ~9 hours, so restart the server well before expiry.
TOKEN_LIFETIME_SECONDS = 8 * 60 * 60
CALL_TIMEOUT_SECONDS = 60


class PayPalMCPError(RuntimeError):
    """A PayPal MCP tool call failed."""

    def __init__(self, tool: str, status: int | None, message: str):
        super().__init__(f"PayPal MCP {tool} failed ({status}): {message}")
        self.status = status


class PayPalMCPClient:
    """One long-lived connection to the official PayPal MCP server.

    The server (`npx @paypal/mcp`) runs as a child process and speaks MCP
    over stdio. A background task owns the connection, because the MCP
    SDK requires a connection to be opened and closed in the same task.
    """

    def __init__(self):
        self._session: ClientSession | None = None
        self._owner: asyncio.Task | None = None
        self._stop: asyncio.Event | None = None
        self._started_at = 0.0
        self._lock = asyncio.Lock()

    async def call(self, tool: str, arguments: dict) -> dict:
        """Call a PayPal MCP tool and return its JSON result."""

        session = await self._ensure_session()
        result = await session.call_tool(
            tool, arguments, read_timeout_seconds=CALL_TIMEOUT_SECONDS
        )

        text = "".join(
            getattr(item, "text", "") for item in result.content
        )

        try:
            body = json.loads(text) if text else {}
        except json.JSONDecodeError:
            body = {"ok": False, "message": text}

        # PayPal MCP reports HTTP errors as {"ok": false, ...} in a
        # normal (non-error) result, so both shapes must be checked.
        failed = getattr(result, "is_error", False) or (
            isinstance(body, dict) and body.get("ok") is False
        )

        if failed:
            message = str(body.get("message") or text)
            print(
                f"PayPal MCP {tool} failed: status={body.get('status')} "
                f"code={body.get('code')}"
            )

            if "INR_FOREIGN_CURRENCY_BLOCKED" in text:
                raise ValueError(
                    "PayPal cannot send invoices to customers in India. "
                    "Use a customer account outside India."
                )

            raise PayPalMCPError(tool, body.get("status"), message)

        return body

    async def close(self) -> None:
        """Stop the MCP server process."""

        if self._stop:
            self._stop.set()

        if self._owner:
            await asyncio.gather(self._owner, return_exceptions=True)

        self._session = self._owner = self._stop = None

    async def _ensure_session(self) -> ClientSession:
        async with self._lock:
            expired = time.time() - self._started_at > TOKEN_LIFETIME_SECONDS
            dead = self._owner is None or self._owner.done()

            if self._session and not expired and not dead:
                return self._session

            await self.close()
            await self._start()

            return self._session

    async def _start(self) -> None:
        # Imported here to avoid a circular import with the service module.
        from paypal_agent.services.paypal_invoice_service import (
            PayPalInvoiceService,
        )

        token = await PayPalInvoiceService()._get_access_token()
        environment = (
            "SANDBOX" if "sandbox" in settings.paypal_base_url else "PRODUCTION"
        )
        params = StdioServerParameters(
            command="npx",
            args=["-y", settings.paypal_mcp_package, "--tools=all"],
            env={
                **os.environ,
                "PAYPAL_ACCESS_TOKEN": token,
                "PAYPAL_ENVIRONMENT": environment,
            },
        )

        ready: asyncio.Future = asyncio.get_running_loop().create_future()
        self._stop = asyncio.Event()
        self._owner = asyncio.create_task(self._run(params, ready, self._stop))
        self._session = await ready
        self._started_at = time.time()
        print(f"[mcp] connected to {settings.paypal_mcp_package} ({environment})")

    @staticmethod
    async def _run(params, ready: asyncio.Future, stop: asyncio.Event) -> None:
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    ready.set_result(session)
                    await stop.wait()

        except Exception as exc:
            if not ready.done():
                ready.set_exception(exc)
            else:
                print(f"[mcp] connection lost: {type(exc).__name__}: {exc}")


mcp_client = PayPalMCPClient()
