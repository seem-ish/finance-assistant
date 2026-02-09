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
    addbill_command,
    bills_command,
    budget_command,
    calculate_summary,
    delbill_command,
    delbudget_command,
    get_authorized_user,
    get_user_name,
    month_command,
    parse_add_command,
    setbudget_command,
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
def mock_categorizer():
    """Mock Categorizer that returns predictable results."""
    cat = MagicMock()
    cat.categorize.return_value = "Groceries"
    cat.get_icon.return_value = "🛒"
    return cat


@pytest.fixture
def mock_context(mock_settings, mock_categorizer):
    """Mock bot context with settings, sheets, and categorizer."""
    ctx = MagicMock()
    ctx.bot_data = {
        "settings": mock_settings,
        "sheets": MagicMock(),
        "categorizer": mock_categorizer,
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
        result = parse_add_command(["25", "Whole", "Foods"])
        assert result == {
            "amount": 25.0,
            "category": None,
            "description": "Whole Foods",
        }

    def test_valid_decimal(self):
        result = parse_add_command(["25.50", "Chipotle", "lunch"])
        assert result["amount"] == 25.50
        assert result["category"] is None
        assert result["description"] == "Chipotle lunch"

    def test_long_description(self):
        result = parse_add_command(
            ["100", "Amazon", "office", "supplies", "and", "books"]
        )
        assert result["description"] == "Amazon office supplies and books"

    def test_single_word_description(self):
        result = parse_add_command(["25", "Starbucks"])
        assert result == {
            "amount": 25.0,
            "category": None,
            "description": "Starbucks",
        }

    def test_missing_description(self):
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
        mock_context.args = ["25.50", "Whole", "Foods"]
        mock_context.bot_data["sheets"].add_transaction.return_value = "abc12345"

        await add_command(update_user1, mock_context)

        # Sheets called with auto-categorized category
        mock_context.bot_data["sheets"].add_transaction.assert_called_once_with(
            amount=25.50,
            category="Groceries",
            description="Whole Foods",
            user="user1",
            source="telegram",
        )
        # Categorizer was called with the description
        mock_context.bot_data["categorizer"].categorize.assert_called_once_with(
            "Whole Foods"
        )
        # Response sent
        response = update_user1.message.reply_text.call_args[0][0]
        assert "✅" in response
        assert "$25.50" in response
        assert "abc12345" in response
        assert "Groceries" in response

    @pytest.mark.asyncio
    async def test_invalid_format(self, update_user1, mock_context):
        mock_context.args = ["25"]  # missing description

        await add_command(update_user1, mock_context)

        mock_context.bot_data["sheets"].add_transaction.assert_not_called()
        response = update_user1.message.reply_text.call_args[0][0]
        assert "❌" in response

    @pytest.mark.asyncio
    async def test_duplicate(self, update_user1, mock_context):
        mock_context.args = ["25", "Whole", "Foods"]
        mock_context.bot_data["sheets"].add_transaction.side_effect = (
            DuplicateTransactionError()
        )

        await add_command(update_user1, mock_context)

        response = update_user1.message.reply_text.call_args[0][0]
        assert "⚠️" in response
        assert "uplicate" in response  # "Duplicate" or "duplicate"

    @pytest.mark.asyncio
    async def test_unauthorized_silent(self, update_stranger, mock_context):
        mock_context.args = ["25", "Whole", "Foods"]

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


# =========================================================================
# /bills handler
# =========================================================================


class TestBillsCommand:

    @pytest.mark.asyncio
    async def test_with_bills(self, update_user1, mock_context):
        mock_context.bot_data["sheets"].get_bills.return_value = pd.DataFrame(
            [
                {"name": "Netflix", "amount": 15.99, "due_day": 15,
                 "frequency": "monthly", "auto_pay": True},
            ]
        )

        await bills_command(update_user1, mock_context)

        response = update_user1.message.reply_text.call_args[0][0]
        assert "Netflix" in response
        assert "$15.99" in response

    @pytest.mark.asyncio
    async def test_empty_bills(self, update_user1, mock_context):
        mock_context.bot_data["sheets"].get_bills.return_value = pd.DataFrame()

        await bills_command(update_user1, mock_context)

        response = update_user1.message.reply_text.call_args[0][0]
        assert "No bills" in response


# =========================================================================
# /addbill handler
# =========================================================================


class TestAddBillCommand:

    @pytest.mark.asyncio
    async def test_success(self, update_user1, mock_context):
        mock_context.args = ["Netflix", "15.99", "15"]
        mock_context.bot_data["sheets"].add_bill.return_value = "bill123"

        await addbill_command(update_user1, mock_context)

        mock_context.bot_data["sheets"].add_bill.assert_called_once()
        call_kwargs = mock_context.bot_data["sheets"].add_bill.call_args[1]
        assert call_kwargs["name"] == "Netflix"
        assert call_kwargs["amount"] == 15.99
        assert call_kwargs["due_day"] == 15

        response = update_user1.message.reply_text.call_args[0][0]
        assert "✅" in response
        assert "Netflix" in response

    @pytest.mark.asyncio
    async def test_invalid_format(self, update_user1, mock_context):
        mock_context.args = ["Netflix"]  # missing amount and due_day

        await addbill_command(update_user1, mock_context)

        mock_context.bot_data["sheets"].add_bill.assert_not_called()
        response = update_user1.message.reply_text.call_args[0][0]
        assert "❌" in response

    @pytest.mark.asyncio
    async def test_unauthorized_silent(self, update_stranger, mock_context):
        mock_context.args = ["Netflix", "15.99", "15"]

        await addbill_command(update_stranger, mock_context)

        update_stranger.message.reply_text.assert_not_called()


# =========================================================================
# /delbill handler
# =========================================================================


class TestDelBillCommand:

    @pytest.mark.asyncio
    async def test_success(self, update_user1, mock_context):
        mock_context.args = ["Netflix"]
        mock_context.bot_data["sheets"].get_bills.return_value = pd.DataFrame(
            [{"id": "bill123", "name": "Netflix", "amount": 15.99}]
        )
        mock_context.bot_data["sheets"].delete_bill.return_value = True

        await delbill_command(update_user1, mock_context)

        mock_context.bot_data["sheets"].delete_bill.assert_called_once_with("bill123")
        response = update_user1.message.reply_text.call_args[0][0]
        assert "✅" in response
        assert "Netflix" in response

    @pytest.mark.asyncio
    async def test_not_found(self, update_user1, mock_context):
        mock_context.args = ["NonExistent"]
        mock_context.bot_data["sheets"].get_bills.return_value = pd.DataFrame(
            [{"id": "bill123", "name": "Netflix", "amount": 15.99}]
        )

        await delbill_command(update_user1, mock_context)

        mock_context.bot_data["sheets"].delete_bill.assert_not_called()
        response = update_user1.message.reply_text.call_args[0][0]
        assert "❌" in response
        assert "No bill found" in response


# =========================================================================
# /budget handler
# =========================================================================


class TestBudgetCommand:

    @pytest.mark.asyncio
    async def test_with_budgets(self, update_user1, mock_context):
        mock_context.bot_data["sheets"].get_budgets.return_value = pd.DataFrame(
            [{"category": "Groceries", "monthly_limit": 500, "user": "user1"}]
        )
        mock_context.bot_data["sheets"].get_transactions.return_value = pd.DataFrame(
            [{"amount": 200, "category": "Groceries"}]
        )

        await budget_command(update_user1, mock_context)

        response = update_user1.message.reply_text.call_args[0][0]
        assert "Groceries" in response
        assert "█" in response

    @pytest.mark.asyncio
    async def test_empty_budgets(self, update_user1, mock_context):
        mock_context.bot_data["sheets"].get_budgets.return_value = pd.DataFrame(
            columns=["category", "monthly_limit", "user"]
        )

        await budget_command(update_user1, mock_context)

        response = update_user1.message.reply_text.call_args[0][0]
        assert "No budgets" in response


# =========================================================================
# /setbudget handler
# =========================================================================


class TestSetBudgetCommand:

    @pytest.mark.asyncio
    async def test_success(self, update_user1, mock_context):
        mock_context.args = ["Groceries", "500"]

        await setbudget_command(update_user1, mock_context)

        mock_context.bot_data["sheets"].set_budget.assert_called_once_with(
            category="Groceries", monthly_limit=500.0, user="user1"
        )
        response = update_user1.message.reply_text.call_args[0][0]
        assert "✅" in response
        assert "Groceries" in response
        assert "$500.00" in response

    @pytest.mark.asyncio
    async def test_invalid_format(self, update_user1, mock_context):
        mock_context.args = ["Groceries"]  # missing limit

        await setbudget_command(update_user1, mock_context)

        mock_context.bot_data["sheets"].set_budget.assert_not_called()
        response = update_user1.message.reply_text.call_args[0][0]
        assert "❌" in response

    @pytest.mark.asyncio
    async def test_unauthorized_silent(self, update_stranger, mock_context):
        mock_context.args = ["Groceries", "500"]

        await setbudget_command(update_stranger, mock_context)

        update_stranger.message.reply_text.assert_not_called()


# =========================================================================
# /delbudget handler
# =========================================================================


class TestDelBudgetCommand:

    @pytest.mark.asyncio
    async def test_success(self, update_user1, mock_context):
        mock_context.args = ["Groceries"]
        mock_context.bot_data["sheets"].delete_budget.return_value = True

        await delbudget_command(update_user1, mock_context)

        mock_context.bot_data["sheets"].delete_budget.assert_called_once_with(
            category="Groceries", user="user1"
        )
        response = update_user1.message.reply_text.call_args[0][0]
        assert "✅" in response
        assert "Groceries" in response

    @pytest.mark.asyncio
    async def test_not_found(self, update_user1, mock_context):
        mock_context.args = ["NonExistent"]
        mock_context.bot_data["sheets"].delete_budget.return_value = False

        await delbudget_command(update_user1, mock_context)

        response = update_user1.message.reply_text.call_args[0][0]
        assert "❌" in response
        assert "No budget found" in response
