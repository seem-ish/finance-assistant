"""Tests for CSV statement parsers.

Run:
    pytest tests/test_csv_parser.py -v
"""

from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest

from parsers.csv_parser import (
    AmexParser,
    CapitalOneParser,
    ChaseParser,
    DiscoverParser,
    detect_bank,
    import_csv,
)
from services.exceptions import DuplicateTransactionError, InvalidDataError


# =========================================================================
# Chase Parser
# =========================================================================


class TestChaseParser:
    parser = ChaseParser()

    def test_can_parse_chase_columns(self):
        df = pd.DataFrame(
            columns=["Transaction Date", "Post Date", "Description", "Category", "Type", "Amount", "Memo"]
        )
        assert self.parser.can_parse(df) is True

    def test_cannot_parse_amex_columns(self):
        df = pd.DataFrame(columns=["Date", "Description", "Amount"])
        assert self.parser.can_parse(df) is False

    def test_flips_negative_to_positive(self):
        df = pd.DataFrame(
            [
                {
                    "Transaction Date": "01/15/2025",
                    "Post Date": "01/16/2025",
                    "Description": "WHOLE FOODS MARKET",
                    "Category": "Groceries",
                    "Type": "Sale",
                    "Amount": -45.67,
                    "Memo": "",
                },
            ]
        )
        result = self.parser.parse(df)
        assert len(result) == 1
        assert result[0]["amount"] == 45.67
        assert result[0]["description"] == "WHOLE FOODS MARKET"
        assert result[0]["date"] == date(2025, 1, 15)

    def test_skips_payments(self):
        """Positive amounts in Chase = payments/credits → skip."""
        df = pd.DataFrame(
            [
                {
                    "Transaction Date": "01/15/2025",
                    "Post Date": "01/16/2025",
                    "Description": "PAYMENT RECEIVED",
                    "Category": "",
                    "Type": "Payment",
                    "Amount": 500.00,
                    "Memo": "",
                },
            ]
        )
        result = self.parser.parse(df)
        assert len(result) == 0

    def test_multiple_transactions(self):
        df = pd.DataFrame(
            [
                {
                    "Transaction Date": "01/15/2025",
                    "Post Date": "01/16/2025",
                    "Description": "WHOLE FOODS",
                    "Category": "",
                    "Type": "Sale",
                    "Amount": -25.00,
                    "Memo": "",
                },
                {
                    "Transaction Date": "01/16/2025",
                    "Post Date": "01/17/2025",
                    "Description": "CHIPOTLE",
                    "Category": "",
                    "Type": "Sale",
                    "Amount": -12.50,
                    "Memo": "",
                },
                {
                    "Transaction Date": "01/20/2025",
                    "Post Date": "01/21/2025",
                    "Description": "PAYMENT",
                    "Category": "",
                    "Type": "Payment",
                    "Amount": 100.00,
                    "Memo": "",
                },
            ]
        )
        result = self.parser.parse(df)
        assert len(result) == 2  # payment skipped


# =========================================================================
# Amex Parser
# =========================================================================


class TestAmexParser:
    parser = AmexParser()

    def test_can_parse_amex_columns(self):
        df = pd.DataFrame(columns=["Date", "Description", "Amount"])
        assert self.parser.can_parse(df) is True

    def test_cannot_parse_chase_columns(self):
        df = pd.DataFrame(
            columns=["Transaction Date", "Post Date", "Description", "Amount"]
        )
        assert self.parser.can_parse(df) is False

    def test_positive_is_purchase(self):
        df = pd.DataFrame(
            [{"Date": "01/15/2025", "Description": "STARBUCKS", "Amount": 5.75}]
        )
        result = self.parser.parse(df)
        assert len(result) == 1
        assert result[0]["amount"] == 5.75
        assert result[0]["date"] == date(2025, 1, 15)

    def test_skips_negative_credits(self):
        df = pd.DataFrame(
            [{"Date": "01/15/2025", "Description": "CREDIT", "Amount": -50.00}]
        )
        result = self.parser.parse(df)
        assert len(result) == 0


# =========================================================================
# Discover Parser
# =========================================================================


class TestDiscoverParser:
    parser = DiscoverParser()

    def test_can_parse_discover_columns(self):
        df = pd.DataFrame(
            columns=["Trans. Date", "Post Date", "Description", "Amount", "Category"]
        )
        assert self.parser.can_parse(df) is True

    def test_cannot_parse_chase_columns(self):
        df = pd.DataFrame(
            columns=["Transaction Date", "Post Date", "Description", "Amount"]
        )
        assert self.parser.can_parse(df) is False

    def test_parses_purchase(self):
        df = pd.DataFrame(
            [
                {
                    "Trans. Date": "01/15/2025",
                    "Post Date": "01/16/2025",
                    "Description": "TARGET",
                    "Amount": 33.99,
                    "Category": "Merchandise",
                }
            ]
        )
        result = self.parser.parse(df)
        assert len(result) == 1
        assert result[0]["amount"] == 33.99
        assert result[0]["description"] == "TARGET"

    def test_skips_negative_credits(self):
        df = pd.DataFrame(
            [
                {
                    "Trans. Date": "01/15/2025",
                    "Post Date": "01/16/2025",
                    "Description": "CASHBACK BONUS",
                    "Amount": -10.00,
                    "Category": "",
                }
            ]
        )
        result = self.parser.parse(df)
        assert len(result) == 0


# =========================================================================
# Capital One Parser
# =========================================================================


class TestCapitalOneParser:
    parser = CapitalOneParser()

    def test_can_parse_capital_one_columns(self):
        df = pd.DataFrame(
            columns=[
                "Transaction Date",
                "Posted Date",
                "Card No.",
                "Description",
                "Category",
                "Debit",
                "Credit",
            ]
        )
        assert self.parser.can_parse(df) is True

    def test_cannot_parse_chase_columns(self):
        """Chase has Transaction Date but no Debit/Credit columns."""
        df = pd.DataFrame(
            columns=["Transaction Date", "Post Date", "Description", "Amount"]
        )
        assert self.parser.can_parse(df) is False

    def test_debit_is_purchase(self):
        df = pd.DataFrame(
            [
                {
                    "Transaction Date": "2025-01-15",
                    "Posted Date": "2025-01-16",
                    "Card No.": "1234",
                    "Description": "AMAZON",
                    "Category": "Shopping",
                    "Debit": 89.99,
                    "Credit": "",
                }
            ]
        )
        result = self.parser.parse(df)
        assert len(result) == 1
        assert result[0]["amount"] == 89.99
        assert result[0]["description"] == "AMAZON"

    def test_skips_credit_rows(self):
        """Rows with no debit = payments/credits → skip."""
        df = pd.DataFrame(
            [
                {
                    "Transaction Date": "2025-01-15",
                    "Posted Date": "2025-01-16",
                    "Card No.": "1234",
                    "Description": "PAYMENT",
                    "Category": "",
                    "Debit": "",
                    "Credit": 500.00,
                }
            ]
        )
        result = self.parser.parse(df)
        assert len(result) == 0


# =========================================================================
# Auto-detection
# =========================================================================


class TestDetectBank:

    def test_detects_chase(self):
        df = pd.DataFrame(
            columns=["Transaction Date", "Post Date", "Description", "Category", "Type", "Amount", "Memo"]
        )
        parser = detect_bank(df)
        assert parser is not None
        assert parser.bank_name == "Chase"

    def test_detects_amex(self):
        df = pd.DataFrame(columns=["Date", "Description", "Amount"])
        parser = detect_bank(df)
        assert parser is not None
        assert parser.bank_name == "Amex"

    def test_detects_discover(self):
        df = pd.DataFrame(
            columns=["Trans. Date", "Post Date", "Description", "Amount", "Category"]
        )
        parser = detect_bank(df)
        assert parser is not None
        assert parser.bank_name == "Discover"

    def test_detects_capital_one(self):
        df = pd.DataFrame(
            columns=[
                "Transaction Date",
                "Posted Date",
                "Card No.",
                "Description",
                "Category",
                "Debit",
                "Credit",
            ]
        )
        parser = detect_bank(df)
        assert parser is not None
        assert parser.bank_name == "Capital One"

    def test_unknown_format_returns_none(self):
        df = pd.DataFrame(columns=["Foo", "Bar", "Baz"])
        assert detect_bank(df) is None


# =========================================================================
# import_csv (integration with mocked services)
# =========================================================================


class TestImportCsv:

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

    def _write_chase_csv(self, tmp_path):
        csv_content = (
            "Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
            "01/15/2025,01/16/2025,WHOLE FOODS,Groceries,Sale,-25.00,\n"
            "01/16/2025,01/17/2025,CHIPOTLE,Food,Sale,-12.50,\n"
            "01/20/2025,01/21/2025,PAYMENT,,Payment,100.00,\n"
        )
        csv_file = tmp_path / "chase.csv"
        csv_file.write_text(csv_content)
        return str(csv_file)

    def test_imports_purchases_skips_payments(self, tmp_path, mock_sheets, mock_categorizer):
        filepath = self._write_chase_csv(tmp_path)
        result = import_csv(filepath, mock_sheets, mock_categorizer, card="Chase Sapphire")

        assert result["imported"] == 2
        assert result["skipped_duplicates"] == 0
        assert result["errors"] == 0
        assert result["bank"] == "Chase"
        assert mock_sheets.add_transaction.call_count == 2

    def test_counts_duplicates(self, tmp_path, mock_sheets, mock_categorizer):
        mock_sheets.add_transaction.side_effect = [
            "id1",  # first succeeds
            DuplicateTransactionError(),  # second is duplicate
        ]
        filepath = self._write_chase_csv(tmp_path)
        result = import_csv(filepath, mock_sheets, mock_categorizer)

        assert result["imported"] == 1
        assert result["skipped_duplicates"] == 1

    def test_uses_correct_source_and_card(self, tmp_path, mock_sheets, mock_categorizer):
        filepath = self._write_chase_csv(tmp_path)
        import_csv(filepath, mock_sheets, mock_categorizer, user="user2", card="Chase Freedom")

        call_kwargs = mock_sheets.add_transaction.call_args_list[0][1]
        assert call_kwargs["source"] == "csv"
        assert call_kwargs["card"] == "Chase Freedom"
        assert call_kwargs["user"] == "user2"

    def test_invalid_file_raises(self, mock_sheets, mock_categorizer):
        with pytest.raises(InvalidDataError, match="Could not read"):
            import_csv("/nonexistent/file.csv", mock_sheets, mock_categorizer)

    def test_unrecognized_format_raises(self, tmp_path, mock_sheets, mock_categorizer):
        csv_file = tmp_path / "unknown.csv"
        csv_file.write_text("Foo,Bar,Baz\n1,2,3\n")
        with pytest.raises(InvalidDataError, match="Unrecognized CSV format"):
            import_csv(str(csv_file), mock_sheets, mock_categorizer)

    def test_empty_csv_raises(self, tmp_path, mock_sheets, mock_categorizer):
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("")
        with pytest.raises(InvalidDataError):
            import_csv(str(csv_file), mock_sheets, mock_categorizer)

    def test_categorizer_called_for_each_transaction(self, tmp_path, mock_sheets, mock_categorizer):
        filepath = self._write_chase_csv(tmp_path)
        import_csv(filepath, mock_sheets, mock_categorizer)

        assert mock_categorizer.categorize.call_count == 2
        descriptions = [
            call[0][0] for call in mock_categorizer.categorize.call_args_list
        ]
        assert "WHOLE FOODS" in descriptions
        assert "CHIPOTLE" in descriptions
