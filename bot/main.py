"""Telegram bot entry point for the finance assistant.

Run the bot:
    python -m bot.main

For Cloud Run deployment, set the PORT environment variable.
A lightweight HTTP health-check server runs alongside the bot.
"""

import datetime
import logging
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import pytz
from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from bot.handlers import (
    add_command,
    addbill_command,
    ask_command,
    bills_command,
    budget_command,
    delbill_command,
    delbudget_command,
    delete_callback,
    delete_command,
    help_command,
    month_command,
    monthall_command,
    setbudget_command,
    start_command,
    synccalendar_command,
    syncgmail_command,
    today_command,
    upcoming_command,
    unknown_command,
    unknown_text,
    week_command,
    weekall_command,
)
from bot.scheduled_tasks import (
    send_daily_summary,
    send_monthly_summary,
    send_weekly_summary,
    sync_calendar_scheduled,
    sync_gmail_scheduled,
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
    app.add_handler(CommandHandler("weekall", weekall_command))
    app.add_handler(CommandHandler("monthall", monthall_command))
    app.add_handler(CommandHandler("bills", bills_command))
    app.add_handler(CommandHandler("upcoming", upcoming_command))
    app.add_handler(CommandHandler("addbill", addbill_command))
    app.add_handler(CommandHandler("delbill", delbill_command))
    app.add_handler(CommandHandler("budget", budget_command))
    app.add_handler(CommandHandler("setbudget", setbudget_command))
    app.add_handler(CommandHandler("delbudget", delbudget_command))
    app.add_handler(CommandHandler("syncgmail", syncgmail_command))
    app.add_handler(CommandHandler("synccalendar", synccalendar_command))
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(CallbackQueryHandler(delete_callback, pattern=r"^del:"))

    # Catch-all handlers (must be registered last)
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_text))

    # Schedule automatic summaries
    if settings.auto_summaries_enabled:
        tz = pytz.timezone(settings.timezone)
        summary_time = datetime.time(hour=settings.daily_summary_hour, tzinfo=tz)

        app.job_queue.run_daily(
            send_daily_summary,
            time=summary_time,
            name="daily_summary",
        )
        app.job_queue.run_daily(
            send_weekly_summary,
            time=summary_time,
            days=(settings.weekly_summary_day,),
            name="weekly_summary",
        )
        app.job_queue.run_monthly(
            send_monthly_summary,
            when=summary_time,
            day=1,
            name="monthly_summary",
        )
        logger.info(
            "Auto summaries scheduled: daily at %s %s, weekly on day %d, monthly on 1st",
            settings.daily_summary_hour,
            settings.timezone,
            settings.weekly_summary_day,
        )
    else:
        logger.info("Auto summaries disabled")

    # Schedule Gmail sync
    if settings.gmail_sync_enabled:
        app.job_queue.run_repeating(
            sync_gmail_scheduled,
            interval=settings.gmail_sync_interval_hours * 3600,
            first=60,  # First run 60s after startup
            name="gmail_sync",
        )
        logger.info(
            "Gmail sync scheduled every %d hours", settings.gmail_sync_interval_hours
        )
    else:
        logger.info("Gmail sync disabled (set GMAIL_SYNC_ENABLED=true to enable)")

    # Schedule Calendar sync
    if settings.calendar_sync_enabled:
        tz = pytz.timezone(settings.timezone)
        cal_time = datetime.time(hour=settings.daily_summary_hour, tzinfo=tz)
        app.job_queue.run_daily(
            sync_calendar_scheduled,
            time=cal_time,
            name="calendar_sync",
        )
        logger.info("Calendar sync scheduled daily")
    else:
        logger.info("Calendar sync disabled (set CALENDAR_SYNC_ENABLED=true to enable)")

    # Start health-check server for Cloud Run (responds to HTTP probes)
    port = int(os.environ.get("PORT", "0"))
    if port:
        _start_health_server(port)
        logger.info("Health-check server listening on port %d", port)

    # Start polling for messages
    logger.info("Starting Telegram bot...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


class _HealthHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler for Cloud Run health checks."""

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format, *args):  # noqa: A002
        """Suppress default request logging to keep logs clean."""
        pass


def _start_health_server(port: int) -> None:
    """Start a background HTTP server for health checks."""
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    main()
