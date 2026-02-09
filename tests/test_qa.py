"""Tests for the Q&A service (services/qa.py).

All tests mock the OpenAI API — no real API calls are made.
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from services.qa import _build_financial_context, answer_question


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_sheets():
    """Create a mock GoogleSheetsService with sample data."""
    sheets = MagicMock()

    # Sample transactions
    txn_data = pd.DataFrame(
        {
            "date": [date(2025, 2, 1), date(2025, 2, 3), date(2025, 2, 5)],
            "amount": [45.00, 12.50, 80.00],
            "category": ["Groceries", "Coffee", "Groceries"],
            "description": ["Whole Foods", "Starbucks", "Trader Joe's"],
            "user": ["user1", "user1", "user1"],
        }
    )
    sheets.get_transactions.return_value = txn_data

    # Sample budgets
    budgets_df = pd.DataFrame(
        {
            "category": ["Groceries", "Coffee"],
            "monthly_limit": [500.0, 50.0],
            "user": ["user1", "user1"],
        }
    )
    sheets.get_budgets.return_value = budgets_df

    # Sample bills
    bills_df = pd.DataFrame(
        {
            "id": ["b1"],
            "name": ["Netflix"],
            "amount": [15.99],
            "due_day": [15],
            "frequency": ["monthly"],
            "category": ["Entertainment"],
            "user": ["user1"],
            "auto_pay": [False],
            "active": [True],
        }
    )
    sheets.get_bills.return_value = bills_df

    return sheets


@pytest.fixture
def mock_sheets_empty():
    """Create a mock GoogleSheetsService with no data."""
    sheets = MagicMock()
    sheets.get_transactions.return_value = pd.DataFrame()
    sheets.get_budgets.return_value = pd.DataFrame()
    sheets.get_bills.return_value = pd.DataFrame()
    return sheets


@pytest.fixture
def settings_enabled():
    """Settings with Q&A enabled."""
    settings = MagicMock()
    settings.qa_enabled = True
    settings.openai_api_key = "sk-test-key-123"
    settings.qa_model = "gpt-4o-mini"
    settings.currency_symbol = "$"
    return settings


@pytest.fixture
def settings_disabled():
    """Settings with Q&A disabled."""
    settings = MagicMock()
    settings.qa_enabled = False
    settings.openai_api_key = ""
    settings.qa_model = "gpt-4o-mini"
    settings.currency_symbol = "$"
    return settings


# ---------------------------------------------------------------------------
# TestBuildFinancialContext
# ---------------------------------------------------------------------------


class TestBuildFinancialContext:
    """Tests for _build_financial_context helper."""

    def test_with_data(self, mock_sheets):
        """Context includes transactions, budgets, and bills."""
        context = _build_financial_context(mock_sheets, "user1", currency="$")

        # Should contain transaction info
        assert "CURRENT MONTH TRANSACTIONS" in context
        assert "Groceries" in context
        assert "Coffee" in context

        # Should contain budget status
        assert "BUDGET STATUS" in context

        # Should contain bills
        assert "ACTIVE BILLS" in context
        assert "Netflix" in context
        assert "15.99" in context

    def test_with_empty_data(self, mock_sheets_empty):
        """Context handles no data gracefully."""
        context = _build_financial_context(mock_sheets_empty, "user1", currency="$")

        assert "No transactions yet" in context
        assert "No budgets configured" in context
        assert "None" in context  # No bills


# ---------------------------------------------------------------------------
# TestAnswerQuestion
# ---------------------------------------------------------------------------


class TestAnswerQuestion:
    """Tests for the answer_question function."""

    @patch("services.qa.OpenAI")
    def test_successful_answer(self, mock_openai_cls, mock_sheets, settings_enabled):
        """Returns the LLM's response on success."""
        # Set up mock OpenAI client
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            "You spent $125.00 on groceries this month."
        )
        mock_client.chat.completions.create.return_value = mock_response

        result = answer_question(
            "How much did I spend on groceries?",
            mock_sheets,
            "user1",
            settings_enabled,
        )

        assert "125.00" in result
        assert "groceries" in result.lower()

        # Verify OpenAI was called with correct model
        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "gpt-4o-mini"
        assert call_kwargs["max_tokens"] == 500
        assert call_kwargs["temperature"] == 0.3

    def test_qa_disabled(self, mock_sheets, settings_disabled):
        """Returns a message when Q&A is disabled."""
        result = answer_question(
            "How much did I spend?", mock_sheets, "user1", settings_disabled
        )
        assert "not enabled" in result.lower()

    def test_no_api_key(self, mock_sheets, settings_enabled):
        """Returns a message when API key is empty."""
        settings_enabled.openai_api_key = ""
        result = answer_question(
            "How much did I spend?", mock_sheets, "user1", settings_enabled
        )
        assert "API key" in result

    @patch("services.qa.OpenAI")
    def test_openai_error(self, mock_openai_cls, mock_sheets, settings_enabled):
        """Returns a friendly error when OpenAI fails."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception("API timeout")

        result = answer_question(
            "How much did I spend?", mock_sheets, "user1", settings_enabled
        )
        assert "couldn't process" in result.lower() or "try again" in result.lower()
