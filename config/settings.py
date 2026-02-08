"""Application settings loaded from environment variables."""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """All configuration for the finance assistant.

    Values are loaded from the .env file automatically.
    """

    # Telegram Bot
    telegram_bot_token: str = Field(description="Bot token from @BotFather")
    telegram_user1_id: int = Field(description="Your Telegram user ID")
    telegram_user2_id: int = Field(description="Your husband's Telegram user ID")
    telegram_user1_name: str = Field(default="User 1", description="Display name for user 1")
    telegram_user2_name: str = Field(default="User 2", description="Display name for user 2")

    # Google Sheets
    google_credentials_file: str = Field(
        default="config/google_credentials.json",
        description="Path to Google service account JSON key",
    )
    google_spreadsheet_id: str = Field(description="Google Sheets spreadsheet ID from URL")

    # Google Drive
    google_drive_folder_id: str = Field(
        default="", description="Google Drive folder ID for statement storage"
    )

    # App Settings
    currency_symbol: str = Field(default="$", description="Currency symbol for display")
    timezone: str = Field(default="America/New_York", description="Your timezone")
    daily_summary_hour: int = Field(
        default=8, description="Hour to send daily summary (24h format)"
    )
    weekly_summary_day: int = Field(
        default=0, description="Day for weekly summary (0=Monday)"
    )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


def get_settings() -> Settings:
    """Load and return application settings."""
    return Settings()
