"""Transaction categorizer — auto-detect spending category from description.

Matches transaction descriptions against keyword lists stored in the
Categories sheet. Falls back to "Other" if no match is found.

Usage:
    from services.categorizer import Categorizer

    categorizer = Categorizer(sheets_service)
    category = categorizer.categorize("Whole Foods organic milk")
    # → "Groceries"
"""

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


class Categorizer:
    """Auto-categorize transactions by matching descriptions to keywords."""

    def __init__(self, sheets_service):
        """Initialize with a GoogleSheetsService to load categories.

        Args:
            sheets_service: A GoogleSheetsService instance (must be initialized).
        """
        self._sheets = sheets_service
        self._categories: list[dict] = []
        self._loaded = False

    def _load_categories(self) -> None:
        """Load categories from Google Sheets (cached after first load)."""
        if self._loaded:
            return

        df = self._sheets.get_categories()
        self._categories = []

        for _, row in df.iterrows():
            keywords_str = str(row.get("keywords", ""))
            keywords = [k.strip().lower() for k in keywords_str.split(",") if k.strip()]
            self._categories.append(
                {
                    "name": str(row.get("name", "")),
                    "keywords": keywords,
                    "icon": str(row.get("icon", "")),
                }
            )

        self._loaded = True
        logger.info("Loaded %d categories for auto-categorization", len(self._categories))

    def reload(self) -> None:
        """Force reload categories from Google Sheets."""
        self._loaded = False
        self._load_categories()

    def categorize(self, description: str) -> str:
        """Determine the spending category for a transaction description.

        Checks if any category keyword appears in the description
        (case-insensitive substring match).

        Args:
            description: The transaction description (e.g., "Whole Foods organic milk").

        Returns:
            Category name (e.g., "Groceries") or "Other" if no match.
        """
        self._load_categories()

        description_lower = description.lower()

        for cat in self._categories:
            for keyword in cat["keywords"]:
                if keyword in description_lower:
                    logger.debug(
                        "Matched '%s' → %s (keyword: '%s')",
                        description, cat["name"], keyword,
                    )
                    return cat["name"]

        logger.debug("No category match for '%s' → Other", description)
        return "Other"

    def get_icon(self, category_name: str) -> str:
        """Get the emoji icon for a category.

        Args:
            category_name: Category name (e.g., "Groceries").

        Returns:
            Emoji icon (e.g., "🛒") or "📦" if not found.
        """
        self._load_categories()

        for cat in self._categories:
            if cat["name"].lower() == category_name.lower():
                return cat["icon"]
        return "📦"
