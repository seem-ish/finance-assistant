"""Tests for PDF statement parsers.

Run:
    pytest tests/test_pdf_parser.py -v

All tests use mocked pdfplumber objects — no real PDFs needed.
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from parsers.pdf_parser import (
    AmexPdfParser,
    CapitalOnePdfParser,
    ChasePdfParser,
    DiscoverPdfParser,
    _extract_year_from_text,
    _is_payment,
    _parse_amount,
    _parse_date,
    detect_pdf_bank,
    import_pdf,
)
from services.exceptions import DuplicateTransactionError, InvalidDataError


# =========================================================================
# Helper functions
# =========================================================================


class TestParseDate:

    def test_mm_dd_yyyy(self):
        assert _parse_date("01/15/2025") == date(2025, 1, 15)

    def test_mm_dd_yy(self):
        assert _parse_date("01/15/25") == date(2025, 1, 15)

    def test_mm_dd_with_year(self):
        assert _parse_date("01/15", statement_year=2025) == date(2025, 1, 15)

    def test_mm_dd_no_year_uses_current(self):
        result = _parse_date("06/15")
        assert result is not None
        assert result.month == 6
        assert result.day == 15

    def test_invalid_returns_none(self):
        assert _parse_date("not-a-date") is None


class TestParseAmount:

    def test_simple(self):
        assert _parse_amount("45.67") == 45.67

    def test_with_comma(self):
        assert _parse_amount("1,234.56") == 1234.56

    def test_with_dollar_sign(self):
        assert _parse_amount("$89.99") == 89.99

    def test_invalid_returns_none(self):
        assert _parse_amount("abc") is None


class TestIsPayment:

    def test_payment(self):
        assert _is_payment("PAYMENT THANK YOU") is True

    def test_autopay(self):
        assert _is_payment("AUTOPAY 01/15") is True

    def test_refund(self):
        assert _is_payment("REFUND - AMAZON") is True

    def test_purchase(self):
        assert _is_payment("WHOLE FOODS MARKET") is False


class TestExtractYear:

    def test_from_date_format(self):
        assert _extract_year_from_text("Statement Date: 01/15/2025") == 2025

    def test_from_month_year(self):
        assert _extract_year_from_text("January 2025 Statement") == 2025

    def test_no_year_returns_none(self):
        assert _extract_year_from_text("No year here") is None


# =========================================================================
# Bank detection
# =========================================================================


class TestChasePdfParser:
    parser = ChasePdfParser()

    def test_detects_chase(self):
        assert self.parser.can_parse("JPMorgan Chase Bank Account Statement") is True

    def test_detects_chase_url(self):
        assert self.parser.can_parse("Visit chase.com for details") is True

    def test_rejects_amex(self):
        assert self.parser.can_parse("American Express Statement") is False

    def test_parse_text_lines(self):
        mock_page = MagicMock()
        mock_page.extract_tables.return_value = []
        mock_page.extract_text.return_value = (
            "JPMorgan Chase Bank\n"
            "01/15 WHOLE FOODS MARKET 45.67\n"
            "01/16 STARBUCKS STORE 456 6.75\n"
            "01/20 PAYMENT THANK YOU 500.00\n"
        )
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]

        result = self.parser.parse_transactions(mock_pdf, statement_year=2025)
        assert len(result) == 2  # payment skipped
        assert result[0]["description"] == "WHOLE FOODS MARKET"
        assert result[0]["amount"] == 45.67
        assert result[0]["date"] == date(2025, 1, 15)

    def test_parse_table_rows(self):
        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [
            [
                ["Date", "Description", "Amount"],  # header row
                ["01/15", "WHOLE FOODS MARKET", "45.67"],
                ["01/16", "CHIPOTLE", "12.50"],
            ]
        ]
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]

        result = self.parser.parse_transactions(mock_pdf, statement_year=2025)
        assert len(result) == 2
        assert result[0]["amount"] == 45.67
        assert result[1]["description"] == "CHIPOTLE"


class TestAmexPdfParser:
    parser = AmexPdfParser()

    def test_detects_amex(self):
        assert self.parser.can_parse("American Express Company") is True

    def test_rejects_chase(self):
        assert self.parser.can_parse("JPMorgan Chase") is False

    def test_parse_transactions(self):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = (
            "American Express\n"
            "01/15 AMAZON MARKETPLACE 89.99\n"
            "01/16 CREDIT ADJUSTMENT -25.00\n"
        )
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]

        result = self.parser.parse_transactions(mock_pdf, statement_year=2025)
        assert len(result) == 1
        assert result[0]["description"] == "AMAZON MARKETPLACE"


class TestDiscoverPdfParser:
    parser = DiscoverPdfParser()

    def test_detects_discover(self):
        assert self.parser.can_parse("Discover Bank discover.com Cashback") is True

    def test_rejects_chase(self):
        assert self.parser.can_parse("JPMorgan Chase") is False

    def test_parse_text_lines(self):
        mock_page = MagicMock()
        mock_page.extract_tables.return_value = []
        mock_page.extract_text.return_value = (
            "Discover Financial\n"
            "01/15 TARGET STORE 33.99\n"
            "01/20 PAYMENT RECEIVED 200.00\n"
        )
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]

        result = self.parser.parse_transactions(mock_pdf, statement_year=2025)
        assert len(result) == 1
        assert result[0]["description"] == "TARGET STORE"


class TestCapitalOnePdfParser:
    parser = CapitalOnePdfParser()

    def test_detects_capital_one(self):
        assert self.parser.can_parse("Capital One Financial Corp") is True

    def test_rejects_amex(self):
        assert self.parser.can_parse("American Express") is False

    def test_parse_transactions(self):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = (
            "Capital One\n"
            "01/15 UBER EATS 18.50\n"
            "01/16 AUTOPAY 500.00\n"
        )
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]

        result = self.parser.parse_transactions(mock_pdf, statement_year=2025)
        assert len(result) == 1
        assert result[0]["description"] == "UBER EATS"


# =========================================================================
# Auto-detection
# =========================================================================


class TestDetectPdfBank:

    def test_detects_chase(self):
        parser = detect_pdf_bank("JPMorgan Chase Bank Statement")
        assert parser is not None
        assert parser.bank_name == "Chase"

    def test_detects_amex(self):
        parser = detect_pdf_bank("American Express Company")
        assert parser is not None
        assert parser.bank_name == "Amex"

    def test_detects_discover(self):
        parser = detect_pdf_bank("Discover Bank discover.com Cashback")
        assert parser is not None
        assert parser.bank_name == "Discover"

    def test_detects_capital_one(self):
        parser = detect_pdf_bank("Capital One Statement")
        assert parser is not None
        assert parser.bank_name == "Capital One"

    def test_unknown_returns_none(self):
        assert detect_pdf_bank("Random Bank XYZ") is None


# =========================================================================
# import_pdf (integration with mocked services)
# =========================================================================


class TestImportPdf:

    @pytest.fixture
    def mock_sheets(self):
        sheets = MagicMock()
        sheets.add_transaction.return_value = "abc12345"
        return sheets

    @pytest.fixture
    def mock_categorizer(self):
        cat = MagicMock()
        cat.categorize.return_value = "Groceries"
        return cat

    def _mock_pdf(self):
        """Create a mock pdfplumber PDF with Chase-like content."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = (
            "JPMorgan Chase Bank\n"
            "Statement Date: 01/31/2025\n"
            "01/15 WHOLE FOODS MARKET 45.67\n"
            "01/16 STARBUCKS 6.75\n"
            "01/20 PAYMENT THANK YOU 500.00\n"
        )
        mock_page.extract_tables.return_value = []

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.close = MagicMock()
        return mock_pdf

    @patch("parsers.pdf_parser.pdfplumber.open")
    def test_imports_purchases(self, mock_open, mock_sheets, mock_categorizer):
        mock_open.return_value = self._mock_pdf()

        result = import_pdf(
            "fake.pdf", mock_sheets, mock_categorizer, card="Chase Sapphire"
        )

        assert result["imported"] == 2
        assert result["skipped_duplicates"] == 0
        assert result["errors"] == 0
        assert result["bank"] == "Chase"
        assert mock_sheets.add_transaction.call_count == 2

    @patch("parsers.pdf_parser.pdfplumber.open")
    def test_counts_duplicates(self, mock_open, mock_sheets, mock_categorizer):
        mock_open.return_value = self._mock_pdf()
        mock_sheets.add_transaction.side_effect = [
            "id1",
            DuplicateTransactionError(),
        ]

        result = import_pdf("fake.pdf", mock_sheets, mock_categorizer)

        assert result["imported"] == 1
        assert result["skipped_duplicates"] == 1

    @patch("parsers.pdf_parser.pdfplumber.open")
    def test_uses_statement_source(self, mock_open, mock_sheets, mock_categorizer):
        mock_open.return_value = self._mock_pdf()

        import_pdf(
            "fake.pdf", mock_sheets, mock_categorizer, user="user2", card="Chase Freedom"
        )

        call_kwargs = mock_sheets.add_transaction.call_args_list[0][1]
        assert call_kwargs["source"] == "statement"
        assert call_kwargs["card"] == "Chase Freedom"
        assert call_kwargs["user"] == "user2"

    @patch("parsers.pdf_parser.pdfplumber.open")
    def test_unrecognized_bank_raises(self, mock_open, mock_sheets, mock_categorizer):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Unknown Bank Statement"
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.close = MagicMock()
        mock_open.return_value = mock_pdf

        with pytest.raises(InvalidDataError, match="Unrecognized PDF format"):
            import_pdf("fake.pdf", mock_sheets, mock_categorizer)

    @patch("parsers.pdf_parser.pdfplumber.open")
    def test_empty_pdf_raises(self, mock_open, mock_sheets, mock_categorizer):
        mock_pdf = MagicMock()
        mock_pdf.pages = []
        mock_pdf.close = MagicMock()
        mock_open.return_value = mock_pdf

        with pytest.raises(InvalidDataError, match="no pages"):
            import_pdf("fake.pdf", mock_sheets, mock_categorizer)
