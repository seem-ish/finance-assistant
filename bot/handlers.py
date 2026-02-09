"""Telegram bot command handlers.

Each handler:
1. Checks if the user is authorized (user1 or user2)
2. Identifies which user is messaging (maps telegram_id → "user1"/"user2")
3. Calls GoogleSheetsService methods
4. Sends formatted response with emojis
"""

import logging
from datetime import date, timedelta
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from services.bill_tracker import (
    format_bills_list,
    format_upcoming_reminder,
    get_upcoming_bills,
)
from services.budget_tracker import format_budget_status, get_budget_status
from services.exceptions import DuplicateTransactionError, InvalidDataError
from services.qa import answer_question

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper functions (testable without Telegram)
# ---------------------------------------------------------------------------


def get_authorized_user(update: Update, settings) -> Optional[str]:
    """Check if the user is authorized and return their identifier.

    Returns "user1", "user2", or None (unauthorized).
    """
    telegram_id = update.effective_user.id

    if telegram_id == settings.telegram_user1_id:
        return "user1"
    elif telegram_id == settings.telegram_user2_id:
        return "user2"
    else:
        logger.warning("Unauthorized access attempt from user_id: %s", telegram_id)
        return None


def get_user_name(user: str, settings) -> str:
    """Get display name for a user identifier."""
    if user == "user1":
        return settings.telegram_user1_name
    return settings.telegram_user2_name


def parse_add_command(args: list[str]) -> Optional[dict]:
    """Parse /add command arguments.

    Supports two formats:
        /add <amount> <category> <description...>   — explicit category
        /add <amount> <description...>               — auto-categorize

    Returns dict with amount, description, and optionally category.
    If category is not provided, it will be None (caller should auto-detect).
    Returns None if parsing fails entirely.
    """
    if len(args) < 2:
        return None

    try:
        amount = float(args[0])
    except ValueError:
        return None

    # The rest is either "category description..." or just "description..."
    # We'll return all remaining text as description, and let the caller
    # decide if the second word is a known category or part of description.
    remaining = args[1:]
    description = " ".join(remaining)

    return {"amount": amount, "category": None, "description": description}


def calculate_summary(df, currency_symbol: str) -> str:
    """Format a transactions DataFrame into a spending summary.

    Returns a string with total, transaction count, and per-category breakdown
    sorted by amount (highest first).
    """
    if df.empty:
        return "No transactions found."

    total = df["amount"].sum()
    count = len(df)
    txn_word = "transaction" if count == 1 else "transactions"

    lines = [f"💰 Total: {currency_symbol}{total:.2f} ({count} {txn_word})", ""]
    lines.append("📊 By Category:")

    by_category = (
        df.groupby("category")["amount"].sum().sort_values(ascending=False)
    )
    for category, amount in by_category.items():
        lines.append(f"  • {category}: {currency_symbol}{amount:.2f}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start — welcome message."""
    settings = context.bot_data["settings"]
    user = get_authorized_user(update, settings)
    if user is None:
        return

    name = get_user_name(user, settings)
    await update.message.reply_text(
        f"👋 Welcome to your Finance Assistant, {name}!\n\n"
        f"I help you track spending and stay on budget.\n"
        f"Use /help to see all commands."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help — list all commands."""
    settings = context.bot_data["settings"]
    user = get_authorized_user(update, settings)
    if user is None:
        return

    await update.message.reply_text(
        "📚 *Available Commands*\n\n"
        "*Add Expenses:*\n"
        "`/add <amount> <description>`\n"
        "Example: `/add 25 Whole Foods` → auto-detects Groceries\n\n"
        "*View Spending:*\n"
        "`/today` — Today's spending\n"
        "`/week` — This week's spending\n"
        "`/month` — This month's spending\n\n"
        "*Bills:*\n"
        "`/bills` — View all your bills\n"
        "`/upcoming` — Bills due in next 7 days\n"
        "`/addbill <name> <amount> <due_day>`\n"
        "`/delbill <name>` — Remove a bill\n\n"
        "*Budgets:*\n"
        "`/budget` — Budget status this month\n"
        "`/setbudget <category> <limit>`\n"
        "`/delbudget <category>`\n\n"
        "*Gmail:*\n"
        "`/syncgmail` — Scan Gmail for receipts & statements\n\n"
        "*Calendar:*\n"
        "`/synccalendar` — Sync bills to Google Calendar\n\n"
        "*Q&A:*\n"
        "`/ask <question>` — Ask about your finances\n"
        "Or just type a question directly!\n\n"
        "💡 Category is auto-detected from your description",
        parse_mode=ParseMode.MARKDOWN,
    )


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /add — add a new expense.

    Supports:
        /add 25 groceries Whole Foods   — explicit category
        /add 25 Whole Foods             — auto-categorize from description
    """
    settings = context.bot_data["settings"]
    sheets = context.bot_data["sheets"]
    categorizer = context.bot_data.get("categorizer")
    user = get_authorized_user(update, settings)
    if user is None:
        return

    parsed = parse_add_command(context.args or [])
    if parsed is None:
        await update.message.reply_text(
            "❌ Invalid format\\. Use:\n"
            "`/add <amount> <description>`\n"
            "or `/add <amount> <category> <description>`\n\n"
            "Example: `/add 25 Whole Foods`\n"
            "Example: `/add 25 groceries Whole Foods`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    description = parsed["description"]

    # Auto-categorize: check if the description matches any category keyword
    if categorizer:
        category = categorizer.categorize(description)
        icon = categorizer.get_icon(category)
    else:
        category = "Other"
        icon = "📦"

    try:
        transaction_id = sheets.add_transaction(
            amount=parsed["amount"],
            category=category,
            description=description,
            user=user,
            source="telegram",
        )
        currency = settings.currency_symbol
        auto_tag = " (auto)" if parsed["category"] is None else ""
        await update.message.reply_text(
            f"✅ Added: {currency}{parsed['amount']:.2f} — {icon} {category}{auto_tag}\n"
            f"📝 {description}\n"
            f"🆔 {transaction_id}"
        )

    except InvalidDataError as e:
        await update.message.reply_text(f"❌ {e}")
    except DuplicateTransactionError:
        await update.message.reply_text(
            "⚠️ Duplicate transaction — not added to avoid double-counting."
        )
    except Exception as e:
        logger.error("Error adding transaction: %s", e)
        await update.message.reply_text(
            "❌ Something went wrong. Please try again later."
        )


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /today — show today's spending."""
    settings = context.bot_data["settings"]
    sheets = context.bot_data["sheets"]
    user = get_authorized_user(update, settings)
    if user is None:
        return

    try:
        today = date.today()
        df = sheets.get_transactions(start_date=today, end_date=today, user=user)
        summary = calculate_summary(df, settings.currency_symbol)
        header = f"📅 Today's Spending ({today.strftime('%B %d, %Y')})"
        await update.message.reply_text(f"{header}\n\n{summary}")

    except Exception as e:
        logger.error("Error fetching today's transactions: %s", e)
        await update.message.reply_text(
            "❌ Couldn't fetch today's data. Please try again later."
        )


async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /week — show this week's spending (Monday–today)."""
    settings = context.bot_data["settings"]
    sheets = context.bot_data["sheets"]
    user = get_authorized_user(update, settings)
    if user is None:
        return

    try:
        today = date.today()
        week_start = today - timedelta(days=today.weekday())  # Monday
        df = sheets.get_transactions(start_date=week_start, end_date=today, user=user)
        summary = calculate_summary(df, settings.currency_symbol)
        header = f"📅 This Week ({week_start.strftime('%b %d')} — {today.strftime('%b %d')})"
        await update.message.reply_text(f"{header}\n\n{summary}")

    except Exception as e:
        logger.error("Error fetching week's transactions: %s", e)
        await update.message.reply_text(
            "❌ Couldn't fetch this week's data. Please try again later."
        )


async def month_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /month — show this month's spending."""
    settings = context.bot_data["settings"]
    sheets = context.bot_data["sheets"]
    user = get_authorized_user(update, settings)
    if user is None:
        return

    try:
        today = date.today()
        month_start = date(today.year, today.month, 1)
        df = sheets.get_transactions(start_date=month_start, end_date=today, user=user)
        summary = calculate_summary(df, settings.currency_symbol)
        header = f"📅 This Month ({today.strftime('%B %Y')})"
        await update.message.reply_text(f"{header}\n\n{summary}")

    except Exception as e:
        logger.error("Error fetching month's transactions: %s", e)
        await update.message.reply_text(
            "❌ Couldn't fetch this month's data. Please try again later."
        )


async def bills_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /bills — show all active bills."""
    settings = context.bot_data["settings"]
    sheets = context.bot_data["sheets"]
    user = get_authorized_user(update, settings)
    if user is None:
        return

    try:
        df = sheets.get_bills(active_only=True, user=user)
        message = format_bills_list(df, settings.currency_symbol)
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error("Error fetching bills: %s", e)
        await update.message.reply_text("❌ Couldn't fetch bills. Please try again later.")


async def upcoming_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /upcoming — show bills due in the next 7 days."""
    settings = context.bot_data["settings"]
    sheets = context.bot_data["sheets"]
    user = get_authorized_user(update, settings)
    if user is None:
        return

    try:
        bills = get_upcoming_bills(sheets, user=user, days_ahead=7)
        message = format_upcoming_reminder(bills, settings.currency_symbol)
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error("Error fetching upcoming bills: %s", e)
        await update.message.reply_text(
            "❌ Couldn't fetch upcoming bills. Please try again later."
        )


async def addbill_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /addbill — add a recurring bill.

    Format: /addbill <name> <amount> <due_day>
    Example: /addbill Netflix 15.99 15
    """
    settings = context.bot_data["settings"]
    sheets = context.bot_data["sheets"]
    categorizer = context.bot_data.get("categorizer")
    user = get_authorized_user(update, settings)
    if user is None:
        return

    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text(
            "❌ Usage: `/addbill <name> <amount> <due_day>`\n\n"
            "Example: `/addbill Netflix 15.99 15`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    name = args[0]
    try:
        amount = float(args[1])
        due_day = int(args[2])
    except ValueError:
        await update.message.reply_text(
            "❌ Amount must be a number and due day must be an integer.\n\n"
            "Example: `/addbill Netflix 15.99 15`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Auto-detect category from bill name
    if categorizer:
        category = categorizer.categorize(name)
    else:
        category = "Other"

    try:
        bill_id = sheets.add_bill(
            name=name,
            amount=amount,
            due_day=due_day,
            frequency="monthly",
            category=category,
            user=user,
        )
        currency = settings.currency_symbol
        msg = (
            f"✅ Added bill: {name} — {currency}{amount:,.2f} "
            f"due on day {due_day} (monthly)\n"
            f"🆔 {bill_id}"
        )

        # Auto-create calendar event if enabled
        if settings.calendar_sync_enabled:
            try:
                from services.bill_tracker import get_next_due_date
                from services.calendar import CalendarService

                cal = CalendarService(
                    credentials_file=settings.gmail_oauth_credentials_file,
                    token_file=settings.calendar_token_file,
                    calendar_id=settings.calendar_id,
                )
                if cal.authenticate():
                    due_date = get_next_due_date(due_day)
                    event_id = cal.create_bill_event(
                        name=name,
                        amount=amount,
                        due_date=due_date,
                        category=category,
                    )
                    if event_id:
                        msg += "\n📅 Calendar event created"
            except Exception as e:
                logger.error("Failed to create calendar event: %s", e)

        await update.message.reply_text(msg)
    except InvalidDataError as e:
        await update.message.reply_text(f"❌ {e}")
    except Exception as e:
        logger.error("Error adding bill: %s", e)
        await update.message.reply_text("❌ Something went wrong. Please try again.")


async def delbill_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /delbill — delete a bill by name.

    Format: /delbill <name>
    Example: /delbill Netflix
    """
    settings = context.bot_data["settings"]
    sheets = context.bot_data["sheets"]
    user = get_authorized_user(update, settings)
    if user is None:
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "❌ Usage: `/delbill <name>`\n\n"
            "Example: `/delbill Netflix`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    name = " ".join(args)

    # Find the bill by name
    df = sheets.get_bills(user=user)
    match = df[df["name"].str.lower() == name.lower()]

    if match.empty:
        await update.message.reply_text(
            f"❌ No bill found with name '{name}'.\n\n"
            f"Use /bills to see your current bills."
        )
        return

    bill_id = match.iloc[0]["id"]
    try:
        sheets.delete_bill(bill_id)
        await update.message.reply_text(f"✅ Deleted bill: {name}")
    except Exception as e:
        logger.error("Error deleting bill: %s", e)
        await update.message.reply_text("❌ Couldn't delete the bill. Please try again.")


async def budget_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /budget — show budget status for current month."""
    settings = context.bot_data["settings"]
    sheets = context.bot_data["sheets"]
    user = get_authorized_user(update, settings)
    if user is None:
        return

    try:
        statuses = get_budget_status(sheets, user=user)
        message = format_budget_status(statuses, settings.currency_symbol)
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error("Error fetching budget status: %s", e)
        await update.message.reply_text(
            "❌ Couldn't fetch budget status. Please try again later."
        )


async def setbudget_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /setbudget — set a monthly budget for a category.

    Format: /setbudget <category> <limit>
    Example: /setbudget Groceries 500
    """
    settings = context.bot_data["settings"]
    sheets = context.bot_data["sheets"]
    user = get_authorized_user(update, settings)
    if user is None:
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "❌ Usage: `/setbudget <category> <limit>`\n\n"
            "Example: `/setbudget Groceries 500`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    category = args[0].capitalize()
    try:
        limit = float(args[1])
    except ValueError:
        await update.message.reply_text(
            "❌ Limit must be a number.\n\n"
            "Example: `/setbudget Groceries 500`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        sheets.set_budget(category=category, monthly_limit=limit, user=user)
        currency = settings.currency_symbol
        await update.message.reply_text(
            f"✅ Budget set: {category} — {currency}{limit:,.2f}/month"
        )
    except InvalidDataError as e:
        await update.message.reply_text(f"❌ {e}")
    except Exception as e:
        logger.error("Error setting budget: %s", e)
        await update.message.reply_text("❌ Something went wrong. Please try again.")


async def delbudget_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /delbudget — delete a budget for a category.

    Format: /delbudget <category>
    Example: /delbudget Groceries
    """
    settings = context.bot_data["settings"]
    sheets = context.bot_data["sheets"]
    user = get_authorized_user(update, settings)
    if user is None:
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "❌ Usage: `/delbudget <category>`\n\n"
            "Example: `/delbudget Groceries`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    category = " ".join(args).capitalize()

    try:
        deleted = sheets.delete_budget(category=category, user=user)
        if deleted:
            await update.message.reply_text(f"✅ Deleted budget for {category}")
        else:
            await update.message.reply_text(
                f"❌ No budget found for '{category}'.\n\n"
                f"Use /budget to see your current budgets."
            )
    except Exception as e:
        logger.error("Error deleting budget: %s", e)
        await update.message.reply_text("❌ Couldn't delete the budget. Please try again.")


async def syncgmail_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /syncgmail — manually trigger Gmail scan."""
    settings = context.bot_data["settings"]
    sheets = context.bot_data["sheets"]
    categorizer = context.bot_data.get("categorizer")
    user = get_authorized_user(update, settings)
    if user is None:
        return

    if not settings.gmail_sync_enabled:
        await update.message.reply_text(
            "❌ Gmail sync is not enabled.\n\n"
            "Run `python -m scripts.setup_gmail` to set up Gmail integration, "
            "then set `GMAIL_SYNC_ENABLED=true` in your .env file.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text("🔄 Scanning Gmail (last 7 days)...")

    try:
        from services.gmail import GmailService, sync_gmail

        gmail = GmailService(
            credentials_file=settings.gmail_oauth_credentials_file,
            token_file=settings.gmail_token_file,
        )
        if not gmail.authenticate():
            await update.message.reply_text(
                "❌ Gmail authentication failed. Run `python -m scripts.setup_gmail` to re-authenticate.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        results = sync_gmail(
            gmail, sheets, categorizer, user=user, days_back=7
        )

        lines = ["📧 *Gmail Sync Complete*\n"]
        if results["receipts_added"]:
            lines.append(f"✅ {results['receipts_added']} receipts imported")
        if results["statements_imported"]:
            lines.append(
                f"✅ {results['statements_imported']} statement transactions imported"
            )
        if results["skipped"]:
            lines.append(f"⏭️ {results['skipped']} duplicates skipped")
        if results["errors"]:
            lines.append(f"⚠️ {results['errors']} errors")
        if not any(results.values()):
            lines.append("No new transactions found.")

        await update.message.reply_text(
            "\n".join(lines), parse_mode=ParseMode.MARKDOWN
        )

    except Exception as e:
        logger.error("Error in Gmail sync: %s", e)
        await update.message.reply_text("❌ Gmail sync failed. Check logs for details.")


async def synccalendar_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /synccalendar — sync all bills to Google Calendar."""
    settings = context.bot_data["settings"]
    sheets = context.bot_data["sheets"]
    user = get_authorized_user(update, settings)
    if user is None:
        return

    if not settings.calendar_sync_enabled:
        await update.message.reply_text(
            "❌ Calendar sync is not enabled.\n\n"
            "Run `python -m scripts.setup_calendar` to set up, "
            "then set `CALENDAR_SYNC_ENABLED=true` in your .env file.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text("📅 Syncing bills to Google Calendar...")

    try:
        from services.calendar import CalendarService, sync_bills_to_calendar

        cal = CalendarService(
            credentials_file=settings.gmail_oauth_credentials_file,
            token_file=settings.calendar_token_file,
            calendar_id=settings.calendar_id,
        )
        if not cal.authenticate():
            await update.message.reply_text(
                "❌ Calendar authentication failed. Run `python -m scripts.setup_calendar` to re-authenticate.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        results = sync_bills_to_calendar(cal, sheets, user=user)

        lines = ["📅 *Calendar Sync Complete*\n"]
        if results["created"]:
            lines.append(f"✅ {results['created']} bill events created")
        if results["existing"]:
            lines.append(f"⏭️ {results['existing']} already on calendar")
        if results["errors"]:
            lines.append(f"⚠️ {results['errors']} errors")
        if not any(results.values()):
            lines.append("No active bills to sync.")

        await update.message.reply_text(
            "\n".join(lines), parse_mode=ParseMode.MARKDOWN
        )

    except Exception as e:
        logger.error("Error in Calendar sync: %s", e)
        await update.message.reply_text("❌ Calendar sync failed. Check logs for details.")


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unknown commands."""
    settings = context.bot_data["settings"]
    user = get_authorized_user(update, settings)
    if user is None:
        return

    await update.message.reply_text("❓ Unknown command. Use /help to see available commands.")


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /ask — ask a natural language question about finances."""
    settings = context.bot_data["settings"]
    sheets = context.bot_data["sheets"]
    user = get_authorized_user(update, settings)
    if user is None:
        return

    question = " ".join(context.args or [])
    if not question:
        await update.message.reply_text(
            "❓ Usage: `/ask <question>`\n\n"
            "Example: `/ask How much did I spend on groceries this month?`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text("🤔 Thinking...")

    try:
        response = answer_question(question, sheets, user, settings)
        await update.message.reply_text(f"💬 {response}")
    except Exception as e:
        logger.error("Error in /ask command: %s", e)
        await update.message.reply_text(
            "❌ Something went wrong. Please try again later."
        )


async def unknown_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle plain text messages — Q&A if enabled, otherwise prompt to use /add."""
    settings = context.bot_data["settings"]
    sheets = context.bot_data["sheets"]
    user = get_authorized_user(update, settings)
    if user is None:
        return

    # If Q&A is enabled, treat plain text as a question
    if settings.qa_enabled:
        question = update.message.text.strip()
        if not question:
            return

        await update.message.reply_text("🤔 Thinking...")

        try:
            response = answer_question(question, sheets, user, settings)
            await update.message.reply_text(f"💬 {response}")
        except Exception as e:
            logger.error("Error in Q&A: %s", e)
            await update.message.reply_text(
                "❌ Something went wrong. Please try again later."
            )
        return

    # Q&A disabled — show the original help message
    await update.message.reply_text(
        "💬 To add an expense, use:\n"
        "`/add <amount> <category> <description>`\n\n"
        "Type /help for all commands.",
        parse_mode=ParseMode.MARKDOWN,
    )
