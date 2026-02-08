"""Bill tracking service — due date calculations and formatting.

Provides helper functions for bill management:
- Calculate next due date for a recurring bill
- Find upcoming bills within N days
- Format bill lists and reminders for display
"""

import calendar
from datetime import date, timedelta

import pandas as pd

from services.sheets import GoogleSheetsService


def get_next_due_date(due_day: int, reference_date: date | None = None) -> date:
    """Calculate the next occurrence of a bill's due day.

    If the due_day hasn't passed yet this month, returns this month's date.
    If it has passed, returns next month's date.
    Handles months with fewer days (e.g., due_day=31 in February → Feb 28).

    Args:
        due_day: Day of month the bill is due (1-31).
        reference_date: Date to calculate from (defaults to today).

    Returns:
        The next due date.
    """
    today = reference_date or date.today()

    # Clamp due_day to the last day of this month
    last_day_this_month = calendar.monthrange(today.year, today.month)[1]
    clamped_day = min(due_day, last_day_this_month)

    this_month_due = date(today.year, today.month, clamped_day)

    if this_month_due >= today:
        return this_month_due

    # Move to next month
    if today.month == 12:
        next_year, next_month = today.year + 1, 1
    else:
        next_year, next_month = today.year, today.month + 1

    last_day_next_month = calendar.monthrange(next_year, next_month)[1]
    clamped_day = min(due_day, last_day_next_month)
    return date(next_year, next_month, clamped_day)


def get_upcoming_bills(
    sheets: GoogleSheetsService,
    user: str | None = None,
    days_ahead: int = 7,
    reference_date: date | None = None,
) -> list[dict]:
    """Get bills due within the next N days.

    Returns a list of dicts with bill info + calculated due_date and days_until.
    Sorted by days_until (soonest first).
    """
    today = reference_date or date.today()
    cutoff = today + timedelta(days=days_ahead)

    df = sheets.get_bills(active_only=True, user=user)
    if df.empty:
        return []

    upcoming = []
    for _, row in df.iterrows():
        due_day = int(row["due_day"])
        next_due = get_next_due_date(due_day, reference_date=today)

        if today <= next_due <= cutoff:
            days_until = (next_due - today).days
            upcoming.append(
                {
                    "name": row["name"],
                    "amount": float(row["amount"]),
                    "due_date": next_due,
                    "days_until": days_until,
                    "category": row["category"],
                    "auto_pay": row.get("auto_pay", False),
                    "frequency": row.get("frequency", "monthly"),
                }
            )

    upcoming.sort(key=lambda b: b["days_until"])
    return upcoming


def format_bills_list(df: pd.DataFrame, currency: str = "$") -> str:
    """Format a bills DataFrame into a readable message.

    Shows each bill with name, amount, due day, frequency, and auto-pay status.
    Includes total monthly amount at the end.
    """
    if df.empty:
        return "No bills set up yet.\n\nAdd one with: /addbill <name> <amount> <due_day>"

    lines = ["📋 *Your Bills*\n"]
    total = 0.0

    for _, row in df.iterrows():
        name = row["name"]
        amount = float(row["amount"])
        due_day = int(row["due_day"])
        frequency = row.get("frequency", "monthly")
        auto_pay = row.get("auto_pay", False)

        auto_tag = " ✅ auto-pay" if auto_pay else ""
        lines.append(
            f"  • {name} — {currency}{amount:,.2f} "
            f"(due day {due_day}, {frequency}{auto_tag})"
        )
        total += amount

    lines.append(f"\n💰 Total monthly: {currency}{total:,.2f}")
    return "\n".join(lines)


def format_upcoming_reminder(bills: list[dict], currency: str = "$") -> str:
    """Format upcoming bills into a reminder message.

    Shows each bill with due date and days until due.
    """
    if not bills:
        return "✅ No bills due in the next 7 days!"

    lines = ["⏰ *Bills Due Soon*\n"]
    for bill in bills:
        name = bill["name"]
        amount = bill["amount"]
        due_date = bill["due_date"]
        days = bill["days_until"]
        auto_pay = bill.get("auto_pay", False)

        if days == 0:
            when = "📍 TODAY"
        elif days == 1:
            when = "tomorrow"
        else:
            when = f"in {days} days"

        auto_tag = " (auto-pay ✅)" if auto_pay else ""
        lines.append(
            f"  • {name} — {currency}{amount:,.2f} "
            f"(due {due_date.strftime('%b %d')}, {when}{auto_tag})"
        )

    return "\n".join(lines)
