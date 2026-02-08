"""Tests for the bill tracker service.

Run:
    pytest tests/test_bill_tracker.py -v
"""

from datetime import date, timedelta
from unittest.mock import MagicMock

import pandas as pd
import pytest

from services.bill_tracker import (
    format_bills_list,
    format_upcoming_reminder,
    get_next_due_date,
    get_upcoming_bills,
)


# =========================================================================
# get_next_due_date
# =========================================================================


class TestGetNextDueDate:

    def test_due_day_in_future_this_month(self):
        # Feb 8, due day 15 → Feb 15
        result = get_next_due_date(15, reference_date=date(2025, 2, 8))
        assert result == date(2025, 2, 15)

    def test_due_day_already_passed_goes_next_month(self):
        # Feb 8, due day 5 → Mar 5
        result = get_next_due_date(5, reference_date=date(2025, 2, 8))
        assert result == date(2025, 3, 5)

    def test_due_day_is_today(self):
        # Feb 8, due day 8 → Feb 8 (today counts)
        result = get_next_due_date(8, reference_date=date(2025, 2, 8))
        assert result == date(2025, 2, 8)

    def test_day_31_in_short_month(self):
        # Feb 8, due day 31 → Feb 28 (clamped)
        result = get_next_due_date(31, reference_date=date(2025, 2, 8))
        assert result == date(2025, 2, 28)

    def test_day_31_already_passed_next_month(self):
        # Jan 31, due day 15 → Feb 15
        result = get_next_due_date(15, reference_date=date(2025, 1, 31))
        assert result == date(2025, 2, 15)

    def test_december_rolls_to_january(self):
        # Dec 25, due day 10 → Jan 10 next year
        result = get_next_due_date(10, reference_date=date(2025, 12, 25))
        assert result == date(2026, 1, 10)


# =========================================================================
# get_upcoming_bills
# =========================================================================


class TestGetUpcomingBills:

    def _mock_sheets_with_bills(self, bills_data):
        mock_sheets = MagicMock()
        df = pd.DataFrame(bills_data)
        mock_sheets.get_bills.return_value = df
        return mock_sheets

    def test_returns_bills_within_range(self):
        sheets = self._mock_sheets_with_bills(
            [
                {"name": "Netflix", "amount": 15.99, "due_day": 15,
                 "category": "Entertainment", "auto_pay": True, "frequency": "monthly", "active": True},
                {"name": "Rent", "amount": 2000, "due_day": 1,
                 "category": "Housing", "auto_pay": False, "frequency": "monthly", "active": True},
            ]
        )
        # Feb 10: Netflix due Feb 15 (5 days), Rent due Mar 1 (19 days)
        result = get_upcoming_bills(sheets, days_ahead=7, reference_date=date(2025, 2, 10))
        assert len(result) == 1
        assert result[0]["name"] == "Netflix"
        assert result[0]["days_until"] == 5

    def test_empty_when_no_bills(self):
        sheets = self._mock_sheets_with_bills([])
        sheets.get_bills.return_value = pd.DataFrame(
            columns=["id", "name", "amount", "due_day", "frequency", "category", "user", "auto_pay", "active"]
        )
        result = get_upcoming_bills(sheets, days_ahead=7, reference_date=date(2025, 2, 10))
        assert result == []

    def test_sorted_by_soonest_first(self):
        sheets = self._mock_sheets_with_bills(
            [
                {"name": "Electric", "amount": 120, "due_day": 20,
                 "category": "Utilities", "auto_pay": False, "frequency": "monthly", "active": True},
                {"name": "Netflix", "amount": 15.99, "due_day": 15,
                 "category": "Entertainment", "auto_pay": True, "frequency": "monthly", "active": True},
            ]
        )
        # Feb 10: Netflix (5 days), Electric (10 days) — both within 14 days
        result = get_upcoming_bills(sheets, days_ahead=14, reference_date=date(2025, 2, 10))
        assert len(result) == 2
        assert result[0]["name"] == "Netflix"
        assert result[1]["name"] == "Electric"


# =========================================================================
# format_bills_list
# =========================================================================


class TestFormatBillsList:

    def test_formats_bills(self):
        df = pd.DataFrame(
            [
                {"name": "Rent", "amount": 2000, "due_day": 1,
                 "frequency": "monthly", "auto_pay": False},
                {"name": "Netflix", "amount": 15.99, "due_day": 15,
                 "frequency": "monthly", "auto_pay": True},
            ]
        )
        result = format_bills_list(df)
        assert "Rent" in result
        assert "$2,000.00" in result
        assert "Netflix" in result
        assert "auto-pay" in result
        assert "Total monthly" in result

    def test_empty_bills(self):
        df = pd.DataFrame()
        result = format_bills_list(df)
        assert "No bills set up yet" in result

    def test_custom_currency(self):
        df = pd.DataFrame(
            [{"name": "Test", "amount": 10, "due_day": 1,
              "frequency": "monthly", "auto_pay": False}]
        )
        result = format_bills_list(df, currency="€")
        assert "€10.00" in result


# =========================================================================
# format_upcoming_reminder
# =========================================================================


class TestFormatUpcomingReminder:

    def test_formats_upcoming(self):
        bills = [
            {"name": "Netflix", "amount": 15.99, "due_date": date(2025, 2, 15),
             "days_until": 5, "auto_pay": True},
            {"name": "Electric", "amount": 120, "due_date": date(2025, 2, 20),
             "days_until": 10, "auto_pay": False},
        ]
        result = format_upcoming_reminder(bills)
        assert "Netflix" in result
        assert "in 5 days" in result
        assert "auto-pay" in result
        assert "Electric" in result

    def test_today_marker(self):
        bills = [
            {"name": "Rent", "amount": 2000, "due_date": date(2025, 2, 1),
             "days_until": 0, "auto_pay": False},
        ]
        result = format_upcoming_reminder(bills)
        assert "TODAY" in result

    def test_tomorrow(self):
        bills = [
            {"name": "Test", "amount": 10, "due_date": date(2025, 2, 2),
             "days_until": 1, "auto_pay": False},
        ]
        result = format_upcoming_reminder(bills)
        assert "tomorrow" in result

    def test_no_upcoming(self):
        result = format_upcoming_reminder([])
        assert "No bills due" in result
