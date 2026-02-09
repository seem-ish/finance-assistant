"""Budget tracking service — spending vs limits comparison.

Compares actual spending per category against monthly budget limits.
Provides formatted status with visual progress bars and alerts.
"""

from datetime import date

from services.sheets import GoogleSheetsService

BAR_LENGTH = 20  # characters for progress bar


def _progress_bar(percent: float) -> str:
    """Create a text-based progress bar.

    Args:
        percent: 0-100+ percentage filled.

    Returns:
        String like '[██████████░░░░░░░░░░]'
    """
    filled = min(int(percent / 100 * BAR_LENGTH), BAR_LENGTH)
    empty = BAR_LENGTH - filled
    return f"[{'█' * filled}{'░' * empty}]"


def get_budget_status(
    sheets: GoogleSheetsService,
    user: str,
    reference_date: date | None = None,
) -> list[dict]:
    """Get budget vs actual spending for each budgeted category.

    Args:
        sheets: Initialized GoogleSheetsService.
        user: "user1" or "user2".
        reference_date: Date to calculate from (defaults to today).

    Returns:
        List of dicts: {category, limit, spent, remaining, percent_used}
        Sorted by percent_used descending (most over-budget first).
    """
    today = reference_date or date.today()
    month_start = date(today.year, today.month, 1)

    # Get budgets for this user
    budgets_df = sheets.get_budgets(user=user)
    if budgets_df.empty:
        return []

    # Get this month's transactions
    txn_df = sheets.get_transactions(
        start_date=month_start, end_date=today, user=user
    )

    # Sum spending per category
    spending = {}
    if not txn_df.empty:
        spending = txn_df.groupby("category")["amount"].sum().to_dict()

    # Build status for each budget
    statuses = []
    for _, row in budgets_df.iterrows():
        category = row["category"]
        limit = float(row["monthly_limit"])
        spent = spending.get(category, 0.0)
        remaining = limit - spent
        percent = (spent / limit * 100) if limit > 0 else 0

        statuses.append(
            {
                "category": category,
                "limit": limit,
                "spent": spent,
                "remaining": remaining,
                "percent_used": round(percent, 1),
            }
        )

    # Sort: most over-budget first
    statuses.sort(key=lambda s: s["percent_used"], reverse=True)
    return statuses


def format_budget_status(statuses: list[dict], currency: str = "$") -> str:
    """Format budget statuses into a Telegram-friendly message with progress bars."""
    if not statuses:
        return (
            "No budgets set up yet.\n\n"
            "Set one with: /setbudget <category> <limit>\n"
            "Example: /setbudget Groceries 500"
        )

    today = date.today()
    lines = [f"📊 *Budget Status — {today.strftime('%B %Y')}*\n"]

    total_spent = 0.0
    total_limit = 0.0

    for s in statuses:
        category = s["category"]
        spent = s["spent"]
        limit = s["limit"]
        percent = s["percent_used"]

        total_spent += spent
        total_limit += limit

        # Status indicator
        if percent >= 100:
            indicator = " 🔴 OVER"
        elif percent >= 80:
            indicator = " ⚠️"
        else:
            indicator = ""

        lines.append(
            f"{category}: {currency}{spent:,.2f} / {currency}{limit:,.2f} "
            f"({percent:.0f}%){indicator}"
        )
        lines.append(_progress_bar(percent))
        lines.append("")  # blank line

    # Total
    total_percent = (total_spent / total_limit * 100) if total_limit > 0 else 0
    lines.append(
        f"💰 Total: {currency}{total_spent:,.2f} / {currency}{total_limit:,.2f} "
        f"({total_percent:.0f}%)"
    )

    return "\n".join(lines)


def get_budget_alerts(statuses: list[dict]) -> list[str]:
    """Get alert messages for categories approaching or exceeding budget.

    Returns list of alert strings for categories at ≥80% usage.
    """
    alerts = []
    for s in statuses:
        category = s["category"]
        percent = s["percent_used"]

        if percent >= 100:
            over_amount = s["spent"] - s["limit"]
            alerts.append(
                f"🔴 {category} is OVER budget by ${over_amount:,.2f} "
                f"({percent:.0f}% used)"
            )
        elif percent >= 80:
            remaining = s["remaining"]
            alerts.append(
                f"⚠️ {category} is at {percent:.0f}% — "
                f"${remaining:,.2f} remaining"
            )

    return alerts
