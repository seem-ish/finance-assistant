"""Tests for dashboard helper functions.

Run:
    pytest tests/test_dashboard.py -v
"""

from datetime import date, timedelta

import pandas as pd
import pytest

from dashboard.app import build_category_summary, format_currency, get_date_range


# =========================================================================
# format_currency
# =========================================================================


class TestFormatCurrency:

    def test_basic(self):
        assert format_currency(25.50) == "$25.50"

    def test_custom_symbol(self):
        assert format_currency(100, "€") == "€100.00"

    def test_zero(self):
        assert format_currency(0) == "$0.00"

    def test_large_number_with_commas(self):
        assert format_currency(1234567.89) == "$1,234,567.89"

    def test_small_amount(self):
        assert format_currency(0.99) == "$0.99"


# =========================================================================
# get_date_range
# =========================================================================


class TestGetDateRange:

    def test_today(self):
        start, end = get_date_range("today")
        assert start == date.today()
        assert end == date.today()

    def test_this_week_starts_monday(self):
        start, end = get_date_range("this_week")
        today = date.today()
        expected_monday = today - timedelta(days=today.weekday())
        assert start == expected_monday
        assert end == today

    def test_this_month_starts_first(self):
        start, end = get_date_range("this_month")
        today = date.today()
        assert start == date(today.year, today.month, 1)
        assert end == today

    def test_last_30_days(self):
        start, end = get_date_range("last_30_days")
        today = date.today()
        assert start == today - timedelta(days=30)
        assert end == today

    def test_unknown_preset_defaults_to_this_month(self):
        start, end = get_date_range("unknown")
        today = date.today()
        assert start == date(today.year, today.month, 1)
        assert end == today


# =========================================================================
# build_category_summary
# =========================================================================


class TestBuildCategorySummary:

    def test_empty_dataframe(self):
        result = build_category_summary(pd.DataFrame())
        assert list(result.columns) == ["category", "total", "count"]
        assert len(result) == 0

    def test_single_category(self):
        df = pd.DataFrame(
            [
                {"amount": 25.50, "category": "Groceries"},
                {"amount": 30.00, "category": "Groceries"},
            ]
        )
        result = build_category_summary(df)
        assert len(result) == 1
        assert result.iloc[0]["category"] == "Groceries"
        assert result.iloc[0]["total"] == 55.50
        assert result.iloc[0]["count"] == 2

    def test_multiple_categories_sorted_by_total(self):
        df = pd.DataFrame(
            [
                {"amount": 10, "category": "Transport"},
                {"amount": 100, "category": "Shopping"},
                {"amount": 50, "category": "Dining"},
            ]
        )
        result = build_category_summary(df)
        assert len(result) == 3
        # Sorted highest first
        assert list(result["category"]) == ["Shopping", "Dining", "Transport"]

    def test_aggregates_correctly(self):
        df = pd.DataFrame(
            [
                {"amount": 20, "category": "Dining"},
                {"amount": 30, "category": "Dining"},
                {"amount": 15, "category": "Transport"},
            ]
        )
        result = build_category_summary(df)
        dining = result[result["category"] == "Dining"].iloc[0]
        assert dining["total"] == 50
        assert dining["count"] == 2
