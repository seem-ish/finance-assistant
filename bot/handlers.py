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

from services.exceptions import DuplicateTransactionError, InvalidDataError

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

    Expected: /add <amount> <category> <description...>
    Example:  /add 25.50 groceries Whole Foods organic milk

    Returns dict with amount, category, description — or None if invalid.
    """
    if len(args) < 3:
        return None

    try:
        amount = float(args[0])
    except ValueError:
        return None

    category = args[1].capitalize()
    description = " ".join(args[2:])

    return {"amount": amount, "category": category, "description": description}


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
        "`/add <amount> <category> <description>`\n"
        "Example: `/add 25 groceries Whole Foods`\n\n"
        "*View Spending:*\n"
        "`/today` — Today's spending\n"
        "`/week` — This week's spending\n"
        "`/month` — This month's spending\n\n"
        "💡 Categories are auto-capitalized",
        parse_mode=ParseMode.MARKDOWN,
    )


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /add — add a new expense."""
    settings = context.bot_data["settings"]
    sheets = context.bot_data["sheets"]
    user = get_authorized_user(update, settings)
    if user is None:
        return

    parsed = parse_add_command(context.args or [])
    if parsed is None:
        await update.message.reply_text(
            "❌ Invalid format\\. Use:\n"
            "`/add <amount> <category> <description>`\n\n"
            "Example: `/add 25.50 groceries Whole Foods`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    try:
        transaction_id = sheets.add_transaction(
            amount=parsed["amount"],
            category=parsed["category"],
            description=parsed["description"],
            user=user,
            source="telegram",
        )
        currency = settings.currency_symbol
        await update.message.reply_text(
            f"✅ Added: {currency}{parsed['amount']:.2f} — {parsed['category']}\n"
            f"📝 {parsed['description']}\n"
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


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unknown commands."""
    settings = context.bot_data["settings"]
    user = get_authorized_user(update, settings)
    if user is None:
        return

    await update.message.reply_text("❓ Unknown command. Use /help to see available commands.")


async def unknown_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle plain text messages."""
    settings = context.bot_data["settings"]
    user = get_authorized_user(update, settings)
    if user is None:
        return

    await update.message.reply_text(
        "💬 To add an expense, use:\n"
        "`/add <amount> <category> <description>`\n\n"
        "Type /help for all commands.",
        parse_mode=ParseMode.MARKDOWN,
    )
