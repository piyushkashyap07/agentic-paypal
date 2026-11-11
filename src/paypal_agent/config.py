import os

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    app_name: str = "PayPal AI Agent"
    app_env: str = "development"
    app_base_url: str = "http://127.0.0.1:8000"
    paypal_invoicer_email: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    ollama_api_key: str = ""
    ollama_model: str = "gpt-oss:120b"
    ollama_base_url: str = "https://ollama.com"
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_base_url: str = "https://api-m.sandbox.paypal.com"

    # How invoice calls reach PayPal: "mcp" (official PayPal MCP server)
    # or "rest" (direct REST API). Webhook verification always uses REST,
    # because PayPal MCP has no tool for it.
    paypal_transport: str = "mcp"
    paypal_mcp_package: str = "@paypal/mcp@1.8.1"

    # Browser origins allowed to make changes (our Next.js frontend).
    # Comma-separated. Anything else is refused (see api/security.py).
    allowed_origins: str = (
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:3001,http://127.0.0.1:3001"
    )

    @property
    def allowed_origin_list(self) -> set[str]:
        return {
            origin.strip().rstrip("/")
            for origin in self.allowed_origins.split(",")
            if origin.strip()
        }

    database_url: str = "sqlite+aiosqlite:///./paypal_agent.db"

    # Background payment monitor.
    monitor_enabled: bool = True
    monitor_interval_seconds: int = 60
    monitor_auto_remind: bool = True

    # Used when the user doesn't say when the invoice is due.
    default_due_days: int = 14

    # PayPal webhooks (see CHECKPOINT.md #8). Without an id we cannot verify
    # a webhook, so it is refused unless unverified ones are explicitly allowed.
    paypal_webhook_id: str = ""
    webhook_allow_unverified: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()