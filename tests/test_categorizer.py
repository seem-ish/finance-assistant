"""Tests for the transaction categorizer.

Run:
    pytest tests/test_categorizer.py -v
"""

from unittest.mock import MagicMock

import pandas as pd
import pytest

from services.categorizer import Categorizer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_sheets():
    """Mock GoogleSheetsService with default categories."""
    sheets = MagicMock()
    sheets.get_categories.return_value = pd.DataFrame(
        [
            {"name": "Groceries", "keywords": "supermarket,grocery,whole foods,trader joe", "icon": "🛒"},
            {"name": "Dining", "keywords": "restaurant,doordash,uber eats,chipotle,starbucks", "icon": "🍽️"},
            {"name": "Transport", "keywords": "gas,uber,lyft,parking,toll", "icon": "🚗"},
            {"name": "Shopping", "keywords": "amazon,target,walmart,costco", "icon": "🛍️"},
            {"name": "Entertainment", "keywords": "netflix,spotify,movies,hulu,disney", "icon": "🎬"},
            {"name": "Health", "keywords": "pharmacy,doctor,gym,hospital,dental", "icon": "🏥"},
            {"name": "Utilities", "keywords": "electric,water,internet,phone,gas bill", "icon": "💡"},
            {"name": "Housing", "keywords": "rent,mortgage,maintenance,hoa", "icon": "🏠"},
            {"name": "Subscriptions", "keywords": "software,apps,memberships,cloud", "icon": "📱"},
            {"name": "Travel", "keywords": "hotel,airline,airbnb,flight,booking", "icon": "✈️"},
            {"name": "Education", "keywords": "courses,books,tuition,udemy", "icon": "📚"},
            {"name": "Personal", "keywords": "salon,clothing,gifts,haircut", "icon": "💅"},
            {"name": "Insurance", "keywords": "auto insurance,health insurance,life insurance", "icon": "🛡️"},
            {"name": "Other", "keywords": "uncategorized", "icon": "📦"},
        ]
    )
    return sheets


@pytest.fixture
def categorizer(mock_sheets):
    return Categorizer(mock_sheets)


# =========================================================================
# Keyword matching
# =========================================================================


class TestCategorize:

    def test_exact_keyword_match(self, categorizer):
        assert categorizer.categorize("Whole Foods organic milk") == "Groceries"

    def test_case_insensitive(self, categorizer):
        assert categorizer.categorize("CHIPOTLE burrito") == "Dining"

    def test_partial_match(self, categorizer):
        assert categorizer.categorize("Uber ride to airport") == "Transport"

    def test_starbucks_is_dining(self, categorizer):
        assert categorizer.categorize("Starbucks coffee") == "Dining"

    def test_amazon_is_shopping(self, categorizer):
        assert categorizer.categorize("Amazon order #12345") == "Shopping"

    def test_netflix_is_entertainment(self, categorizer):
        assert categorizer.categorize("Netflix monthly subscription") == "Entertainment"

    def test_gym_is_health(self, categorizer):
        assert categorizer.categorize("Gym membership fee") == "Health"

    def test_rent_is_housing(self, categorizer):
        assert categorizer.categorize("Monthly rent payment") == "Housing"

    def test_hotel_is_travel(self, categorizer):
        assert categorizer.categorize("Hotel booking Miami") == "Travel"

    def test_no_match_returns_other(self, categorizer):
        assert categorizer.categorize("Random unknown expense xyz") == "Other"

    def test_empty_description_returns_other(self, categorizer):
        assert categorizer.categorize("") == "Other"

    def test_trader_joe_is_groceries(self, categorizer):
        assert categorizer.categorize("Trader Joe's shopping trip") == "Groceries"

    def test_multi_word_keyword(self, categorizer):
        """Keywords like 'whole foods' should match as a phrase."""
        assert categorizer.categorize("whole foods market") == "Groceries"

    def test_uber_eats_is_dining_not_transport(self, categorizer):
        """'uber eats' should match Dining before 'uber' matches Transport."""
        assert categorizer.categorize("Uber Eats delivery pizza") == "Dining"


# =========================================================================
# Icon lookup
# =========================================================================


class TestGetIcon:

    def test_known_category(self, categorizer):
        assert categorizer.get_icon("Groceries") == "🛒"

    def test_case_insensitive(self, categorizer):
        assert categorizer.get_icon("dining") == "🍽️"

    def test_unknown_category(self, categorizer):
        assert categorizer.get_icon("NonExistentCategory") == "📦"


# =========================================================================
# Caching
# =========================================================================


class TestCaching:

    def test_loads_categories_once(self, mock_sheets, categorizer):
        categorizer.categorize("test1")
        categorizer.categorize("test2")
        categorizer.categorize("test3")
        # Should only call get_categories once (cached)
        assert mock_sheets.get_categories.call_count == 1

    def test_reload_forces_fresh_load(self, mock_sheets, categorizer):
        categorizer.categorize("test1")
        categorizer.reload()
        categorizer.categorize("test2")
        assert mock_sheets.get_categories.call_count == 2
