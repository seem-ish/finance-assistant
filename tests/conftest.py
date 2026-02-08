"""Shared test fixtures for the finance assistant test suite."""

import os
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from dotenv import load_dotenv

# Load .env so integration tests can find GOOGLE_SPREADSHEET_ID etc.
load_dotenv()


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_transaction_data():
    """Sample transaction data for testing."""
    return {
        "amount": 45.67,
        "category": "Groceries",
        "description": "Whole Foods Market",
        "user": "user1",
        "transaction_date": date(2025, 2, 7),
        "source": "manual",
        "card": "Chase Sapphire",
        "is_shared": False,
    }


@pytest.fixture
def sample_bill_data():
    """Sample bill data for testing."""
    return {
        "name": "Netflix",
        "amount": 15.99,
        "due_day": 15,
        "frequency": "monthly",
        "category": "Subscriptions",
        "user": "user1",
        "auto_pay": True,
    }


@pytest.fixture
def sample_budget_data():
    """Sample budget data for testing."""
    return {
        "category": "Groceries",
        "monthly_limit": 600.00,
        "user": "user1",
    }


# ---------------------------------------------------------------------------
# Mock Google Sheets service fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_sheets_service():
    """Create a GoogleSheetsService with mocked gspread client.

    This lets you test logic without real Google API calls.
    """
    with patch("services.sheets.Credentials") as mock_creds, \
         patch("services.sheets.gspread") as mock_gspread:

        mock_creds.from_service_account_file.return_value = MagicMock()
        mock_client = MagicMock()
        mock_gspread.authorize.return_value = mock_client
        mock_spreadsheet = MagicMock()
        mock_spreadsheet.title = "Test Finance Assistant"
        mock_client.open_by_key.return_value = mock_spreadsheet

        from services.sheets import GoogleSheetsService
        service = GoogleSheetsService(
            credentials_file="fake_creds.json",
            spreadsheet_id="fake_spreadsheet_id",
        )

        # Attach mocks for inspection in tests
        service._mock_client = mock_client
        service._mock_spreadsheet = mock_spreadsheet

        yield service


# ---------------------------------------------------------------------------
# Integration test service fixture (uses real Google Sheets)
# ---------------------------------------------------------------------------

@pytest.fixture
def integration_service():
    """Create a real GoogleSheetsService for integration testing.

    Skips if credentials or spreadsheet ID are not available.
    """
    creds_file = os.environ.get(
        "GOOGLE_CREDENTIALS_FILE", "config/google_credentials.json"
    )
    spreadsheet_id = os.environ.get("GOOGLE_SPREADSHEET_ID", "")

    if not spreadsheet_id or spreadsheet_id == "your_spreadsheet_id_here":
        pytest.skip("GOOGLE_SPREADSHEET_ID not set — skipping integration test")

    if not os.path.exists(creds_file):
        pytest.skip(f"Credentials file not found: {creds_file}")

    from services.sheets import GoogleSheetsService
    service = GoogleSheetsService(
        credentials_file=creds_file,
        spreadsheet_id=spreadsheet_id,
    )
    service.initialize()
    return service
