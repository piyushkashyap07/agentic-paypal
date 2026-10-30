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

    database_url: str = "sqlite+aiosqlite:///./paypal_agent.db"

    # Background payment monitor.
    monitor_enabled: bool = True
    monitor_interval_seconds: int = 60
    monitor_auto_remind: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()