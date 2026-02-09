"""Tests for scheduled auto-summary tasks.

Run:
    pytest tests/test_scheduled_tasks.py -v
"""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from bot.scheduled_tasks import (
    _build_user_list,
    send_daily_summary,
    send_monthly_summary,
    send_weekly_summary,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_settings():
    """Mock settings with both users active."""
    s = MagicMock()
    s.telegram_user1_id = 7992938764
    s.telegram_user2_id = 111111111
    s.telegram_user1_name = "Seemran"
    s.telegram_user2_name = "Amit"
    s.currency_symbol = "$"
    s.auto_summaries_enabled = True
    return s


@pytest.fixture
def mock_settings_single_user():
    """Mock settings with user2 as placeholder."""
    s = MagicMock()
    s.telegram_user1_id = 7992938764
    s.telegram_user2_id = 0
    s.currency_symbol = "$"
    s.auto_summaries_enabled = True
    return s


@pytest.fixture
def mock_context(mock_settings):
    """Mock context with bot_data and async bot.send_message."""
    ctx = MagicMock()
    ctx.bot_data = {
        "settings": mock_settings,
        "sheets": MagicMock(),
    }
    ctx.bot = AsyncMock()
    ctx.bot.send_message = AsyncMock()
    return ctx


def _sample_transactions():
    return pd.DataFrame([
        {"amount": 25.50, "category": "Groceries", "description": "Whole Foods"},
        {"amount": 15.00, "category": "Dining", "description": "Chipotle"},
    ])


# =========================================================================
# _build_user_list
# =========================================================================


class TestBuildUserList:

    def test_both_users_active(self, mock_settings):
        users = _build_user_list(mock_settings)
        assert len(users) == 2
        assert users[0] == (7992938764, "user1")
        assert users[1] == (111111111, "user2")

    def test_placeholder_user2_skipped(self, mock_settings_single_user):
        users = _build_user_list(mock_settings_single_user)
        assert len(users) == 1
        assert users[0] == (7992938764, "user1")


# =========================================================================
# send_daily_summary
# =========================================================================


class TestSendDailySummary:

    @pytest.mark.asyncio
    async def test_sends_with_transactions_and_bills(self, mock_context):
        sheets = mock_context.bot_data["sheets"]
        sheets.get_transactions.return_value = _sample_transactions()

        # Mock upcoming bills
        with patch(
            "bot.scheduled_tasks.get_upcoming_bills",
            return_value=[{"name": "Netflix", "amount": 15.99, "days_until": 1}],
        ), patch(
            "bot.scheduled_tasks.format_upcoming_reminder",
            return_value="🔔 Netflix — $15.99 (tomorrow)",
        ):
            await send_daily_summary(mock_context)

        # Should send to both users
        assert mock_context.bot.send_message.call_count == 2
        message = mock_context.bot.send_message.call_args_list[0][1]["text"]
        assert "Daily Summary" in message
        assert "$40.50" in message
        assert "Netflix" in message

    @pytest.mark.asyncio
    async def test_skips_when_no_data(self, mock_context):
        sheets = mock_context.bot_data["sheets"]
        sheets.get_transactions.return_value = pd.DataFrame()

        with patch(
            "bot.scheduled_tasks.get_upcoming_bills", return_value=[]
        ), patch(
            "bot.scheduled_tasks.format_upcoming_reminder", return_value=""
        ):
            await send_daily_summary(mock_context)

        mock_context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_error_gracefully(self, mock_context):
        sheets = mock_context.bot_data["sheets"]
        sheets.get_transactions.side_effect = Exception("Connection error")

        with patch("bot.scheduled_tasks.get_upcoming_bills", return_value=[]):
            await send_daily_summary(mock_context)

        # Should not crash, and no message sent
        mock_context.bot.send_message.assert_not_called()


# =========================================================================
# send_weekly_summary
# =========================================================================


class TestSendWeeklySummary:

    @pytest.mark.asyncio
    async def test_sends_with_data_and_alerts(self, mock_context):
        sheets = mock_context.bot_data["sheets"]
        sheets.get_transactions.return_value = _sample_transactions()

        with patch(
            "bot.scheduled_tasks.get_budget_status",
            return_value=[{"category": "Dining", "percent_used": 90}],
        ), patch(
            "bot.scheduled_tasks.get_budget_alerts",
            return_value=["⚠️ Dining: 90% of $200 budget used"],
        ), patch(
            "bot.scheduled_tasks.get_upcoming_bills", return_value=[]
        ), patch(
            "bot.scheduled_tasks.format_upcoming_reminder", return_value=""
        ):
            await send_weekly_summary(mock_context)

        assert mock_context.bot.send_message.call_count == 2
        message = mock_context.bot.send_message.call_args_list[0][1]["text"]
        assert "Weekly Summary" in message
        assert "$40.50" in message
        assert "Budget Alerts" in message
        assert "Dining" in message

    @pytest.mark.asyncio
    async def test_skips_when_no_data(self, mock_context):
        sheets = mock_context.bot_data["sheets"]
        sheets.get_transactions.return_value = pd.DataFrame()

        with patch(
            "bot.scheduled_tasks.get_budget_status", return_value=[]
        ), patch(
            "bot.scheduled_tasks.get_budget_alerts", return_value=[]
        ), patch(
            "bot.scheduled_tasks.get_upcoming_bills", return_value=[]
        ), patch(
            "bot.scheduled_tasks.format_upcoming_reminder", return_value=""
        ):
            await send_weekly_summary(mock_context)

        mock_context.bot.send_message.assert_not_called()


# =========================================================================
# send_monthly_summary
# =========================================================================


class TestSendMonthlySummary:

    @pytest.mark.asyncio
    async def test_sends_last_month_summary(self, mock_context):
        sheets = mock_context.bot_data["sheets"]
        sheets.get_transactions.return_value = _sample_transactions()

        with patch(
            "bot.scheduled_tasks.get_budget_status",
            return_value=[{"category": "Groceries", "limit": 500, "spent": 300}],
        ), patch(
            "bot.scheduled_tasks.format_budget_status",
            return_value="🛒 Groceries: $300 / $500 (60%)",
        ):
            await send_monthly_summary(mock_context)

        assert mock_context.bot.send_message.call_count == 2
        message = mock_context.bot.send_message.call_args_list[0][1]["text"]
        assert "Monthly Summary" in message
        assert "$40.50" in message
        assert "Budget Recap" in message

    @pytest.mark.asyncio
    async def test_skips_when_no_data(self, mock_context):
        sheets = mock_context.bot_data["sheets"]
        sheets.get_transactions.return_value = pd.DataFrame()

        with patch(
            "bot.scheduled_tasks.get_budget_status", return_value=[]
        ), patch(
            "bot.scheduled_tasks.format_budget_status", return_value=""
        ):
            await send_monthly_summary(mock_context)

        mock_context.bot.send_message.assert_not_called()


# =========================================================================
# Auto summaries disabled
# =========================================================================


class TestAutoSummariesDisabled:

    @pytest.mark.asyncio
    async def test_daily_skips_when_disabled(self, mock_context):
        mock_context.bot_data["settings"].auto_summaries_enabled = False
        await send_daily_summary(mock_context)
        mock_context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_weekly_skips_when_disabled(self, mock_context):
        mock_context.bot_data["settings"].auto_summaries_enabled = False
        await send_weekly_summary(mock_context)
        mock_context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_monthly_skips_when_disabled(self, mock_context):
        mock_context.bot_data["settings"].auto_summaries_enabled = False
        await send_monthly_summary(mock_context)
        mock_context.bot.send_message.assert_not_called()
