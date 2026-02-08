"""Abstract base class for credit card statement parsers.

Each bank has a different CSV format. Subclasses implement:
- can_parse(df) → True if this parser handles the CSV columns
- parse(df) → list of standardized transaction dicts
"""

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd


class StatementParser(ABC):
    """Base class for all statement parsers."""

    # Human-readable name for this parser (e.g., "Chase", "Amex")
    bank_name: str = "Unknown"

    @abstractmethod
    def can_parse(self, df: pd.DataFrame) -> bool:
        """Return True if this parser can handle the given DataFrame.

        Checks whether the CSV columns match the expected format for
        this bank.
        """

    @abstractmethod
    def parse(self, df: pd.DataFrame) -> list[dict]:
        """Parse a DataFrame into standardized transaction dicts.

        Each dict has:
            - "date": datetime.date
            - "amount": float (positive = purchase)
            - "description": str

        Payments/credits (amount <= 0) should be excluded.
        """
