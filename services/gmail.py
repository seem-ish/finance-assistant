"""Gmail integration for auto-importing purchase receipts and statements.

Uses OAuth2 user authentication (read-only access) to scan Gmail for:
1. Purchase confirmation emails → extract amount/merchant → add as transactions
2. Forwarded credit card statements (PDF/CSV) → import via existing parsers

Setup:
    python -m scripts.setup_gmail
"""

import base64
import logging
import os
import re
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from parsers.csv_parser import import_csv
from parsers.pdf_parser import import_pdf
from services.exceptions import DuplicateTransactionError

logger = logging.getLogger(__name__)

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


# ---------------------------------------------------------------------------
# Gmail Service
# ---------------------------------------------------------------------------


class GmailService:
    """Connects to Gmail API using OAuth2 user credentials."""

    def __init__(self, credentials_file: str, token_file: str):
        self.credentials_file = credentials_file
        self.token_file = token_file
        self._service = None

    def authenticate(self) -> bool:
        """Authenticate with Gmail. Returns True if successful."""
        creds = None

        # Load existing token
        if os.path.exists(self.token_file):
            creds = Credentials.from_authorized_user_file(self.token_file, GMAIL_SCOPES)

        # Refresh or run new auth flow
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                logger.error("Token refresh failed: %s", e)
                creds = None

        if not creds or not creds.valid:
            if not os.path.exists(self.credentials_file):
                logger.error(
                    "OAuth2 credentials file not found: %s. "
                    "Run 'python -m scripts.setup_gmail' first.",
                    self.credentials_file,
                )
                return False

            flow = InstalledAppFlow.from_client_secrets_file(
                self.credentials_file, GMAIL_SCOPES
            )
            creds = flow.run_local_server(port=0)

            # Save token for future runs
            with open(self.token_file, "w") as f:
                f.write(creds.to_json())

        self._service = build("gmail", "v1", credentials=creds)
        return True

    def get_recent_emails(self, query: str, max_results: int = 50) -> list[dict]:
        """Search Gmail and return list of message metadata."""
        if not self._service:
            return []

        try:
            result = (
                self._service.users()
                .messages()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )
            return result.get("messages", [])
        except Exception as e:
            logger.error("Gmail search failed: %s", e)
            return []

    def get_email(self, msg_id: str) -> Optional[dict]:
        """Fetch full email by message ID."""
        if not self._service:
            return None

        try:
            return (
                self._service.users()
                .messages()
                .get(userId="me", id=msg_id, format="full")
                .execute()
            )
        except Exception as e:
            logger.error("Failed to fetch email %s: %s", msg_id, e)
            return None

    def download_attachment(
        self, msg_id: str, attachment_id: str, save_path: str
    ) -> bool:
        """Download an email attachment and save to disk."""
        if not self._service:
            return False

        try:
            attachment = (
                self._service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=msg_id, id=attachment_id)
                .execute()
            )
            data = base64.urlsafe_b64decode(attachment["data"])
            with open(save_path, "wb") as f:
                f.write(data)
            return True
        except Exception as e:
            logger.error("Failed to download attachment: %s", e)
            return False


# ---------------------------------------------------------------------------
# Email parsing helpers
# ---------------------------------------------------------------------------


def _get_header(headers: list[dict], name: str) -> str:
    """Extract a header value from email headers list."""
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _get_email_body(payload: dict) -> str:
    """Extract plain text body from email payload."""
    # Simple single-part message
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode(
            "utf-8", errors="replace"
        )

    # Multipart message — find text/plain
    for part in payload.get("parts", []):
        mime = part.get("mimeType", "")
        if mime == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode(
                "utf-8", errors="replace"
            )
        # Nested multipart
        if mime.startswith("multipart/"):
            result = _get_email_body(part)
            if result:
                return result

    return ""


def _get_attachments(payload: dict) -> list[dict]:
    """Extract attachment info from email payload."""
    attachments = []
    for part in payload.get("parts", []):
        filename = part.get("filename", "")
        if filename and part.get("body", {}).get("attachmentId"):
            attachments.append(
                {
                    "filename": filename,
                    "attachment_id": part["body"]["attachmentId"],
                    "mime_type": part.get("mimeType", ""),
                }
            )
        # Check nested parts
        if part.get("parts"):
            attachments.extend(_get_attachments(part))
    return attachments


# ---------------------------------------------------------------------------
# Purchase receipt parsing
# ---------------------------------------------------------------------------

# Patterns to extract dollar amounts from email bodies
AMOUNT_PATTERNS = [
    r"(?:total|amount|charged|paid|payment)[:\s]*\$?([\d,]+\.?\d{0,2})",
    r"\$\s*([\d,]+\.\d{2})",
    r"USD\s*([\d,]+\.\d{2})",
]

# Known purchase email senders and their merchant names
KNOWN_SENDERS = {
    "auto-confirm@amazon.com": "Amazon",
    "digital-no-reply@amazon.com": "Amazon",
    "ship-confirm@amazon.com": "Amazon",
    "no-reply@alertsp.chase.com": "Chase",
    "service@paypal.com": "PayPal",
    "venmo@venmo.com": "Venmo",
    "noreply@uber.com": "Uber",
    "no-reply@doordash.com": "DoorDash",
    "noreply@grubhub.com": "Grubhub",
    "receipts@square.com": "Square",
    "no_reply@email.apple.com": "Apple",
}


def parse_purchase_email(email_data: dict) -> Optional[dict]:
    """Try to extract a purchase transaction from an email.

    Returns dict with {amount, description, date, message_id} or None.
    """
    if not email_data or "payload" not in email_data:
        return None

    headers = email_data["payload"].get("headers", [])
    subject = _get_header(headers, "Subject")
    sender = _get_header(headers, "From")
    date_str = _get_header(headers, "Date")
    body = _get_email_body(email_data["payload"])
    msg_id = email_data.get("id", "")

    # Check if this looks like a purchase email
    purchase_keywords = [
        "order confirmation",
        "receipt",
        "payment",
        "purchase",
        "your order",
        "transaction",
        "charged",
    ]

    subject_lower = subject.lower()
    is_purchase = any(kw in subject_lower for kw in purchase_keywords)

    if not is_purchase:
        return None

    # Try to extract amount
    amount = None
    search_text = f"{subject} {body}"
    for pattern in AMOUNT_PATTERNS:
        match = re.search(pattern, search_text, re.IGNORECASE)
        if match:
            try:
                amount = float(match.group(1).replace(",", ""))
                if amount > 0:
                    break
            except ValueError:
                continue

    if not amount or amount <= 0:
        return None

    # Determine merchant/description
    sender_email = re.search(r"<?([\w.+-]+@[\w.-]+)>?", sender)
    sender_addr = sender_email.group(1).lower() if sender_email else sender.lower()

    description = KNOWN_SENDERS.get(sender_addr, "")
    if not description:
        # Try to extract merchant from subject
        # Remove common prefixes
        desc = re.sub(
            r"(?i)(your |order |receipt |confirmation |from |for )", "", subject
        )
        description = desc.strip()[:80]  # Cap length

    if not description:
        description = f"Email purchase ({sender_addr})"

    # Parse date
    transaction_date = None
    if date_str:
        try:
            # Email dates: "Sat, 8 Feb 2025 10:30:00 -0500"
            from email.utils import parsedate_to_datetime

            dt = parsedate_to_datetime(date_str)
            transaction_date = dt.date()
        except Exception:
            transaction_date = date.today()

    return {
        "amount": amount,
        "description": description,
        "date": transaction_date or date.today(),
        "message_id": msg_id,
    }


# ---------------------------------------------------------------------------
# Main sync function
# ---------------------------------------------------------------------------


def sync_gmail(
    gmail: GmailService,
    sheets,
    categorizer,
    user: str = "user1",
    days_back: int = 1,
) -> dict:
    """Scan Gmail for purchase receipts and statement attachments.

    Args:
        gmail: Authenticated GmailService instance
        sheets: GoogleSheetsService instance
        categorizer: Categorizer instance
        user: User key ("user1" or "user2")
        days_back: How many days back to scan (1 for scheduled, 7 for manual)

    Returns:
        dict with receipts_added, statements_imported, skipped, errors
    """
    results = {
        "receipts_added": 0,
        "statements_imported": 0,
        "skipped": 0,
        "errors": 0,
    }

    # --- 1. Scan for purchase confirmation emails ---
    receipt_query = (
        f'subject:(receipt OR "order confirmation" OR "payment received" '
        f'OR "purchase" OR "your order") '
        f"newer_than:{days_back}d"
    )
    receipt_emails = gmail.get_recent_emails(receipt_query)
    logger.info("Found %d potential receipt emails", len(receipt_emails))

    for msg_meta in receipt_emails:
        try:
            email_data = gmail.get_email(msg_meta["id"])
            if not email_data:
                continue

            parsed = parse_purchase_email(email_data)
            if not parsed:
                continue

            category = categorizer.categorize(parsed["description"])
            # Include message_id in description for dedup
            desc = f"{parsed['description']} [gmail:{parsed['message_id'][:8]}]"

            try:
                sheets.add_transaction(
                    amount=parsed["amount"],
                    category=category,
                    description=desc,
                    user=user,
                    transaction_date=parsed["date"],
                    source="gmail",
                )
                results["receipts_added"] += 1
            except DuplicateTransactionError:
                results["skipped"] += 1

        except Exception as e:
            logger.error("Error processing receipt email: %s", e)
            results["errors"] += 1

    # --- 2. Scan for statement attachments (PDF/CSV) ---
    statement_query = (
        f"has:attachment filename:(pdf OR csv) "
        f'subject:(statement OR "account summary" OR "billing statement") '
        f"newer_than:{days_back}d"
    )
    statement_emails = gmail.get_recent_emails(statement_query)
    logger.info("Found %d potential statement emails", len(statement_emails))

    for msg_meta in statement_emails:
        try:
            email_data = gmail.get_email(msg_meta["id"])
            if not email_data:
                continue

            attachments = _get_attachments(email_data.get("payload", {}))

            for att in attachments:
                filename = att["filename"].lower()
                if not (filename.endswith(".pdf") or filename.endswith(".csv")):
                    continue

                # Download to temp file
                with tempfile.NamedTemporaryFile(
                    suffix=Path(filename).suffix, delete=False
                ) as tmp:
                    tmp_path = tmp.name

                try:
                    downloaded = gmail.download_attachment(
                        msg_meta["id"], att["attachment_id"], tmp_path
                    )
                    if not downloaded:
                        continue

                    # Import using existing parsers
                    if filename.endswith(".pdf"):
                        import_result = import_pdf(
                            tmp_path, sheets, categorizer, user=user
                        )
                    else:
                        import_result = import_csv(
                            tmp_path, sheets, categorizer, user=user
                        )

                    results["statements_imported"] += import_result.get("imported", 0)
                    results["skipped"] += import_result.get("skipped_duplicates", 0)
                    results["errors"] += import_result.get("errors", 0)

                finally:
                    # Clean up temp file
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)

        except Exception as e:
            logger.error("Error processing statement email: %s", e)
            results["errors"] += 1

    return results
