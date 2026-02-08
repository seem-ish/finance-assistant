"""Telegram bot entry point for the finance assistant.

Run the bot:
    python -m bot.main
"""

import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from bot.handlers import (
    add_command,
    help_command,
    month_command,
    start_command,
    today_command,
    unknown_command,
    unknown_text,
    week_command,
)
from config.settings import get_settings
from services.categorizer import Categorizer
from services.sheets import GoogleSheetsService

logger = logging.getLogger(__name__)


def main() -> None:
    """Initialize and run the Telegram bot."""
    # Load configuration
    settings = get_settings()

    # Connect to Google Sheets
    sheets = GoogleSheetsService(
        credentials_file=settings.google_credentials_file,
        spreadsheet_id=settings.google_spreadsheet_id,
    )
    sheets.initialize()
    logger.info("Google Sheets service initialized")

    # Create bot application
    app = Application.builder().token(settings.telegram_bot_token).build()

    # Initialize categorizer
    categorizer = Categorizer(sheets)
    logger.info("Transaction categorizer initialized")

    # Store shared objects so handlers can access them via context.bot_data
    app.bot_data["settings"] = settings
    app.bot_data["sheets"] = sheets
    app.bot_data["categorizer"] = categorizer

    # Register command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("add", add_command))
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("week", week_command))
    app.add_handler(CommandHandler("month", month_command))

    # Catch-all handlers (must be registered last)
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_text))

    # Start polling for messages
    logger.info("Starting Telegram bot...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    main()
