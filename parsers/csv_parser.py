"""CSV statement parsers for Chase, Amex, Discover, and Capital One.

Each bank exports CSVs in a different format. This module:
1. Auto-detects which bank the CSV came from
2. Normalizes transactions into a standard format
3. Imports them into Google Sheets with auto-categorization

Usage:
    from parsers.csv_parser import import_csv
    result = import_csv("statement.csv", sheets, categorizer, card="Chase Sapphire")
    # result = {"imported": 5, "skipped_duplicates": 2, "errors": 0}
"""

import logging
from datetime import date, datetime

import pandas as pd

from parsers.base import StatementParser
from services.categorizer import Categorizer
from services.exceptions import DuplicateTransactionError, InvalidDataError
from services.sheets import GoogleSheetsService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bank-specific parsers
# ---------------------------------------------------------------------------


class ChaseParser(StatementParser):
    """Parse Chase credit card CSV exports.

    Chase format:
        Transaction Date, Post Date, Description, Category, Type, Amount, Memo
        01/15/2025, 01/16/2025, WHOLE FOODS MARKET, Groceries, Sale, -45.67,

    Note: Purchases are NEGATIVE, payments/credits are POSITIVE.
    """

    bank_name = "Chase"

    def can_parse(self, df: pd.DataFrame) -> bool:
        cols = {c.lower().strip() for c in df.columns}
        return (
            "transaction date" in cols
            and "description" in cols
            and "amount" in cols
            and "post date" in cols
        )

    def parse(self, df: pd.DataFrame) -> list[dict]:
        df.columns = [c.strip() for c in df.columns]
        transactions = []
        for _, row in df.iterrows():
            try:
                raw_amount = float(row["Amount"])
                # Chase: negative = purchase, positive = payment/credit
                amount = -raw_amount
                if amount <= 0:
                    continue  # skip payments/credits

                txn_date = pd.to_datetime(row["Transaction Date"]).date()
                description = str(row["Description"]).strip()

                transactions.append(
                    {"date": txn_date, "amount": amount, "description": description}
                )
            except (ValueError, KeyError) as e:
                logger.warning("Skipping Chase row: %s", e)
                continue

        return transactions


class AmexParser(StatementParser):
    """Parse American Express CSV exports.

    Amex format:
        Date, Description, Amount
        01/15/2025, WHOLE FOODS MARKET, 45.67

    Note: Purchases are POSITIVE (opposite of Chase).
    """

    bank_name = "Amex"

    def can_parse(self, df: pd.DataFrame) -> bool:
        cols = {c.lower().strip() for c in df.columns}
        # Amex has Date + Description + Amount but NOT "Transaction Date" or "Post Date"
        return (
            "date" in cols
            and "description" in cols
            and "amount" in cols
            and "transaction date" not in cols
            and "trans. date" not in cols
        )

    def parse(self, df: pd.DataFrame) -> list[dict]:
        df.columns = [c.strip() for c in df.columns]
        transactions = []
        for _, row in df.iterrows():
            try:
                amount = float(row["Amount"])
                if amount <= 0:
                    continue  # skip payments/credits

                txn_date = pd.to_datetime(row["Date"]).date()
                description = str(row["Description"]).strip()

                transactions.append(
                    {"date": txn_date, "amount": amount, "description": description}
                )
            except (ValueError, KeyError) as e:
                logger.warning("Skipping Amex row: %s", e)
                continue

        return transactions


class DiscoverParser(StatementParser):
    """Parse Discover card CSV exports.

    Discover format:
        Trans. Date, Post Date, Description, Amount, Category
        01/15/2025, 01/16/2025, WHOLE FOODS MARKET, 45.67, Supermarkets

    Note: Purchases are POSITIVE.
    """

    bank_name = "Discover"

    def can_parse(self, df: pd.DataFrame) -> bool:
        cols = {c.lower().strip() for c in df.columns}
        return "trans. date" in cols and "description" in cols and "amount" in cols

    def parse(self, df: pd.DataFrame) -> list[dict]:
        df.columns = [c.strip() for c in df.columns]
        transactions = []
        for _, row in df.iterrows():
            try:
                amount = float(row["Amount"])
                if amount <= 0:
                    continue  # skip payments/credits

                txn_date = pd.to_datetime(row["Trans. Date"]).date()
                description = str(row["Description"]).strip()

                transactions.append(
                    {"date": txn_date, "amount": amount, "description": description}
                )
            except (ValueError, KeyError) as e:
                logger.warning("Skipping Discover row: %s", e)
                continue

        return transactions


class CapitalOneParser(StatementParser):
    """Parse Capital One CSV exports.

    Capital One format:
        Transaction Date, Posted Date, Card No., Description, Category, Debit, Credit
        2025-01-15, 2025-01-16, 1234, WHOLE FOODS MARKET, Groceries, 45.67,

    Note: Separate Debit and Credit columns. Debit = purchase, Credit = payment.
    """

    bank_name = "Capital One"

    def can_parse(self, df: pd.DataFrame) -> bool:
        cols = {c.lower().strip() for c in df.columns}
        return (
            "transaction date" in cols
            and "description" in cols
            and "debit" in cols
            and "credit" in cols
        )

    def parse(self, df: pd.DataFrame) -> list[dict]:
        df.columns = [c.strip() for c in df.columns]
        transactions = []
        for _, row in df.iterrows():
            try:
                # Capital One uses separate Debit/Credit columns
                debit = row.get("Debit")
                if pd.isna(debit) or debit == "":
                    continue  # no debit = payment/credit row, skip

                amount = float(debit)
                if amount <= 0:
                    continue

                txn_date = pd.to_datetime(row["Transaction Date"]).date()
                description = str(row["Description"]).strip()

                transactions.append(
                    {"date": txn_date, "amount": amount, "description": description}
                )
            except (ValueError, KeyError) as e:
                logger.warning("Skipping Capital One row: %s", e)
                continue

        return transactions


# ---------------------------------------------------------------------------
# Auto-detection & import
# ---------------------------------------------------------------------------

# Order matters: CapitalOne before Chase (both have "Transaction Date",
# but CapitalOne also has "Debit"/"Credit" columns)
ALL_PARSERS: list[StatementParser] = [
    CapitalOneParser(),
    ChaseParser(),
    DiscoverParser(),
    AmexParser(),
]


def detect_bank(df: pd.DataFrame) -> StatementParser | None:
    """Auto-detect which bank parser can handle this CSV.

    Returns the matching parser, or None if no parser matches.
    """
    for parser in ALL_PARSERS:
        if parser.can_parse(df):
            return parser
    return None


def import_csv(
    filepath: str,
    sheets: GoogleSheetsService,
    categorizer: Categorizer,
    user: str = "user1",
    card: str = "",
) -> dict:
    """Import a CSV credit card statement into Google Sheets.

    Auto-detects the bank format, categorizes transactions, and adds them
    to the Sheets database. Skips duplicates safely.

    Args:
        filepath: Path to the CSV file.
        sheets: Initialized GoogleSheetsService.
        categorizer: Initialized Categorizer for auto-categorization.
        user: Which user owns these transactions ("user1" or "user2").
        card: Credit card name (e.g., "Chase Sapphire").

    Returns:
        Summary dict: {"imported": int, "skipped_duplicates": int,
                        "errors": int, "bank": str}

    Raises:
        InvalidDataError: If the CSV can't be read or no parser matches.
    """
    # Read CSV
    try:
        df = pd.read_csv(filepath)
    except Exception as e:
        raise InvalidDataError(f"Could not read CSV file: {e}") from e

    if df.empty:
        raise InvalidDataError("CSV file is empty.")

    # Auto-detect bank
    parser = detect_bank(df)
    if parser is None:
        columns = ", ".join(df.columns.tolist())
        raise InvalidDataError(
            f"Unrecognized CSV format. Columns found: {columns}\n"
            f"Supported banks: Chase, Amex, Discover, Capital One"
        )

    logger.info("Detected bank: %s (%d rows)", parser.bank_name, len(df))

    # Parse into standardized transactions
    transactions = parser.parse(df)
    logger.info("Parsed %d purchase transactions", len(transactions))

    # Import each transaction
    imported = 0
    skipped = 0
    errors = 0

    for txn in transactions:
        try:
            category = categorizer.categorize(txn["description"])
            sheets.add_transaction(
                amount=txn["amount"],
                category=category,
                description=txn["description"],
                user=user,
                transaction_date=txn["date"],
                source="csv",
                card=card,
            )
            imported += 1
        except DuplicateTransactionError:
            skipped += 1
        except Exception as e:
            logger.error("Error importing transaction: %s — %s", txn, e)
            errors += 1

    return {
        "imported": imported,
        "skipped_duplicates": skipped,
        "errors": errors,
        "bank": parser.bank_name,
    }
