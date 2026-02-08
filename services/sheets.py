"""Google Sheets service — the data layer for the finance assistant.

This module provides CRUD operations for all 4 sheets:
- Transactions: Daily spending records
- Bills: Recurring bill definitions
- Budgets: Monthly budget limits per category
- Categories: Spending categories with keyword matching

Usage:
    from services.sheets import GoogleSheetsService
    from config.settings import get_settings

    settings = get_settings()
    sheets = GoogleSheetsService(
        credentials_file=settings.google_credentials_file,
        spreadsheet_id=settings.google_spreadsheet_id,
    )
    sheets.initialize()  # Creates sheets + default categories if needed
"""

import logging
import uuid
from datetime import date, datetime
from typing import Any, Optional

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

from services.exceptions import (
    DuplicateTransactionError,
    InvalidDataError,
    SheetsConnectionError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

TRANSACTION_HEADERS = [
    "id", "date", "amount", "category", "description",
    "user", "source", "card", "is_shared", "created_at",
]

BILL_HEADERS = [
    "id", "name", "amount", "due_day", "frequency",
    "category", "user", "auto_pay", "active",
]

BUDGET_HEADERS = ["category", "monthly_limit", "user"]

CATEGORY_HEADERS = ["name", "keywords", "icon"]

DEFAULT_CATEGORIES = [
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


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _generate_id() -> str:
    """Generate a short unique ID (first 8 chars of UUID4)."""
    return uuid.uuid4().hex[:8]


def _to_bool_str(value: bool) -> str:
    """Convert Python bool to Sheets-friendly string."""
    return "TRUE" if value else "FALSE"


def _from_bool_str(value: str) -> bool:
    """Convert Sheets string back to Python bool."""
    return str(value).upper() in ("TRUE", "1", "YES")


def _today_str() -> str:
    """Return today's date as ISO string."""
    return date.today().isoformat()


def _now_str() -> str:
    """Return current datetime as ISO string."""
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Main service class
# ---------------------------------------------------------------------------

class GoogleSheetsService:
    """Manages all Google Sheets operations for the finance assistant.

    Call initialize() after creating the instance to set up sheets.
    """

    def __init__(self, credentials_file: str, spreadsheet_id: str):
        """Connect to Google Sheets.

        Args:
            credentials_file: Path to the service account JSON key file.
            spreadsheet_id: The Google Sheets spreadsheet ID.

        Raises:
            SheetsConnectionError: If connection fails.
        """
        try:
            creds = Credentials.from_service_account_file(
                credentials_file, scopes=SCOPES
            )
            self._client = gspread.authorize(creds)
            self._spreadsheet = self._client.open_by_key(spreadsheet_id)
            logger.info("Connected to Google Sheets: %s", self._spreadsheet.title)
        except FileNotFoundError:
            raise SheetsConnectionError(
                f"Credentials file not found: {credentials_file}"
            )
        except Exception as e:
            raise SheetsConnectionError(f"Failed to connect to Google Sheets: {e}")

        # Cache worksheet references
        self._sheets: dict[str, gspread.Worksheet] = {}
        self._initialized = False

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Create sheets and default data if they don't exist.

        Safe to call multiple times — skips if already initialized.
        """
        if self._initialized:
            return

        self._ensure_sheet("Transactions", TRANSACTION_HEADERS)
        self._ensure_sheet("Bills", BILL_HEADERS)
        self._ensure_sheet("Budgets", BUDGET_HEADERS)
        self._ensure_sheet("Categories", CATEGORY_HEADERS)

        # Populate default categories if the sheet is empty
        cat_sheet = self._sheets["Categories"]
        existing = cat_sheet.get_all_records()
        if len(existing) == 0:
            rows = [[c["name"], c["keywords"], c["icon"]] for c in DEFAULT_CATEGORIES]
            cat_sheet.append_rows(rows, value_input_option="USER_ENTERED")
            logger.info("Populated %d default categories", len(DEFAULT_CATEGORIES))

        self._initialized = True
        logger.info("Sheets initialized successfully")

    def _ensure_sheet(self, name: str, headers: list[str]) -> gspread.Worksheet:
        """Get or create a worksheet with the given headers."""
        try:
            sheet = self._spreadsheet.worksheet(name)
        except gspread.WorksheetNotFound:
            sheet = self._spreadsheet.add_worksheet(
                title=name, rows=1000, cols=len(headers)
            )
            sheet.append_row(headers, value_input_option="USER_ENTERED")
            logger.info("Created sheet: %s", name)

        self._sheets[name] = sheet
        return sheet

    def _get_sheet(self, name: str) -> gspread.Worksheet:
        """Return cached worksheet reference."""
        if name not in self._sheets:
            self._ensure_sheet(
                name,
                {
                    "Transactions": TRANSACTION_HEADERS,
                    "Bills": BILL_HEADERS,
                    "Budgets": BUDGET_HEADERS,
                    "Categories": CATEGORY_HEADERS,
                }[name],
            )
        return self._sheets[name]

    # ------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------

    def add_transaction(
        self,
        amount: float,
        category: str,
        description: str,
        user: str,
        transaction_date: Optional[date] = None,
        source: str = "manual",
        card: str = "",
        is_shared: bool = False,
    ) -> str:
        """Add a new transaction and return its ID.

        Args:
            amount: Transaction amount (positive number).
            category: Spending category name.
            description: What the transaction was for.
            user: "user1" or "user2".
            transaction_date: Date of transaction (defaults to today).
            source: How it was entered — "manual", "statement", or "csv".
            card: Credit card name (optional).
            is_shared: Whether this is a shared expense.

        Returns:
            The generated transaction ID.

        Raises:
            InvalidDataError: If amount is not positive.
            DuplicateTransactionError: If a duplicate is detected.
        """
        if amount <= 0:
            raise InvalidDataError("Amount must be positive")

        t_date = (transaction_date or date.today()).isoformat()

        # Check for duplicates
        if self.check_duplicate(t_date, amount, description):
            raise DuplicateTransactionError(
                f"Duplicate transaction: {t_date} | ${amount} | {description}"
            )

        t_id = _generate_id()
        row = [
            t_id,
            t_date,
            amount,
            category,
            description,
            user,
            source,
            card,
            _to_bool_str(is_shared),
            _now_str(),
        ]

        self._get_sheet("Transactions").append_row(
            row, value_input_option="USER_ENTERED"
        )
        logger.info("Added transaction %s: $%.2f %s", t_id, amount, category)
        return t_id

    def get_transactions(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        user: Optional[str] = None,
        category: Optional[str] = None,
    ) -> pd.DataFrame:
        """Get transactions as a DataFrame, optionally filtered.

        Args:
            start_date: Include transactions on or after this date.
            end_date: Include transactions on or before this date.
            user: Filter by user ("user1" or "user2").
            category: Filter by category name.

        Returns:
            DataFrame with columns matching TRANSACTION_HEADERS.
            Empty DataFrame if no transactions found.
        """
        records = self._get_sheet("Transactions").get_all_records()
        if not records:
            return pd.DataFrame(columns=TRANSACTION_HEADERS)

        df = pd.DataFrame(records)

        # Ensure expected columns exist
        for col in TRANSACTION_HEADERS:
            if col not in df.columns:
                df[col] = ""

        # Convert types
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
        df["is_shared"] = df["is_shared"].apply(_from_bool_str)

        # Apply filters
        if start_date:
            df = df[df["date"] >= start_date]
        if end_date:
            df = df[df["date"] <= end_date]
        if user:
            df = df[df["user"] == user]
        if category:
            df = df[df["category"].str.lower() == category.lower()]

        return df.reset_index(drop=True)

    def update_transaction(self, transaction_id: str, **updates: Any) -> bool:
        """Update fields of an existing transaction.

        Args:
            transaction_id: The ID of the transaction to update.
            **updates: Field names and new values (e.g., amount=50, category="Dining").

        Returns:
            True if the transaction was found and updated.
        """
        return self._update_row("Transactions", "id", transaction_id, updates)

    def delete_transaction(self, transaction_id: str) -> bool:
        """Delete a transaction by ID.

        Returns:
            True if the transaction was found and deleted.
        """
        return self._delete_row("Transactions", "id", transaction_id)

    def check_duplicate(
        self, transaction_date: str, amount: float, description: str
    ) -> bool:
        """Check if a transaction with same date+amount+description exists.

        Args:
            transaction_date: ISO date string (YYYY-MM-DD).
            amount: Transaction amount.
            description: Transaction description.

        Returns:
            True if a likely duplicate exists.
        """
        records = self._get_sheet("Transactions").get_all_records()
        for r in records:
            if (
                str(r.get("date", "")) == str(transaction_date)
                and abs(float(r.get("amount", 0)) - float(amount)) < 0.01
                and str(r.get("description", "")).lower() == description.lower()
            ):
                return True
        return False

    # ------------------------------------------------------------------
    # Bills
    # ------------------------------------------------------------------

    def add_bill(
        self,
        name: str,
        amount: float,
        due_day: int,
        frequency: str,
        category: str,
        user: str,
        auto_pay: bool = False,
    ) -> str:
        """Add a new recurring bill and return its ID.

        Args:
            name: Bill name (e.g., "Netflix", "Rent").
            amount: Bill amount.
            due_day: Day of the month (1-31).
            frequency: "monthly", "quarterly", or "annual".
            category: Spending category.
            user: "user1", "user2", or "shared".
            auto_pay: Whether this bill is on auto-pay.

        Returns:
            The generated bill ID.

        Raises:
            InvalidDataError: If due_day or frequency is invalid.
        """
        if not 1 <= due_day <= 31:
            raise InvalidDataError(f"due_day must be 1-31, got {due_day}")
        if frequency not in ("monthly", "quarterly", "annual"):
            raise InvalidDataError(
                f"frequency must be monthly/quarterly/annual, got {frequency}"
            )
        if amount <= 0:
            raise InvalidDataError("Amount must be positive")

        bill_id = _generate_id()
        row = [
            bill_id, name, amount, due_day, frequency,
            category, user, _to_bool_str(auto_pay), _to_bool_str(True),
        ]

        self._get_sheet("Bills").append_row(row, value_input_option="USER_ENTERED")
        logger.info("Added bill %s: %s $%.2f", bill_id, name, amount)
        return bill_id

    def get_bills(
        self,
        active_only: bool = False,
        user: Optional[str] = None,
    ) -> pd.DataFrame:
        """Get bills as a DataFrame, optionally filtered.

        Args:
            active_only: If True, only return active bills.
            user: Filter by user.

        Returns:
            DataFrame with columns matching BILL_HEADERS.
        """
        records = self._get_sheet("Bills").get_all_records()
        if not records:
            return pd.DataFrame(columns=BILL_HEADERS)

        df = pd.DataFrame(records)
        for col in BILL_HEADERS:
            if col not in df.columns:
                df[col] = ""

        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
        df["due_day"] = pd.to_numeric(df["due_day"], errors="coerce").fillna(0).astype(int)
        df["auto_pay"] = df["auto_pay"].apply(_from_bool_str)
        df["active"] = df["active"].apply(_from_bool_str)

        if active_only:
            df = df[df["active"]]
        if user:
            df = df[df["user"] == user]

        return df.reset_index(drop=True)

    def update_bill(self, bill_id: str, **updates: Any) -> bool:
        """Update fields of an existing bill."""
        return self._update_row("Bills", "id", bill_id, updates)

    def delete_bill(self, bill_id: str) -> bool:
        """Delete a bill by ID."""
        return self._delete_row("Bills", "id", bill_id)

    # ------------------------------------------------------------------
    # Budgets
    # ------------------------------------------------------------------

    def set_budget(self, category: str, monthly_limit: float, user: str) -> bool:
        """Set (or update) a budget for a category+user combination.

        If a budget already exists for this category+user, it updates the limit.
        Otherwise, creates a new row.

        Args:
            category: Spending category.
            monthly_limit: Monthly budget limit.
            user: "user1", "user2", or "shared".

        Returns:
            True on success.
        """
        if monthly_limit <= 0:
            raise InvalidDataError("Monthly limit must be positive")

        sheet = self._get_sheet("Budgets")
        records = sheet.get_all_records()

        # Check if budget already exists (upsert)
        for i, r in enumerate(records):
            if (
                str(r.get("category", "")).lower() == category.lower()
                and str(r.get("user", "")) == user
            ):
                # Update existing — row index is i+2 (1-indexed + header row)
                sheet.update_cell(i + 2, 2, monthly_limit)
                logger.info("Updated budget: %s/%s = $%.2f", category, user, monthly_limit)
                return True

        # Insert new
        sheet.append_row(
            [category, monthly_limit, user],
            value_input_option="USER_ENTERED",
        )
        logger.info("Added budget: %s/%s = $%.2f", category, user, monthly_limit)
        return True

    def get_budgets(
        self,
        user: Optional[str] = None,
        category: Optional[str] = None,
    ) -> pd.DataFrame:
        """Get budgets as a DataFrame, optionally filtered."""
        records = self._get_sheet("Budgets").get_all_records()
        if not records:
            return pd.DataFrame(columns=BUDGET_HEADERS)

        df = pd.DataFrame(records)
        for col in BUDGET_HEADERS:
            if col not in df.columns:
                df[col] = ""

        df["monthly_limit"] = pd.to_numeric(df["monthly_limit"], errors="coerce").fillna(0)

        if user:
            df = df[df["user"] == user]
        if category:
            df = df[df["category"].str.lower() == category.lower()]

        return df.reset_index(drop=True)

    def delete_budget(self, category: str, user: str) -> bool:
        """Delete a budget by category+user."""
        sheet = self._get_sheet("Budgets")
        records = sheet.get_all_records()

        for i, r in enumerate(records):
            if (
                str(r.get("category", "")).lower() == category.lower()
                and str(r.get("user", "")) == user
            ):
                sheet.delete_rows(i + 2)  # 1-indexed + header
                logger.info("Deleted budget: %s/%s", category, user)
                return True
        return False

    # ------------------------------------------------------------------
    # Categories
    # ------------------------------------------------------------------

    def get_categories(self) -> pd.DataFrame:
        """Get all spending categories as a DataFrame."""
        records = self._get_sheet("Categories").get_all_records()
        if not records:
            return pd.DataFrame(columns=CATEGORY_HEADERS)

        df = pd.DataFrame(records)
        for col in CATEGORY_HEADERS:
            if col not in df.columns:
                df[col] = ""
        return df

    def add_category(self, name: str, keywords: str, icon: str) -> bool:
        """Add a new spending category.

        Args:
            name: Category name.
            keywords: Comma-separated keywords for auto-matching.
            icon: Emoji icon for display.

        Returns:
            True on success.
        """
        # Check if category already exists
        existing = self.get_categories()
        if not existing.empty and name.lower() in existing["name"].str.lower().values:
            raise InvalidDataError(f"Category '{name}' already exists")

        self._get_sheet("Categories").append_row(
            [name, keywords, icon],
            value_input_option="USER_ENTERED",
        )
        logger.info("Added category: %s %s", icon, name)
        return True

    # ------------------------------------------------------------------
    # Generic row helpers
    # ------------------------------------------------------------------

    def _find_row_index(
        self, sheet_name: str, key_column: str, key_value: str
    ) -> Optional[int]:
        """Find the row index (1-based) of a record by a key column value.

        Returns None if not found.
        """
        sheet = self._get_sheet(sheet_name)
        records = sheet.get_all_records()
        for i, r in enumerate(records):
            if str(r.get(key_column, "")) == str(key_value):
                return i + 2  # 1-indexed + header row
        return None

    def _update_row(
        self, sheet_name: str, key_column: str, key_value: str, updates: dict
    ) -> bool:
        """Update specific cells in a row identified by key_column=key_value."""
        sheet = self._get_sheet(sheet_name)
        row_index = self._find_row_index(sheet_name, key_column, key_value)
        if row_index is None:
            return False

        # Get header row to find column indices
        headers = sheet.row_values(1)

        for field, value in updates.items():
            if field not in headers:
                logger.warning("Unknown field '%s' for sheet '%s'", field, sheet_name)
                continue
            col_index = headers.index(field) + 1  # 1-indexed

            # Convert booleans
            if isinstance(value, bool):
                value = _to_bool_str(value)
            elif isinstance(value, date):
                value = value.isoformat()

            sheet.update_cell(row_index, col_index, value)

        logger.info("Updated %s row %s=%s", sheet_name, key_column, key_value)
        return True

    def _delete_row(self, sheet_name: str, key_column: str, key_value: str) -> bool:
        """Delete a row identified by key_column=key_value."""
        row_index = self._find_row_index(sheet_name, key_column, key_value)
        if row_index is None:
            return False

        self._get_sheet(sheet_name).delete_rows(row_index)
        logger.info("Deleted %s row %s=%s", sheet_name, key_column, key_value)
        return True
