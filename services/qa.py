"""Natural language Q&A service powered by OpenAI.

Fetches the user's financial data from Google Sheets, builds a context prompt,
sends it to OpenAI along with the user's question, and returns a concise answer.

Usage:
    from services.qa import answer_question

    answer = answer_question(
        question="How much did I spend on groceries this month?",
        sheets=sheets_service,
        user="user1",
        settings=settings,
    )
"""

import logging
from datetime import date, timedelta

from openai import OpenAI

from services.budget_tracker import get_budget_status
from services.sheets import GoogleSheetsService

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a personal finance assistant. Answer the user's question based on "
    "their financial data provided below.\n\n"
    "Rules:\n"
    "- Be concise (2-4 sentences max).\n"
    "- Always include dollar amounts when relevant.\n"
    "- If the data doesn't contain the answer, say so clearly.\n"
    "- Use the user's currency symbol from the data.\n"
    "- Do NOT make up numbers — only use what's in the data.\n"
)

MAX_CONTEXT_CHARS = 6000  # Keep context compact to stay within token limits


def _build_financial_context(
    sheets: GoogleSheetsService,
    user: str,
    currency: str = "$",
) -> str:
    """Build a text block of the user's financial data for the LLM prompt.

    Fetches this month's transactions, budget status, and active bills,
    then formats them into a compact string.

    Args:
        sheets: Initialized GoogleSheetsService.
        user: "user1" or "user2".
        currency: Currency symbol for display.

    Returns:
        Formatted financial context string.
    """
    today = date.today()
    month_start = date(today.year, today.month, 1)
    week_start = today - timedelta(days=today.weekday())

    sections = []

    # --- This month's transactions ---
    try:
        month_df = sheets.get_transactions(
            start_date=month_start, end_date=today, user=user
        )
        if not month_df.empty:
            total = month_df["amount"].sum()
            count = len(month_df)
            lines = [
                f"CURRENT MONTH TRANSACTIONS ({month_start.strftime('%B %Y')}):",
                f"Total: {currency}{total:.2f} across {count} transactions",
                "",
                "By category:",
            ]
            by_cat = (
                month_df.groupby("category")["amount"]
                .sum()
                .sort_values(ascending=False)
            )
            for cat, amt in by_cat.items():
                cat_count = len(month_df[month_df["category"] == cat])
                lines.append(f"  {cat}: {currency}{amt:.2f} ({cat_count} txns)")

            # Recent transactions (last 10)
            lines.append("")
            lines.append("Recent transactions:")
            recent = month_df.sort_values("date", ascending=False).head(10)
            for _, row in recent.iterrows():
                lines.append(
                    f"  {row['date']} — {currency}{row['amount']:.2f} — "
                    f"{row['category']} — {row['description']}"
                )
            sections.append("\n".join(lines))
        else:
            sections.append("CURRENT MONTH TRANSACTIONS: No transactions yet.")
    except Exception as e:
        logger.warning("Failed to fetch month transactions for QA: %s", e)
        sections.append("CURRENT MONTH TRANSACTIONS: Unable to fetch.")

    # --- This week's transactions ---
    try:
        week_df = sheets.get_transactions(
            start_date=week_start, end_date=today, user=user
        )
        if not week_df.empty:
            total = week_df["amount"].sum()
            sections.append(
                f"THIS WEEK ({week_start.strftime('%b %d')} — "
                f"{today.strftime('%b %d')}): {currency}{total:.2f} "
                f"across {len(week_df)} transactions"
            )
        else:
            sections.append("THIS WEEK: No transactions yet.")
    except Exception as e:
        logger.warning("Failed to fetch week transactions for QA: %s", e)

    # --- Budget status ---
    try:
        statuses = get_budget_status(sheets, user=user)
        if statuses:
            lines = ["BUDGET STATUS:"]
            for s in statuses:
                lines.append(
                    f"  {s['category']}: {currency}{s['spent']:.2f} / "
                    f"{currency}{s['limit']:.2f} ({s['percent_used']:.0f}% used)"
                )
            sections.append("\n".join(lines))
        else:
            sections.append("BUDGET STATUS: No budgets configured.")
    except Exception as e:
        logger.warning("Failed to fetch budget status for QA: %s", e)

    # --- Active bills ---
    try:
        bills_df = sheets.get_bills(active_only=True, user=user)
        if not bills_df.empty:
            lines = ["ACTIVE BILLS:"]
            for _, row in bills_df.iterrows():
                lines.append(
                    f"  {row['name']}: {currency}{float(row['amount']):.2f} "
                    f"due day {row['due_day']} ({row['frequency']})"
                )
            sections.append("\n".join(lines))
        else:
            sections.append("ACTIVE BILLS: None.")
    except Exception as e:
        logger.warning("Failed to fetch bills for QA: %s", e)

    context = "\n\n".join(sections)

    # Truncate if too long to avoid token limits
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS] + "\n... (data truncated)"

    return context


def answer_question(
    question: str,
    sheets: GoogleSheetsService,
    user: str,
    settings,
) -> str:
    """Answer a natural-language question about the user's finances.

    Args:
        question: The user's question text.
        sheets: Initialized GoogleSheetsService.
        user: "user1" or "user2".
        settings: Application settings (must have openai_api_key, qa_model, etc.).

    Returns:
        Answer string from the LLM, or an error message.
    """
    if not settings.qa_enabled:
        return (
            "Q&A is not enabled. Add your OpenAI API key and set "
            "QA_ENABLED=true in your .env file."
        )

    if not settings.openai_api_key:
        return "OpenAI API key not configured. Add OPENAI_API_KEY to your .env file."

    # Build financial context
    context = _build_financial_context(
        sheets, user, currency=settings.currency_symbol
    )

    # Compose messages for the LLM
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + "\n" + context},
        {"role": "user", "content": question},
    ]

    try:
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=settings.qa_model,
            messages=messages,
            max_tokens=500,
            temperature=0.3,
        )
        answer = response.choices[0].message.content.strip()
        return answer

    except Exception as e:
        logger.error("OpenAI API error: %s", e)
        return "Sorry, I couldn't process your question right now. Please try again later."
