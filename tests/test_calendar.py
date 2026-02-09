"""Tests for Google Calendar integration.

Run:
    pytest tests/test_calendar.py -v
"""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from services.calendar import (
    CalendarService,
    sync_bills_to_calendar,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_calendar_service():
    """Mock CalendarService with a fake Google Calendar API."""
    cal = CalendarService.__new__(CalendarService)
    cal._service = MagicMock()
    cal.calendar_id = "primary"
    cal.credentials_file = "fake.json"
    cal.token_file = "fake_token.json"
    return cal


# =========================================================================
# create_bill_event
# =========================================================================


class TestCreateBillEvent:

    def test_creates_event_returns_id(self, mock_calendar_service):
        mock_calendar_service._service.events().insert().execute.return_value = {
            "id": "evt123"
        }

        event_id = mock_calendar_service.create_bill_event(
            name="Netflix",
            amount=15.99,
            due_date=date(2025, 2, 15),
            category="Entertainment",
            auto_pay=True,
        )

        assert event_id == "evt123"
        mock_calendar_service._service.events().insert.assert_called()

    def test_returns_none_when_no_service(self):
        cal = CalendarService.__new__(CalendarService)
        cal._service = None
        assert cal.create_bill_event("Test", 10, date.today()) is None


# =========================================================================
# log_payment_event
# =========================================================================


class TestLogPaymentEvent:

    def test_creates_payment_event(self, mock_calendar_service):
        mock_calendar_service._service.events().insert().execute.return_value = {
            "id": "pay123"
        }

        event_id = mock_calendar_service.log_payment_event(
            name="Netflix",
            amount=15.99,
            payment_date=date(2025, 2, 15),
            category="Entertainment",
        )

        assert event_id == "pay123"


# =========================================================================
# sync_bills_to_calendar
# =========================================================================


class TestSyncBillsToCalendar:

    def test_creates_events_for_active_bills(self, mock_calendar_service):
        mock_sheets = MagicMock()
        mock_sheets.get_bills.return_value = pd.DataFrame([
            {
                "name": "Netflix",
                "amount": 15.99,
                "due_day": 15,
                "category": "Entertainment",
                "auto_pay": True,
                "frequency": "monthly",
            }
        ])

        # No existing events
        mock_calendar_service._service.events().list().execute.return_value = {
            "items": []
        }
        mock_calendar_service._service.events().insert().execute.return_value = {
            "id": "evt123"
        }

        results = sync_bills_to_calendar(mock_calendar_service, mock_sheets)
        assert results["created"] == 1
        assert results["existing"] == 0

    def test_skips_existing_events(self, mock_calendar_service):
        mock_sheets = MagicMock()
        today = date.today()
        # Bill due on day 15
        due_day = 15
        from services.bill_tracker import get_next_due_date
        due_date = get_next_due_date(due_day)

        mock_sheets.get_bills.return_value = pd.DataFrame([
            {
                "name": "Netflix",
                "amount": 15.99,
                "due_day": due_day,
                "category": "Entertainment",
                "auto_pay": True,
                "frequency": "monthly",
            }
        ])

        # Event already exists with matching summary and date
        mock_calendar_service._service.events().list().execute.return_value = {
            "items": [
                {
                    "summary": "💳 Netflix — $15.99 due",
                    "start": {"date": due_date.isoformat()},
                }
            ]
        }

        results = sync_bills_to_calendar(mock_calendar_service, mock_sheets)
        assert results["created"] == 0
        assert results["existing"] == 1

    def test_handles_no_bills(self, mock_calendar_service):
        mock_sheets = MagicMock()
        mock_sheets.get_bills.return_value = pd.DataFrame()

        results = sync_bills_to_calendar(mock_calendar_service, mock_sheets)
        assert results["created"] == 0
        assert results["existing"] == 0
        assert results["errors"] == 0
