"""Tests for the Google Sheets service layer.

Run unit tests (no credentials needed):
    pytest tests/test_sheets.py -v -k "not integration"

Run integration tests (needs .env with GOOGLE_SPREADSHEET_ID):
    pytest tests/test_sheets.py -v -m integration

Run everything:
    pytest tests/test_sheets.py -v
"""

import os
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from services.exceptions import (
    DuplicateTransactionError,
    InvalidDataError,
    SheetsConnectionError,
)
from services.sheets import (
    DEFAULT_CATEGORIES,
    BILL_HEADERS,
    BUDGET_HEADERS,
    CATEGORY_HEADERS,
    TRANSACTION_HEADERS,
    GoogleSheetsService,
    _from_bool_str,
    _generate_id,
    _to_bool_str,
)


# =========================================================================
# UNIT TESTS — no credentials needed
# =========================================================================


class TestHelperFunctions:
    """Test utility/conversion functions."""

    def test_generate_id_is_8_chars(self):
        id1 = _generate_id()
        assert len(id1) == 8
        assert id1.isalnum()

    def test_generate_id_is_unique(self):
        ids = {_generate_id() for _ in range(100)}
        assert len(ids) == 100  # all unique

    def test_to_bool_str_true(self):
        assert _to_bool_str(True) == "TRUE"

    def test_to_bool_str_false(self):
        assert _to_bool_str(False) == "FALSE"

    def test_from_bool_str_true_variants(self):
        assert _from_bool_str("TRUE") is True
        assert _from_bool_str("true") is True
        assert _from_bool_str("1") is True
        assert _from_bool_str("YES") is True

    def test_from_bool_str_false_variants(self):
        assert _from_bool_str("FALSE") is False
        assert _from_bool_str("false") is False
        assert _from_bool_str("0") is False
        assert _from_bool_str("no") is False
        assert _from_bool_str("") is False


class TestConstants:
    """Test that constants are well-formed."""

    def test_transaction_headers_count(self):
        assert len(TRANSACTION_HEADERS) == 10

    def test_bill_headers_count(self):
        assert len(BILL_HEADERS) == 9

    def test_budget_headers_count(self):
        assert len(BUDGET_HEADERS) == 3

    def test_category_headers_count(self):
        assert len(CATEGORY_HEADERS) == 3

    def test_default_categories_count(self):
        assert len(DEFAULT_CATEGORIES) == 14

    def test_default_categories_have_required_fields(self):
        for cat in DEFAULT_CATEGORIES:
            assert "name" in cat
            assert "keywords" in cat
            assert "icon" in cat
            assert len(cat["name"]) > 0
            assert len(cat["keywords"]) > 0
            assert len(cat["icon"]) > 0


class TestConnectionErrors:
    """Test error handling during connection."""

    def test_missing_credentials_file(self):
        with pytest.raises(SheetsConnectionError, match="not found"):
            GoogleSheetsService(
                credentials_file="/nonexistent/path.json",
                spreadsheet_id="fake_id",
            )

    def test_invalid_spreadsheet_id(self):
        """Connecting with bad spreadsheet ID should raise error."""
        with patch("services.sheets.Credentials") as mock_creds, \
             patch("services.sheets.gspread") as mock_gspread:
            mock_creds.from_service_account_file.return_value = MagicMock()
            mock_client = MagicMock()
            mock_gspread.authorize.return_value = mock_client
            mock_client.open_by_key.side_effect = Exception("Spreadsheet not found")

            with pytest.raises(SheetsConnectionError, match="Failed to connect"):
                GoogleSheetsService(
                    credentials_file="fake.json",
                    spreadsheet_id="bad_id",
                )


class TestTransactionValidation:
    """Test transaction input validation (using mock service)."""

    def test_add_transaction_negative_amount(self, mock_sheets_service):
        # Set up mock to avoid actual sheet operations
        mock_sheet = MagicMock()
        mock_sheet.get_all_records.return_value = []
        mock_sheets_service._sheets["Transactions"] = mock_sheet

        with pytest.raises(InvalidDataError, match="positive"):
            mock_sheets_service.add_transaction(
                amount=-10, category="Test", description="Test", user="user1"
            )

    def test_add_transaction_zero_amount(self, mock_sheets_service):
        mock_sheet = MagicMock()
        mock_sheet.get_all_records.return_value = []
        mock_sheets_service._sheets["Transactions"] = mock_sheet

        with pytest.raises(InvalidDataError, match="positive"):
            mock_sheets_service.add_transaction(
                amount=0, category="Test", description="Test", user="user1"
            )


class TestBillValidation:
    """Test bill input validation (using mock service)."""

    def test_add_bill_invalid_due_day_zero(self, mock_sheets_service):
        mock_sheet = MagicMock()
        mock_sheets_service._sheets["Bills"] = mock_sheet

        with pytest.raises(InvalidDataError, match="due_day"):
            mock_sheets_service.add_bill(
                name="Test", amount=10, due_day=0,
                frequency="monthly", category="Test", user="user1",
            )

    def test_add_bill_invalid_due_day_32(self, mock_sheets_service):
        mock_sheet = MagicMock()
        mock_sheets_service._sheets["Bills"] = mock_sheet

        with pytest.raises(InvalidDataError, match="due_day"):
            mock_sheets_service.add_bill(
                name="Test", amount=10, due_day=32,
                frequency="monthly", category="Test", user="user1",
            )

    def test_add_bill_invalid_frequency(self, mock_sheets_service):
        mock_sheet = MagicMock()
        mock_sheets_service._sheets["Bills"] = mock_sheet

        with pytest.raises(InvalidDataError, match="frequency"):
            mock_sheets_service.add_bill(
                name="Test", amount=10, due_day=15,
                frequency="weekly", category="Test", user="user1",
            )

    def test_add_bill_negative_amount(self, mock_sheets_service):
        mock_sheet = MagicMock()
        mock_sheets_service._sheets["Bills"] = mock_sheet

        with pytest.raises(InvalidDataError, match="positive"):
            mock_sheets_service.add_bill(
                name="Test", amount=-5, due_day=15,
                frequency="monthly", category="Test", user="user1",
            )


class TestBudgetValidation:
    """Test budget input validation."""

    def test_set_budget_negative_limit(self, mock_sheets_service):
        mock_sheet = MagicMock()
        mock_sheet.get_all_records.return_value = []
        mock_sheets_service._sheets["Budgets"] = mock_sheet

        with pytest.raises(InvalidDataError, match="positive"):
            mock_sheets_service.set_budget(
                category="Groceries", monthly_limit=-100, user="user1"
            )


class TestDataFrameStructure:
    """Test that DataFrames returned have correct structure."""

    def test_get_transactions_empty_returns_correct_columns(self, mock_sheets_service):
        mock_sheet = MagicMock()
        mock_sheet.get_all_records.return_value = []
        mock_sheets_service._sheets["Transactions"] = mock_sheet

        df = mock_sheets_service.get_transactions()
        assert list(df.columns) == TRANSACTION_HEADERS
        assert len(df) == 0

    def test_get_bills_empty_returns_correct_columns(self, mock_sheets_service):
        mock_sheet = MagicMock()
        mock_sheet.get_all_records.return_value = []
        mock_sheets_service._sheets["Bills"] = mock_sheet

        df = mock_sheets_service.get_bills()
        assert list(df.columns) == BILL_HEADERS
        assert len(df) == 0

    def test_get_budgets_empty_returns_correct_columns(self, mock_sheets_service):
        mock_sheet = MagicMock()
        mock_sheet.get_all_records.return_value = []
        mock_sheets_service._sheets["Budgets"] = mock_sheet

        df = mock_sheets_service.get_budgets()
        assert list(df.columns) == BUDGET_HEADERS
        assert len(df) == 0

    def test_get_categories_empty_returns_correct_columns(self, mock_sheets_service):
        mock_sheet = MagicMock()
        mock_sheet.get_all_records.return_value = []
        mock_sheets_service._sheets["Categories"] = mock_sheet

        df = mock_sheets_service.get_categories()
        assert list(df.columns) == CATEGORY_HEADERS
        assert len(df) == 0

    def test_get_transactions_with_data(self, mock_sheets_service):
        mock_sheet = MagicMock()
        mock_sheet.get_all_records.return_value = [
            {
                "id": "abc12345",
                "date": "2025-02-07",
                "amount": 45.67,
                "category": "Groceries",
                "description": "Whole Foods",
                "user": "user1",
                "source": "manual",
                "card": "Chase",
                "is_shared": "FALSE",
                "created_at": "2025-02-07T10:00:00",
            }
        ]
        mock_sheets_service._sheets["Transactions"] = mock_sheet

        df = mock_sheets_service.get_transactions()
        assert len(df) == 1
        assert df.iloc[0]["amount"] == 45.67
        assert df.iloc[0]["category"] == "Groceries"
        assert df.iloc[0]["is_shared"] == False  # noqa: E712 — numpy bool

    def test_get_transactions_filters_by_user(self, mock_sheets_service):
        mock_sheet = MagicMock()
        mock_sheet.get_all_records.return_value = [
            {"id": "a", "date": "2025-02-07", "amount": 10, "category": "Dining",
             "description": "Lunch", "user": "user1", "source": "manual",
             "card": "", "is_shared": "FALSE", "created_at": ""},
            {"id": "b", "date": "2025-02-07", "amount": 20, "category": "Dining",
             "description": "Dinner", "user": "user2", "source": "manual",
             "card": "", "is_shared": "FALSE", "created_at": ""},
        ]
        mock_sheets_service._sheets["Transactions"] = mock_sheet

        df = mock_sheets_service.get_transactions(user="user1")
        assert len(df) == 1
        assert df.iloc[0]["description"] == "Lunch"

    def test_get_transactions_filters_by_date_range(self, mock_sheets_service):
        mock_sheet = MagicMock()
        mock_sheet.get_all_records.return_value = [
            {"id": "a", "date": "2025-01-15", "amount": 10, "category": "Dining",
             "description": "Old", "user": "user1", "source": "manual",
             "card": "", "is_shared": "FALSE", "created_at": ""},
            {"id": "b", "date": "2025-02-07", "amount": 20, "category": "Dining",
             "description": "Recent", "user": "user1", "source": "manual",
             "card": "", "is_shared": "FALSE", "created_at": ""},
        ]
        mock_sheets_service._sheets["Transactions"] = mock_sheet

        df = mock_sheets_service.get_transactions(
            start_date=date(2025, 2, 1), end_date=date(2025, 2, 28)
        )
        assert len(df) == 1
        assert df.iloc[0]["description"] == "Recent"


# =========================================================================
# INTEGRATION TESTS — require real Google Sheets credentials
# =========================================================================


@pytest.mark.integration
class TestSheetsIntegration:
    """Integration tests that run against a real Google Spreadsheet.

    These tests use the integration_service fixture from conftest.py,
    which auto-skips if credentials are not available.
    """

    def test_connection_and_initialization(self, integration_service):
        """Test that we can connect and sheets are created."""
        # initialize() was already called by the fixture
        assert integration_service._initialized is True

    def test_categories_populated(self, integration_service):
        """Test that default categories were created."""
        df = integration_service.get_categories()
        assert len(df) >= 14  # At least the default categories
        assert "Groceries" in df["name"].values
        assert "Other" in df["name"].values

    def test_transaction_lifecycle(self, integration_service, sample_transaction_data):
        """Test add → read → update → delete for transactions."""
        # ADD
        t_id = integration_service.add_transaction(**sample_transaction_data)
        assert len(t_id) == 8

        # READ
        df = integration_service.get_transactions(user="user1")
        matching = df[df["id"] == t_id]
        assert len(matching) == 1
        assert matching.iloc[0]["amount"] == 45.67
        assert matching.iloc[0]["category"] == "Groceries"

        # UPDATE
        updated = integration_service.update_transaction(
            t_id, category="Shopping", amount=50.00
        )
        assert updated is True

        df = integration_service.get_transactions(user="user1")
        matching = df[df["id"] == t_id]
        assert matching.iloc[0]["category"] == "Shopping"

        # DELETE
        deleted = integration_service.delete_transaction(t_id)
        assert deleted is True

        df = integration_service.get_transactions(user="user1")
        assert t_id not in df["id"].values

    def test_duplicate_detection(self, integration_service):
        """Test that adding a duplicate transaction raises an error."""
        data = {
            "amount": 99.99,
            "category": "Test",
            "description": "Duplicate Test Item",
            "user": "user1",
            "transaction_date": date(2025, 1, 1),
        }

        # First add should succeed
        t_id = integration_service.add_transaction(**data)

        # Second add should raise DuplicateTransactionError
        with pytest.raises(DuplicateTransactionError):
            integration_service.add_transaction(**data)

        # Cleanup
        integration_service.delete_transaction(t_id)

    def test_bill_lifecycle(self, integration_service, sample_bill_data):
        """Test add → read → update → delete for bills."""
        # ADD
        bill_id = integration_service.add_bill(**sample_bill_data)
        assert len(bill_id) == 8

        # READ
        df = integration_service.get_bills(user="user1")
        matching = df[df["id"] == bill_id]
        assert len(matching) == 1
        assert matching.iloc[0]["name"] == "Netflix"
        assert matching.iloc[0]["amount"] == 15.99

        # UPDATE
        updated = integration_service.update_bill(bill_id, amount=17.99)
        assert updated is True

        # DELETE
        deleted = integration_service.delete_bill(bill_id)
        assert deleted is True

    def test_budget_lifecycle(self, integration_service, sample_budget_data):
        """Test set → read → update (upsert) → delete for budgets."""
        # SET
        result = integration_service.set_budget(**sample_budget_data)
        assert result is True

        # READ
        df = integration_service.get_budgets(user="user1", category="Groceries")
        assert len(df) == 1
        assert df.iloc[0]["monthly_limit"] == 600.00

        # UPSERT (update existing)
        integration_service.set_budget(
            category="Groceries", monthly_limit=700.00, user="user1"
        )
        df = integration_service.get_budgets(user="user1", category="Groceries")
        assert df.iloc[0]["monthly_limit"] == 700.00

        # DELETE
        deleted = integration_service.delete_budget(
            category="Groceries", user="user1"
        )
        assert deleted is True

    def test_get_transactions_date_range(self, integration_service):
        """Test filtering transactions by date range."""
        today = date.today()
        yesterday = today - timedelta(days=1)

        # Add two transactions on different dates
        id1 = integration_service.add_transaction(
            amount=10, category="Test", description="Yesterday Item",
            user="user1", transaction_date=yesterday,
        )
        id2 = integration_service.add_transaction(
            amount=20, category="Test", description="Today Item",
            user="user1", transaction_date=today,
        )

        # Filter for today only
        df = integration_service.get_transactions(
            start_date=today, end_date=today
        )
        assert any(df["id"] == id2)

        # Cleanup
        integration_service.delete_transaction(id1)
        integration_service.delete_transaction(id2)


# ---------------------------------------------------------------------------
# pytest configuration for markers
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: marks tests that need real Google Sheets credentials"
    )
