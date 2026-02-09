"""Google Calendar integration for bill reminders and payment tracking.

Uses OAuth2 user authentication to create calendar events for:
1. Bill due date reminders (all-day events with notifications)
2. Payment tracking (logged when bills are paid)

Setup:
    python -m scripts.setup_calendar
"""

import logging
import os
from datetime import date, timedelta

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from services.bill_tracker import get_next_due_date

logger = logging.getLogger(__name__)

CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


# ---------------------------------------------------------------------------
# Calendar Service
# ---------------------------------------------------------------------------


class CalendarService:
    """Connects to Google Calendar API using OAuth2 user credentials."""

    def __init__(
        self,
        credentials_file: str,
        token_file: str,
        calendar_id: str = "primary",
    ):
        self.credentials_file = credentials_file
        self.token_file = token_file
        self.calendar_id = calendar_id
        self._service = None

    def authenticate(self) -> bool:
        """Authenticate with Google Calendar. Returns True if successful."""
        creds = None

        if os.path.exists(self.token_file):
            creds = Credentials.from_authorized_user_file(
                self.token_file, CALENDAR_SCOPES
            )

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                logger.error("Calendar token refresh failed: %s", e)
                creds = None

        if not creds or not creds.valid:
            if not os.path.exists(self.credentials_file):
                logger.error(
                    "OAuth2 credentials file not found: %s. "
                    "Run 'python -m scripts.setup_calendar' first.",
                    self.credentials_file,
                )
                return False

            flow = InstalledAppFlow.from_client_secrets_file(
                self.credentials_file, CALENDAR_SCOPES
            )
            creds = flow.run_local_server(port=0)

            with open(self.token_file, "w") as f:
                f.write(creds.to_json())

        self._service = build("calendar", "v3", credentials=creds)
        return True

    def create_bill_event(
        self,
        name: str,
        amount: float,
        due_date: date,
        category: str = "",
        auto_pay: bool = False,
        frequency: str = "monthly",
    ) -> str | None:
        """Create an all-day calendar event for a bill due date.

        Returns the event ID, or None on failure.
        """
        if not self._service:
            return None

        auto_pay_str = "✅ Auto-pay" if auto_pay else "⚠️ Manual payment"
        summary = f"💳 {name} — ${amount:,.2f} due"
        description = (
            f"Bill: {name}\n"
            f"Amount: ${amount:,.2f}\n"
            f"Category: {category}\n"
            f"Frequency: {frequency}\n"
            f"{auto_pay_str}"
        )

        event = {
            "summary": summary,
            "description": description,
            "start": {"date": due_date.isoformat()},
            "end": {"date": (due_date + timedelta(days=1)).isoformat()},
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 1440},  # 1 day before
                ],
            },
            "colorId": "11" if auto_pay else "6",  # Red for manual, orange for auto
        }

        try:
            result = (
                self._service.events()
                .insert(calendarId=self.calendar_id, body=event)
                .execute()
            )
            return result.get("id")
        except Exception as e:
            logger.error("Failed to create bill event: %s", e)
            return None

    def log_payment_event(
        self,
        name: str,
        amount: float,
        payment_date: date,
        category: str = "",
    ) -> str | None:
        """Create an all-day event to record a payment.

        Returns the event ID, or None on failure.
        """
        if not self._service:
            return None

        summary = f"✅ {name} — ${amount:,.2f} paid"
        description = f"Payment: {name}\nAmount: ${amount:,.2f}\nCategory: {category}"

        event = {
            "summary": summary,
            "description": description,
            "start": {"date": payment_date.isoformat()},
            "end": {"date": (payment_date + timedelta(days=1)).isoformat()},
            "colorId": "10",  # Green
        }

        try:
            result = (
                self._service.events()
                .insert(calendarId=self.calendar_id, body=event)
                .execute()
            )
            return result.get("id")
        except Exception as e:
            logger.error("Failed to create payment event: %s", e)
            return None

    def list_bill_events(
        self, start_date: date, end_date: date
    ) -> list[dict]:
        """List existing bill events in a date range."""
        if not self._service:
            return []

        try:
            result = (
                self._service.events()
                .list(
                    calendarId=self.calendar_id,
                    timeMin=f"{start_date.isoformat()}T00:00:00Z",
                    timeMax=f"{end_date.isoformat()}T23:59:59Z",
                    q="💳",  # Search for bill events by emoji prefix
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            return result.get("items", [])
        except Exception as e:
            logger.error("Failed to list calendar events: %s", e)
            return []

    def delete_event(self, event_id: str) -> bool:
        """Delete a calendar event by ID."""
        if not self._service:
            return False

        try:
            self._service.events().delete(
                calendarId=self.calendar_id, eventId=event_id
            ).execute()
            return True
        except Exception as e:
            logger.error("Failed to delete event %s: %s", event_id, e)
            return False


# ---------------------------------------------------------------------------
# Sync function
# ---------------------------------------------------------------------------


def sync_bills_to_calendar(
    calendar: CalendarService,
    sheets,
    user: str = "user1",
    days_ahead: int = 30,
) -> dict:
    """Sync all active bills to Google Calendar.

    Creates bill reminder events for the next N days. Skips bills
    that already have a matching event (dedup by summary + date).

    Returns dict with created, existing, errors counts.
    """
    results = {"created": 0, "existing": 0, "errors": 0}

    bills_df = sheets.get_bills(active_only=True, user=user)
    if bills_df.empty:
        return results

    today = date.today()
    end_date = today + timedelta(days=days_ahead)

    # Get existing bill events to avoid duplicates
    existing_events = calendar.list_bill_events(today, end_date)
    existing_summaries = set()
    for ev in existing_events:
        summary = ev.get("summary", "")
        start = ev.get("start", {}).get("date", "")
        existing_summaries.add(f"{summary}|{start}")

    for _, bill in bills_df.iterrows():
        try:
            due_date = get_next_due_date(int(bill["due_day"]))

            if due_date > end_date:
                continue

            amount = float(bill["amount"])
            name = bill["name"]
            summary = f"💳 {name} — ${amount:,.2f} due"
            key = f"{summary}|{due_date.isoformat()}"

            if key in existing_summaries:
                results["existing"] += 1
                continue

            event_id = calendar.create_bill_event(
                name=name,
                amount=amount,
                due_date=due_date,
                category=bill.get("category", ""),
                auto_pay=bool(bill.get("auto_pay", False)),
                frequency=bill.get("frequency", "monthly"),
            )

            if event_id:
                results["created"] += 1
            else:
                results["errors"] += 1

        except Exception as e:
            logger.error("Error syncing bill %s: %s", bill.get("name", "?"), e)
            results["errors"] += 1

    return results
