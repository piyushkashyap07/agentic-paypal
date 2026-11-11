import asyncio
from types import SimpleNamespace

import httpx

from paypal_agent.config import settings

# Gemini's OpenAI-compatible endpoint: plain HTTPS, no extra SDK needed.
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
)


# Busy (503) or rate-limited (429) answers are usually gone in seconds.
# Asking the model again has no side effects, so retry those briefly.
RETRY_STATUSES = {429, 503}
RETRY_DELAYS = (1, 3)


class GeminiError(RuntimeError):
    """Gemini returned an error. status_code lets the API explain it."""

    def __init__(self, status_code: int, message: str):
        super().__init__(f"Gemini failed ({status_code}): {message}")
        self.status_code = status_code


class GeminiClient:
    """Drop-in for the Ollama client: same chat() call, same result shape.

    The agent calls `await llm.chat(model=..., messages=..., format="json")`
    and reads `result.message.content`, so nothing else has to change.
    """

    def __init__(self, timeout: float):
        if not settings.gemini_api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is missing. Add it to your .env file."
            )

        self.timeout = timeout

    async def chat(self, model=None, messages=None, format=None, **kwargs):
        body = {
            "model": settings.gemini_model,
            "messages": messages or [],
            # Our tasks are simple (pull out fields, reword facts), so keep
            # the model's thinking low: faster, and lighter on the free quota.
            "reasoning_effort": "low",
        }

        if format == "json":
            body["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for delay in (*RETRY_DELAYS, None):
                response = await client.post(
                    GEMINI_URL,
                    headers={"Authorization": f"Bearer {settings.gemini_api_key}"},
                    json=body,
                )

                if response.status_code not in RETRY_STATUSES or delay is None:
                    break

                await asyncio.sleep(delay)

        if response.is_error:
            # Only the status and Google's short message: never the request,
            # which holds the user's chat.
            try:
                error = response.json()
                error = error[0] if isinstance(error, list) else error
                message = error.get("error", {}).get("message", "")
            except (ValueError, AttributeError):
                message = ""

            raise GeminiError(response.status_code, message[:200])

        content = response.json()["choices"][0]["message"].get("content") or ""

        return SimpleNamespace(message=SimpleNamespace(content=content))
