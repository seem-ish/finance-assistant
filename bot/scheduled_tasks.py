"""Scheduled tasks for automatic summary messages.

These functions are called by APScheduler (via python-telegram-bot's JobQueue)
to send daily, weekly, and monthly spending summaries to users.
"""

import calendar
import logging
from datetime import date, timedelta

from telegram.ext import ContextTypes

from bot.handlers import calculate_summary
from services.bill_tracker import format_upcoming_reminder, get_upcoming_bills
from services.budget_tracker import (
    format_budget_status,
    get_budget_alerts,
    get_budget_status,
)

logger = logging.getLogger(__name__)


def _build_user_list(settings) -> list[tuple[int, str]]:
    """Return list of (chat_id, user_key) for active users.

    Skips user2 if ID is the placeholder value (000000000).
    """
    users = [(settings.telegram_user1_id, "user1")]
    if settings.telegram_user2_id and settings.telegram_user2_id != 0:
        users.append((settings.telegram_user2_id, "user2"))
    return users


async def send_daily_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send yesterday's spending summary + upcoming bills (next 3 days).

    Skips sending if there are no transactions and no upcoming bills.
    """
    settings = context.bot_data["settings"]
    if not settings.auto_summaries_enabled:
        return

    sheets = context.bot_data["sheets"]
    users = _build_user_list(settings)
    yesterday = date.today() - timedelta(days=1)

    for chat_id, user_key in users:
        try:
            # Yesterday's transactions
            df = sheets.get_transactions(
                start_date=yesterday, end_date=yesterday, user=user_key
            )
            spending_summary = calculate_summary(df, settings.currency_symbol)

            # Upcoming bills (next 3 days)
            upcoming = get_upcoming_bills(sheets, user=user_key, days_ahead=3)
            bills_text = format_upcoming_reminder(upcoming, settings.currency_symbol)

            has_transactions = not df.empty
            has_bills = len(upcoming) > 0

            # Skip if nothing to report
            if not has_transactions and not has_bills:
                continue

            # Compose message
            sections = [f"📅 *Daily Summary — {yesterday.strftime('%B %d, %Y')}*"]

            if has_transactions:
                sections.append("")
                sections.append(spending_summary)

            if has_bills:
                sections.append("")
                sections.append(bills_text)

            message = "\n".join(sections)
            await context.bot.send_message(chat_id=chat_id, text=message)

        except Exception as e:
            logger.error("Error sending daily summary to %s: %s", user_key, e)


async def send_weekly_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send this week's spending summary + budget alerts + upcoming bills.

    Runs on the configured weekly_summary_day (default Monday).
    """
    settings = context.bot_data["settings"]
    if not settings.auto_summaries_enabled:
        return

    sheets = context.bot_data["sheets"]
    users = _build_user_list(settings)
    today = date.today()
    week_start = today - timedelta(days=today.weekday())  # Monday

    for chat_id, user_key in users:
        try:
            # Week's transactions
            df = sheets.get_transactions(
                start_date=week_start, end_date=today, user=user_key
            )
            spending_summary = calculate_summary(df, settings.currency_symbol)

            # Budget alerts
            statuses = get_budget_status(sheets, user=user_key)
            alerts = get_budget_alerts(statuses)

            # Upcoming bills (next 7 days)
            upcoming = get_upcoming_bills(sheets, user=user_key, days_ahead=7)
            bills_text = format_upcoming_reminder(upcoming, settings.currency_symbol)

            has_transactions = not df.empty
            has_alerts = len(alerts) > 0
            has_bills = len(upcoming) > 0

            if not has_transactions and not has_alerts and not has_bills:
                continue

            # Compose message
            sections = [
                f"📊 *Weekly Summary — Week of {week_start.strftime('%B %d')}*"
            ]

            if has_transactions:
                sections.append("")
                sections.append(spending_summary)

            if has_alerts:
                sections.append("")
                sections.append("⚠️ *Budget Alerts:*")
                for alert in alerts:
                    sections.append(f"  {alert}")

            if has_bills:
                sections.append("")
                sections.append(bills_text)

            message = "\n".join(sections)
            await context.bot.send_message(chat_id=chat_id, text=message)

        except Exception as e:
            logger.error("Error sending weekly summary to %s: %s", user_key, e)


async def send_monthly_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send last month's full spending summary + budget status recap.

    Runs on the 1st of each month, summarizing the previous month.
    """
    settings = context.bot_data["settings"]
    if not settings.auto_summaries_enabled:
        return

    sheets = context.bot_data["sheets"]
    users = _build_user_list(settings)
    today = date.today()

    # Calculate last month's date range
    if today.month == 1:
        last_month_start = date(today.year - 1, 12, 1)
        last_month_end = date(today.year - 1, 12, 31)
    else:
        last_month = today.month - 1
        last_month_start = date(today.year, last_month, 1)
        last_day = calendar.monthrange(today.year, last_month)[1]
        last_month_end = date(today.year, last_month, last_day)

    month_name = last_month_start.strftime("%B %Y")

    for chat_id, user_key in users:
        try:
            # Last month's transactions
            df = sheets.get_transactions(
                start_date=last_month_start,
                end_date=last_month_end,
                user=user_key,
            )
            spending_summary = calculate_summary(df, settings.currency_symbol)

            # Budget status for last month
            statuses = get_budget_status(
                sheets, user=user_key, reference_date=last_month_end
            )
            budget_text = format_budget_status(statuses, settings.currency_symbol)

            has_transactions = not df.empty
            has_budgets = len(statuses) > 0

            if not has_transactions and not has_budgets:
                continue

            # Compose message
            sections = [f"📆 *Monthly Summary — {month_name}*"]

            if has_transactions:
                sections.append("")
                sections.append(spending_summary)

            if has_budgets:
                sections.append("")
                sections.append("📊 *Budget Recap:*")
                sections.append(budget_text)

            message = "\n".join(sections)
            await context.bot.send_message(chat_id=chat_id, text=message)

        except Exception as e:
            logger.error("Error sending monthly summary to %s: %s", user_key, e)


async def sync_gmail_scheduled(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Scheduled Gmail sync — scan last 24h for purchase receipts and statements."""
    settings = context.bot_data["settings"]
    if not settings.gmail_sync_enabled:
        return

    sheets = context.bot_data["sheets"]
    categorizer = context.bot_data.get("categorizer")
    users = _build_user_list(settings)

    try:
        from services.gmail import GmailService, sync_gmail

        gmail = GmailService(
            credentials_file=settings.gmail_oauth_credentials_file,
            token_file=settings.gmail_token_file,
        )
        if not gmail.authenticate():
            logger.error("Gmail authentication failed during scheduled sync")
            return

        # Only sync for user1 (Gmail is set up for one account)
        user_key = "user1"
        chat_id = settings.telegram_user1_id

        results = sync_gmail(gmail, sheets, categorizer, user=user_key, days_back=1)

        total_new = results["receipts_added"] + results["statements_imported"]
        if total_new > 0:
            lines = ["📧 *Gmail Auto-Sync*\n"]
            if results["receipts_added"]:
                lines.append(f"✅ {results['receipts_added']} receipts imported")
            if results["statements_imported"]:
                lines.append(
                    f"✅ {results['statements_imported']} statement transactions"
                )
            if results["skipped"]:
                lines.append(f"⏭️ {results['skipped']} duplicates skipped")

            await context.bot.send_message(
                chat_id=chat_id, text="\n".join(lines)
            )

        logger.info(
            "Gmail sync complete: %d receipts, %d statements, %d skipped, %d errors",
            results["receipts_added"],
            results["statements_imported"],
            results["skipped"],
            results["errors"],
        )

    except Exception as e:
        logger.error("Gmail scheduled sync failed: %s", e)
