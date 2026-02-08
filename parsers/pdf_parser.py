"""PDF statement parsers for Chase, Amex, Discover, and Capital One.

Uses pdfplumber to extract transaction tables from credit card PDF statements.
Strategy: table extraction first, regex text fallback.

Usage:
    from parsers.pdf_parser import import_pdf
    result = import_pdf("statement.pdf", sheets, categorizer, card="Chase Sapphire")
    # result = {"imported": 5, "skipped_duplicates": 2, "errors": 0, "bank": "Chase"}
"""

import logging
import re
from abc import ABC, abstractmethod
from datetime import date, datetime

import pdfplumber

from services.categorizer import Categorizer
from services.exceptions import DuplicateTransactionError, InvalidDataError
from services.sheets import GoogleSheetsService

logger = logging.getLogger(__name__)

# Keywords that indicate a row is a payment/credit, not a purchase
PAYMENT_KEYWORDS = [
    "payment",
    "thank you",
    "credit",
    "autopay",
    "refund",
    "adjustment",
    "late fee reversal",
    "returned",
]

# Regex for dates in common statement formats
DATE_PATTERN = re.compile(r"(\d{1,2}/\d{1,2}(?:/\d{2,4})?)")
# Regex for amounts like 1,234.56 or 45.67 at end of string
AMOUNT_PATTERN = re.compile(r"[\$]?([\d,]+\.\d{2})\s*$")
# Regex for a full transaction line: date ... description ... amount
TRANSACTION_LINE = re.compile(
    r"(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s+"  # date
    r"(.+?)\s+"  # description (non-greedy)
    r"[\$]?([\d,]+\.\d{2})\s*$"  # amount at end
)


def _parse_date(date_str: str, statement_year: int | None = None) -> date | None:
    """Parse a date string from a statement.

    Handles: MM/DD, MM/DD/YY, MM/DD/YYYY
    If no year is given, uses statement_year or current year.
    """
    date_str = date_str.strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            parsed = datetime.strptime(date_str, fmt)
            return parsed.date()
        except ValueError:
            continue

    # Try MM/DD without year — manually construct date to avoid
    # Python 3.15 deprecation warning with strptime
    parts = date_str.split("/")
    if len(parts) == 2:
        try:
            month, day = int(parts[0]), int(parts[1])
            year = statement_year or date.today().year
            return date(year, month, day)
        except (ValueError, TypeError):
            pass

    return None


def _parse_amount(amount_str: str) -> float | None:
    """Parse an amount string like '1,234.56' or '$45.67'."""
    try:
        cleaned = amount_str.replace(",", "").replace("$", "").strip()
        return float(cleaned)
    except (ValueError, AttributeError):
        return None


def _is_payment(description: str) -> bool:
    """Check if a description looks like a payment/credit rather than a purchase."""
    desc_lower = description.lower()
    return any(kw in desc_lower for kw in PAYMENT_KEYWORDS)


def _extract_year_from_text(full_text: str) -> int | None:
    """Try to find the statement year from the PDF text.

    Looks for patterns like 'Statement Date: 01/15/2025' or 'January 2025'.
    """
    # Try "Statement Date" or similar
    year_match = re.search(r"(\d{1,2}/\d{1,2}/(\d{4}))", full_text)
    if year_match:
        return int(year_match.group(2))

    # Try month name + year
    month_year = re.search(
        r"(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+(\d{4})",
        full_text,
    )
    if month_year:
        return int(month_year.group(2))

    return None


# ---------------------------------------------------------------------------
# PDF parser base
# ---------------------------------------------------------------------------


class PdfStatementParser(ABC):
    """Base class for PDF statement parsers."""

    bank_name: str = "Unknown"

    @abstractmethod
    def can_parse(self, text: str) -> bool:
        """Return True if this parser handles PDFs from this bank.

        Args:
            text: Full text extracted from the first page of the PDF.
        """

    @abstractmethod
    def parse_transactions(
        self, pdf: pdfplumber.PDF, statement_year: int | None = None
    ) -> list[dict]:
        """Extract transactions from the PDF.

        Returns list of dicts: {"date": date, "amount": float, "description": str}
        """


# ---------------------------------------------------------------------------
# Bank-specific parsers
# ---------------------------------------------------------------------------


class ChasePdfParser(PdfStatementParser):
    """Parse Chase credit card PDF statements.

    Chase PDFs contain transaction tables with:
    Date of Transaction | Merchant Name | Amount
    Amounts are positive for purchases.
    """

    bank_name = "Chase"

    def can_parse(self, text: str) -> bool:
        text_lower = text.lower()
        return "jpmorgan chase" in text_lower or "chase.com" in text_lower

    def parse_transactions(
        self, pdf: pdfplumber.PDF, statement_year: int | None = None
    ) -> list[dict]:
        transactions = []
        for page in pdf.pages:
            # Try table extraction first
            tables = page.extract_tables()
            if tables:
                for table in tables:
                    transactions.extend(
                        self._parse_table_rows(table, statement_year)
                    )
            else:
                # Fallback: text line parsing
                text = page.extract_text() or ""
                transactions.extend(
                    self._parse_text_lines(text, statement_year)
                )
        return transactions

    def _parse_table_rows(
        self, table: list[list], statement_year: int | None
    ) -> list[dict]:
        results = []
        for row in table:
            if not row or len(row) < 2:
                continue
            # Find cells that look like date, description, amount
            row_text = [str(cell).strip() if cell else "" for cell in row]
            txn = self._try_parse_row(row_text, statement_year)
            if txn:
                results.append(txn)
        return results

    def _parse_text_lines(
        self, text: str, statement_year: int | None
    ) -> list[dict]:
        results = []
        for line in text.split("\n"):
            match = TRANSACTION_LINE.match(line.strip())
            if match:
                txn_date = _parse_date(match.group(1), statement_year)
                description = match.group(2).strip()
                amount = _parse_amount(match.group(3))
                if txn_date and amount and amount > 0 and not _is_payment(description):
                    results.append(
                        {"date": txn_date, "amount": amount, "description": description}
                    )
        return results

    def _try_parse_row(
        self, cells: list[str], statement_year: int | None
    ) -> dict | None:
        """Try to extract a transaction from table row cells."""
        date_val = None
        amount_val = None
        desc_parts = []

        for cell in cells:
            if not cell:
                continue
            # Try as date
            if date_val is None:
                d = _parse_date(cell, statement_year)
                if d:
                    date_val = d
                    continue
            # Try as amount (last numeric cell wins)
            a = _parse_amount(cell)
            if a is not None:
                amount_val = a
                continue
            # Otherwise it's description
            desc_parts.append(cell)

        description = " ".join(desc_parts).strip()
        if date_val and amount_val and amount_val > 0 and description and not _is_payment(description):
            return {"date": date_val, "amount": amount_val, "description": description}
        return None


class AmexPdfParser(PdfStatementParser):
    """Parse American Express PDF statements."""

    bank_name = "Amex"

    def can_parse(self, text: str) -> bool:
        text_lower = text.lower()
        return "american express" in text_lower or "amex" in text_lower

    def parse_transactions(
        self, pdf: pdfplumber.PDF, statement_year: int | None = None
    ) -> list[dict]:
        transactions = []
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.split("\n"):
                match = TRANSACTION_LINE.match(line.strip())
                if match:
                    txn_date = _parse_date(match.group(1), statement_year)
                    description = match.group(2).strip()
                    amount = _parse_amount(match.group(3))
                    if txn_date and amount and amount > 0 and not _is_payment(description):
                        transactions.append(
                            {"date": txn_date, "amount": amount, "description": description}
                        )
        return transactions


class DiscoverPdfParser(PdfStatementParser):
    """Parse Discover card PDF statements."""

    bank_name = "Discover"

    def can_parse(self, text: str) -> bool:
        text_lower = text.lower()
        return "discover" in text_lower and (
            "discover.com" in text_lower
            or "discover bank" in text_lower
            or "discover financial" in text_lower
            or "cashback" in text_lower
        )

    def parse_transactions(
        self, pdf: pdfplumber.PDF, statement_year: int | None = None
    ) -> list[dict]:
        transactions = []
        for page in pdf.pages:
            tables = page.extract_tables()
            if tables:
                for table in tables:
                    for row in table:
                        if not row or len(row) < 3:
                            continue
                        cells = [str(c).strip() if c else "" for c in row]
                        txn = self._try_parse_row(cells, statement_year)
                        if txn:
                            transactions.append(txn)
            else:
                text = page.extract_text() or ""
                for line in text.split("\n"):
                    match = TRANSACTION_LINE.match(line.strip())
                    if match:
                        txn_date = _parse_date(match.group(1), statement_year)
                        description = match.group(2).strip()
                        amount = _parse_amount(match.group(3))
                        if txn_date and amount and amount > 0 and not _is_payment(description):
                            transactions.append(
                                {"date": txn_date, "amount": amount, "description": description}
                            )
        return transactions

    def _try_parse_row(
        self, cells: list[str], statement_year: int | None
    ) -> dict | None:
        """Parse a Discover table row: Trans Date, Post Date, Description, Amount."""
        date_val = None
        amount_val = None
        desc_parts = []

        for cell in cells:
            if not cell:
                continue
            if date_val is None:
                d = _parse_date(cell, statement_year)
                if d:
                    date_val = d
                    continue
            a = _parse_amount(cell)
            if a is not None:
                amount_val = a
                continue
            desc_parts.append(cell)

        description = " ".join(desc_parts).strip()
        if date_val and amount_val and amount_val > 0 and description and not _is_payment(description):
            return {"date": date_val, "amount": amount_val, "description": description}
        return None


class CapitalOnePdfParser(PdfStatementParser):
    """Parse Capital One PDF statements."""

    bank_name = "Capital One"

    def can_parse(self, text: str) -> bool:
        text_lower = text.lower()
        return "capital one" in text_lower

    def parse_transactions(
        self, pdf: pdfplumber.PDF, statement_year: int | None = None
    ) -> list[dict]:
        transactions = []
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.split("\n"):
                match = TRANSACTION_LINE.match(line.strip())
                if match:
                    txn_date = _parse_date(match.group(1), statement_year)
                    description = match.group(2).strip()
                    amount = _parse_amount(match.group(3))
                    if txn_date and amount and amount > 0 and not _is_payment(description):
                        transactions.append(
                            {"date": txn_date, "amount": amount, "description": description}
                        )
        return transactions


# ---------------------------------------------------------------------------
# Auto-detection & import
# ---------------------------------------------------------------------------

ALL_PDF_PARSERS: list[PdfStatementParser] = [
    ChasePdfParser(),
    AmexPdfParser(),
    DiscoverPdfParser(),
    CapitalOnePdfParser(),
]


def detect_pdf_bank(text: str) -> PdfStatementParser | None:
    """Auto-detect which bank issued this PDF statement.

    Args:
        text: Full text from the first page of the PDF.

    Returns:
        Matching parser, or None if unrecognized.
    """
    for parser in ALL_PDF_PARSERS:
        if parser.can_parse(text):
            return parser
    return None


def import_pdf(
    filepath: str,
    sheets: GoogleSheetsService,
    categorizer: Categorizer,
    user: str = "user1",
    card: str = "",
) -> dict:
    """Import a PDF credit card statement into Google Sheets.

    Auto-detects the bank, extracts transactions, categorizes them,
    and adds to Sheets. Skips duplicates safely.

    Args:
        filepath: Path to the PDF file.
        sheets: Initialized GoogleSheetsService.
        categorizer: Initialized Categorizer for auto-categorization.
        user: Which user owns these transactions ("user1" or "user2").
        card: Credit card name (e.g., "Chase Sapphire").

    Returns:
        Summary dict: {"imported": int, "skipped_duplicates": int,
                        "errors": int, "bank": str}

    Raises:
        InvalidDataError: If the PDF can't be read or no parser matches.
    """
    try:
        pdf = pdfplumber.open(filepath)
    except Exception as e:
        raise InvalidDataError(f"Could not open PDF file: {e}") from e

    if not pdf.pages:
        pdf.close()
        raise InvalidDataError("PDF has no pages.")

    # Get first page text for bank detection
    first_page_text = pdf.pages[0].extract_text() or ""
    if not first_page_text.strip():
        pdf.close()
        raise InvalidDataError("PDF has no extractable text (may be image-based).")

    # Detect bank
    parser = detect_pdf_bank(first_page_text)
    if parser is None:
        pdf.close()
        raise InvalidDataError(
            "Unrecognized PDF format. Could not identify the bank.\n"
            "Supported banks: Chase, Amex, Discover, Capital One"
        )

    logger.info("Detected bank: %s (%d pages)", parser.bank_name, len(pdf.pages))

    # Extract statement year
    full_text = "\n".join(
        page.extract_text() or "" for page in pdf.pages
    )
    statement_year = _extract_year_from_text(full_text)

    # Parse transactions
    transactions = parser.parse_transactions(pdf, statement_year)
    pdf.close()
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
                source="statement",
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
