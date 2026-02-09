"""Tests for the budget tracker service.

Run:
    pytest tests/test_budget_tracker.py -v
"""

from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest

from services.budget_tracker import (
    _progress_bar,
    format_budget_status,
    get_budget_alerts,
    get_budget_status,
)


# =========================================================================
# _progress_bar
# =========================================================================


class TestProgressBar:

    def test_zero_percent(self):
        result = _progress_bar(0)
        assert result == "[" + "░" * 20 + "]"

    def test_fifty_percent(self):
        result = _progress_bar(50)
        assert "█" * 10 in result
        assert "░" * 10 in result

    def test_hundred_percent(self):
        result = _progress_bar(100)
        assert result == "[" + "█" * 20 + "]"

    def test_over_hundred_caps_at_full(self):
        result = _progress_bar(150)
        assert result == "[" + "█" * 20 + "]"


# =========================================================================
# get_budget_status
# =========================================================================


class TestGetBudgetStatus:

    def _mock_sheets(self, budgets, transactions):
        sheets = MagicMock()
        sheets.get_budgets.return_value = pd.DataFrame(budgets) if budgets else pd.DataFrame(columns=["category", "monthly_limit", "user"])
        sheets.get_transactions.return_value = pd.DataFrame(transactions) if transactions else pd.DataFrame(columns=["amount", "category"])
        return sheets

    def test_normal_spending(self):
        sheets = self._mock_sheets(
            budgets=[{"category": "Groceries", "monthly_limit": 500, "user": "user1"}],
            transactions=[
                {"amount": 150, "category": "Groceries"},
                {"amount": 50, "category": "Groceries"},
            ],
        )
        result = get_budget_status(sheets, "user1", reference_date=date(2025, 2, 15))
        assert len(result) == 1
        assert result[0]["category"] == "Groceries"
        assert result[0]["spent"] == 200
        assert result[0]["limit"] == 500
        assert result[0]["remaining"] == 300
        assert result[0]["percent_used"] == 40.0

    def test_over_budget(self):
        sheets = self._mock_sheets(
            budgets=[{"category": "Dining", "monthly_limit": 100, "user": "user1"}],
            transactions=[{"amount": 150, "category": "Dining"}],
        )
        result = get_budget_status(sheets, "user1", reference_date=date(2025, 2, 15))
        assert result[0]["percent_used"] == 150.0
        assert result[0]["remaining"] == -50

    def test_no_spending(self):
        sheets = self._mock_sheets(
            budgets=[{"category": "Shopping", "monthly_limit": 300, "user": "user1"}],
            transactions=[],
        )
        result = get_budget_status(sheets, "user1", reference_date=date(2025, 2, 15))
        assert result[0]["spent"] == 0
        assert result[0]["percent_used"] == 0.0

    def test_no_budgets(self):
        sheets = self._mock_sheets(budgets=[], transactions=[])
        result = get_budget_status(sheets, "user1")
        assert result == []

    def test_sorted_by_percent_descending(self):
        sheets = self._mock_sheets(
            budgets=[
                {"category": "Groceries", "monthly_limit": 500, "user": "user1"},
                {"category": "Dining", "monthly_limit": 100, "user": "user1"},
            ],
            transactions=[
                {"amount": 100, "category": "Groceries"},
                {"amount": 90, "category": "Dining"},
            ],
        )
        result = get_budget_status(sheets, "user1", reference_date=date(2025, 2, 15))
        assert result[0]["category"] == "Dining"  # 90% > 20%
        assert result[1]["category"] == "Groceries"


# =========================================================================
# format_budget_status
# =========================================================================


class TestFormatBudgetStatus:

    def test_formats_statuses(self):
        statuses = [
            {"category": "Groceries", "limit": 500, "spent": 350,
             "remaining": 150, "percent_used": 70.0},
        ]
        result = format_budget_status(statuses)
        assert "Groceries" in result
        assert "$350.00" in result
        assert "$500.00" in result
        assert "70%" in result
        assert "█" in result

    def test_shows_alerts(self):
        statuses = [
            {"category": "Dining", "limit": 100, "spent": 150,
             "remaining": -50, "percent_used": 150.0},
        ]
        result = format_budget_status(statuses)
        assert "🔴" in result
        assert "OVER" in result

    def test_warning_at_80(self):
        statuses = [
            {"category": "Dining", "limit": 200, "spent": 180,
             "remaining": 20, "percent_used": 90.0},
        ]
        result = format_budget_status(statuses)
        assert "⚠️" in result

    def test_empty_statuses(self):
        result = format_budget_status([])
        assert "No budgets set up" in result

    def test_shows_total(self):
        statuses = [
            {"category": "Groceries", "limit": 500, "spent": 200,
             "remaining": 300, "percent_used": 40.0},
            {"category": "Dining", "limit": 200, "spent": 100,
             "remaining": 100, "percent_used": 50.0},
        ]
        result = format_budget_status(statuses)
        assert "Total" in result
        assert "$300.00" in result  # total spent
        assert "$700.00" in result  # total limit


# =========================================================================
# get_budget_alerts
# =========================================================================


class TestGetBudgetAlerts:

    def test_over_budget_alert(self):
        statuses = [
            {"category": "Dining", "limit": 100, "spent": 150,
             "remaining": -50, "percent_used": 150.0},
        ]
        alerts = get_budget_alerts(statuses)
        assert len(alerts) == 1
        assert "🔴" in alerts[0]
        assert "OVER" in alerts[0]

    def test_warning_at_80(self):
        statuses = [
            {"category": "Groceries", "limit": 500, "spent": 420,
             "remaining": 80, "percent_used": 84.0},
        ]
        alerts = get_budget_alerts(statuses)
        assert len(alerts) == 1
        assert "⚠️" in alerts[0]
        assert "84%" in alerts[0]

    def test_no_alerts_under_80(self):
        statuses = [
            {"category": "Groceries", "limit": 500, "spent": 200,
             "remaining": 300, "percent_used": 40.0},
        ]
        alerts = get_budget_alerts(statuses)
        assert alerts == []
