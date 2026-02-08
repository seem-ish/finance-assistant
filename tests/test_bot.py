"""Tests for the Telegram bot handlers.

Run:
    pytest tests/test_bot.py -v
"""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from bot.handlers import (
    add_command,
    calculate_summary,
    get_authorized_user,
    get_user_name,
    month_command,
    parse_add_command,
    today_command,
    week_command,
)
from services.exceptions import DuplicateTransactionError, InvalidDataError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_settings():
    """Mock settings object."""
    s = MagicMock()
    s.telegram_user1_id = 7992938764
    s.telegram_user2_id = 111111111
    s.telegram_user1_name = "Seemran"
    s.telegram_user2_name = "Amit"
    s.currency_symbol = "$"
    return s


def _make_update(user_id: int):
    """Create a mock Telegram Update for a given user ID."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.message = AsyncMock()
    update.message.reply_text = AsyncMock()
    return update


@pytest.fixture
def update_user1():
    return _make_update(7992938764)


@pytest.fixture
def update_user2():
    return _make_update(111111111)


@pytest.fixture
def update_stranger():
    return _make_update(999999999)


@pytest.fixture
def mock_context(mock_settings):
    """Mock bot context with settings and sheets."""
    ctx = MagicMock()
    ctx.bot_data = {
        "settings": mock_settings,
        "sheets": MagicMock(),
    }
    ctx.args = []
    return ctx


# =========================================================================
# Authorization
# =========================================================================


class TestAuthorization:

    def test_user1_authorized(self, update_user1, mock_settings):
        assert get_authorized_user(update_user1, mock_settings) == "user1"

    def test_user2_authorized(self, update_user2, mock_settings):
        assert get_authorized_user(update_user2, mock_settings) == "user2"

    def test_stranger_rejected(self, update_stranger, mock_settings):
        assert get_authorized_user(update_stranger, mock_settings) is None

    def test_user1_name(self, mock_settings):
        assert get_user_name("user1", mock_settings) == "Seemran"

    def test_user2_name(self, mock_settings):
        assert get_user_name("user2", mock_settings) == "Amit"


# =========================================================================
# Command parsing
# =========================================================================


class TestParseAddCommand:

    def test_valid_simple(self):
        result = parse_add_command(["25", "groceries", "Whole", "Foods"])
        assert result == {
            "amount": 25.0,
            "category": "Groceries",
            "description": "Whole Foods",
        }

    def test_valid_decimal(self):
        result = parse_add_command(["25.50", "dining", "Chipotle", "lunch"])
        assert result["amount"] == 25.50
        assert result["category"] == "Dining"
        assert result["description"] == "Chipotle lunch"

    def test_long_description(self):
        result = parse_add_command(
            ["100", "shopping", "Amazon", "office", "supplies", "and", "books"]
        )
        assert result["description"] == "Amazon office supplies and books"

    def test_missing_description(self):
        assert parse_add_command(["25", "groceries"]) is None

    def test_missing_category(self):
        assert parse_add_command(["25"]) is None

    def test_empty_args(self):
        assert parse_add_command([]) is None

    def test_invalid_amount(self):
        assert parse_add_command(["abc", "groceries", "test"]) is None


# =========================================================================
# Summary formatting
# =========================================================================


class TestCalculateSummary:

    def test_empty_dataframe(self):
        assert calculate_summary(pd.DataFrame(), "$") == "No transactions found."

    def test_single_transaction(self):
        df = pd.DataFrame(
            [{"amount": 25.50, "category": "Groceries", "description": "WF"}]
        )
        result = calculate_summary(df, "$")
        assert "$25.50" in result
        assert "1 transaction" in result  # singular
        assert "Groceries" in result

    def test_multiple_categories(self):
        df = pd.DataFrame(
            [
                {"amount": 25.50, "category": "Groceries", "description": "WF"},
                {"amount": 15.00, "category": "Dining", "description": "Chipotle"},
                {"amount": 30.00, "category": "Groceries", "description": "TJ"},
            ]
        )
        result = calculate_summary(df, "$")
        assert "$70.50" in result
        assert "3 transactions" in result  # plural
        assert "Groceries: $55.50" in result
        assert "Dining: $15.00" in result

    def test_sorted_highest_first(self):
        df = pd.DataFrame(
            [
                {"amount": 10, "category": "Transport", "description": "Uber"},
                {"amount": 100, "category": "Shopping", "description": "Amazon"},
                {"amount": 50, "category": "Dining", "description": "Restaurant"},
            ]
        )
        result = calculate_summary(df, "$")
        assert result.index("Shopping") < result.index("Dining") < result.index("Transport")


# =========================================================================
# /add handler
# =========================================================================


class TestAddCommand:

    @pytest.mark.asyncio
    async def test_success(self, update_user1, mock_context):
        mock_context.args = ["25.50", "groceries", "Whole", "Foods"]
        mock_context.bot_data["sheets"].add_transaction.return_value = "abc12345"

        await add_command(update_user1, mock_context)

        # Sheets called correctly
        mock_context.bot_data["sheets"].add_transaction.assert_called_once_with(
            amount=25.50,
            category="Groceries",
            description="Whole Foods",
            user="user1",
            source="telegram",
        )
        # Response sent
        response = update_user1.message.reply_text.call_args[0][0]
        assert "✅" in response
        assert "$25.50" in response
        assert "abc12345" in response

    @pytest.mark.asyncio
    async def test_invalid_format(self, update_user1, mock_context):
        mock_context.args = ["25", "groceries"]  # missing description

        await add_command(update_user1, mock_context)

        mock_context.bot_data["sheets"].add_transaction.assert_not_called()
        response = update_user1.message.reply_text.call_args[0][0]
        assert "❌" in response

    @pytest.mark.asyncio
    async def test_duplicate(self, update_user1, mock_context):
        mock_context.args = ["25", "groceries", "Whole", "Foods"]
        mock_context.bot_data["sheets"].add_transaction.side_effect = (
            DuplicateTransactionError()
        )

        await add_command(update_user1, mock_context)

        response = update_user1.message.reply_text.call_args[0][0]
        assert "⚠️" in response
        assert "uplicate" in response  # "Duplicate" or "duplicate"

    @pytest.mark.asyncio
    async def test_unauthorized_silent(self, update_stranger, mock_context):
        mock_context.args = ["25", "groceries", "test"]

        await add_command(update_stranger, mock_context)

        update_stranger.message.reply_text.assert_not_called()
        mock_context.bot_data["sheets"].add_transaction.assert_not_called()


# =========================================================================
# /today handler
# =========================================================================


class TestTodayCommand:

    @pytest.mark.asyncio
    async def test_with_data(self, update_user1, mock_context):
        mock_context.bot_data["sheets"].get_transactions.return_value = pd.DataFrame(
            [
                {"amount": 25.50, "category": "Groceries", "description": "WF"},
                {"amount": 15.00, "category": "Dining", "description": "Chipotle"},
            ]
        )

        await today_command(update_user1, mock_context)

        # Correct date range
        call_kwargs = mock_context.bot_data["sheets"].get_transactions.call_args[1]
        assert call_kwargs["start_date"] == date.today()
        assert call_kwargs["end_date"] == date.today()
        assert call_kwargs["user"] == "user1"

        response = update_user1.message.reply_text.call_args[0][0]
        assert "$40.50" in response

    @pytest.mark.asyncio
    async def test_no_data(self, update_user1, mock_context):
        mock_context.bot_data["sheets"].get_transactions.return_value = pd.DataFrame()

        await today_command(update_user1, mock_context)

        response = update_user1.message.reply_text.call_args[0][0]
        assert "No transactions found" in response


# =========================================================================
# /week handler
# =========================================================================


class TestWeekCommand:

    @pytest.mark.asyncio
    async def test_starts_on_monday(self, update_user1, mock_context):
        mock_context.bot_data["sheets"].get_transactions.return_value = pd.DataFrame(
            [{"amount": 100, "category": "Shopping", "description": "Amazon"}]
        )

        await week_command(update_user1, mock_context)

        call_kwargs = mock_context.bot_data["sheets"].get_transactions.call_args[1]
        today = date.today()
        expected_monday = today - timedelta(days=today.weekday())
        assert call_kwargs["start_date"] == expected_monday
        assert call_kwargs["end_date"] == today


# =========================================================================
# /month handler
# =========================================================================


class TestMonthCommand:

    @pytest.mark.asyncio
    async def test_starts_on_first(self, update_user1, mock_context):
        mock_context.bot_data["sheets"].get_transactions.return_value = pd.DataFrame(
            [{"amount": 500, "category": "Groceries", "description": "Monthly"}]
        )

        await month_command(update_user1, mock_context)

        call_kwargs = mock_context.bot_data["sheets"].get_transactions.call_args[1]
        today = date.today()
        assert call_kwargs["start_date"] == date(today.year, today.month, 1)
        assert call_kwargs["end_date"] == today
