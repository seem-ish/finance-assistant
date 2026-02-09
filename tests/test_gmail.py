"""Tests for Gmail integration.

Run:
    pytest tests/test_gmail.py -v
"""

import base64
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from services.gmail import (
    _get_attachments,
    _get_email_body,
    _get_header,
    parse_purchase_email,
    sync_gmail,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_email(
    subject: str,
    sender: str,
    body: str,
    msg_id: str = "abc123",
    date_str: str = "Sat, 8 Feb 2025 10:30:00 -0500",
    attachments: list | None = None,
):
    """Build a mock Gmail email data structure."""
    body_encoded = base64.urlsafe_b64encode(body.encode()).decode()
    parts = [
        {
            "mimeType": "text/plain",
            "body": {"data": body_encoded},
        }
    ]

    if attachments:
        for att in attachments:
            parts.append(
                {
                    "filename": att["filename"],
                    "mimeType": att.get("mime_type", "application/pdf"),
                    "body": {"attachmentId": att.get("attachment_id", "att123")},
                }
            )

    return {
        "id": msg_id,
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
                {"name": "Date", "value": date_str},
            ],
            "parts": parts,
        },
    }


# =========================================================================
# Header / body extraction helpers
# =========================================================================


class TestGetHeader:

    def test_finds_header(self):
        headers = [{"name": "Subject", "value": "Test"}, {"name": "From", "value": "a@b.com"}]
        assert _get_header(headers, "Subject") == "Test"

    def test_missing_header_returns_empty(self):
        assert _get_header([], "Subject") == ""


class TestGetEmailBody:

    def test_extracts_plain_text(self):
        body_text = "Hello world"
        encoded = base64.urlsafe_b64encode(body_text.encode()).decode()
        payload = {
            "parts": [{"mimeType": "text/plain", "body": {"data": encoded}}]
        }
        assert _get_email_body(payload) == "Hello world"

    def test_single_part_body(self):
        body_text = "Direct body"
        encoded = base64.urlsafe_b64encode(body_text.encode()).decode()
        payload = {"body": {"data": encoded}}
        assert _get_email_body(payload) == "Direct body"


class TestGetAttachments:

    def test_extracts_attachments(self):
        payload = {
            "parts": [
                {
                    "filename": "statement.pdf",
                    "mimeType": "application/pdf",
                    "body": {"attachmentId": "att123"},
                },
                {
                    "mimeType": "text/plain",
                    "body": {"data": "dGVzdA=="},
                },
            ]
        }
        atts = _get_attachments(payload)
        assert len(atts) == 1
        assert atts[0]["filename"] == "statement.pdf"

    def test_no_attachments(self):
        payload = {"parts": [{"mimeType": "text/plain", "body": {"data": "dGVzdA=="}}]}
        assert _get_attachments(payload) == []


# =========================================================================
# Purchase email parsing
# =========================================================================


class TestParsePurchaseEmail:

    def test_amazon_receipt(self):
        email = _make_email(
            subject="Your Amazon.com order confirmation",
            sender="auto-confirm@amazon.com",
            body="Your order total: $47.99\nShipping to: Home",
        )
        result = parse_purchase_email(email)
        assert result is not None
        assert result["amount"] == 47.99
        assert result["description"] == "Amazon"
        assert result["date"] == date(2025, 2, 8)

    def test_generic_receipt(self):
        email = _make_email(
            subject="Payment receipt from Target",
            sender="noreply@target.com",
            body="You paid $32.50 at Target Store #1234",
        )
        result = parse_purchase_email(email)
        assert result is not None
        assert result["amount"] == 32.50

    def test_non_purchase_email_returns_none(self):
        email = _make_email(
            subject="Weekly newsletter",
            sender="news@example.com",
            body="Here are this week's top stories",
        )
        result = parse_purchase_email(email)
        assert result is None

    def test_no_amount_returns_none(self):
        email = _make_email(
            subject="Your order confirmation",
            sender="shop@example.com",
            body="Thank you for your order. We'll send details soon.",
        )
        result = parse_purchase_email(email)
        assert result is None

    def test_paypal_receipt(self):
        email = _make_email(
            subject="Receipt for your payment to Store",
            sender="service@paypal.com",
            body="You sent a payment of $25.00 USD",
        )
        result = parse_purchase_email(email)
        assert result is not None
        assert result["amount"] == 25.00
        assert result["description"] == "PayPal"

    def test_empty_email_returns_none(self):
        assert parse_purchase_email(None) is None
        assert parse_purchase_email({}) is None


# =========================================================================
# sync_gmail
# =========================================================================


class TestSyncGmail:

    def test_imports_receipts(self):
        mock_gmail = MagicMock()
        mock_gmail.get_recent_emails.side_effect = [
            # First call: receipt emails
            [{"id": "msg1"}],
            # Second call: statement emails
            [],
        ]
        mock_gmail.get_email.return_value = _make_email(
            subject="Your order confirmation",
            sender="auto-confirm@amazon.com",
            body="Order total: $47.99",
            msg_id="msg1",
        )

        mock_sheets = MagicMock()
        mock_sheets.add_transaction.return_value = "txn123"

        mock_categorizer = MagicMock()
        mock_categorizer.categorize.return_value = "Shopping"

        results = sync_gmail(mock_gmail, mock_sheets, mock_categorizer)
        assert results["receipts_added"] == 1
        mock_sheets.add_transaction.assert_called_once()
        call_kwargs = mock_sheets.add_transaction.call_args[1]
        assert call_kwargs["source"] == "gmail"
        assert call_kwargs["amount"] == 47.99

    def test_no_emails_returns_zeros(self):
        mock_gmail = MagicMock()
        mock_gmail.get_recent_emails.return_value = []

        mock_sheets = MagicMock()
        mock_categorizer = MagicMock()

        results = sync_gmail(mock_gmail, mock_sheets, mock_categorizer)
        assert results["receipts_added"] == 0
        assert results["statements_imported"] == 0
        assert results["skipped"] == 0

    def test_skips_duplicates(self):
        from services.exceptions import DuplicateTransactionError

        mock_gmail = MagicMock()
        mock_gmail.get_recent_emails.side_effect = [
            [{"id": "msg1"}],
            [],
        ]
        mock_gmail.get_email.return_value = _make_email(
            subject="Receipt for purchase",
            sender="auto-confirm@amazon.com",
            body="Total: $25.00",
            msg_id="msg1",
        )

        mock_sheets = MagicMock()
        mock_sheets.add_transaction.side_effect = DuplicateTransactionError()

        mock_categorizer = MagicMock()
        mock_categorizer.categorize.return_value = "Shopping"

        results = sync_gmail(mock_gmail, mock_sheets, mock_categorizer)
        assert results["receipts_added"] == 0
        assert results["skipped"] == 1
