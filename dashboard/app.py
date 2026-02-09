"""Streamlit dashboard for the finance assistant.

Run:
    streamlit run dashboard/app.py
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# Ensure project root is on the path so imports work when Streamlit runs this file
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings  # noqa: E402
from services.budget_tracker import get_budget_status  # noqa: E402
from services.sheets import GoogleSheetsService  # noqa: E402


# ---------------------------------------------------------------------------
# Helper functions (testable)
# ---------------------------------------------------------------------------


def format_currency(amount: float, symbol: str = "$") -> str:
    """Format a number as currency, e.g. '$25.50'."""
    return f"{symbol}{amount:,.2f}"


def get_date_range(preset: str) -> tuple[date, date]:
    """Return (start_date, end_date) for a named preset.

    Supported presets: "today", "this_week", "this_month", "last_30_days".
    """
    today = date.today()
    if preset == "today":
        return today, today
    elif preset == "this_week":
        monday = today - timedelta(days=today.weekday())
        return monday, today
    elif preset == "this_month":
        return date(today.year, today.month, 1), today
    elif preset == "last_30_days":
        return today - timedelta(days=30), today
    else:
        return date(today.year, today.month, 1), today


def build_category_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate transactions by category.

    Returns a DataFrame with columns: category, total, count — sorted by
    total descending.
    """
    if df.empty:
        return pd.DataFrame(columns=["category", "total", "count"])

    summary = (
        df.groupby("category")
        .agg(total=("amount", "sum"), count=("amount", "count"))
        .reset_index()
        .sort_values("total", ascending=False)
    )
    return summary


# ---------------------------------------------------------------------------
# Streamlit setup & caching
# ---------------------------------------------------------------------------


@st.cache_resource
def get_sheets_service() -> GoogleSheetsService:
    """Create and cache the Google Sheets connection."""
    settings = get_settings()
    sheets = GoogleSheetsService(
        credentials_file=settings.google_credentials_file,
        spreadsheet_id=settings.google_spreadsheet_id,
    )
    sheets.initialize()
    return sheets


@st.cache_data(ttl=300)
def load_categories(_sheets: GoogleSheetsService) -> dict[str, str]:
    """Load category → icon mapping (cached 5 minutes)."""
    df = _sheets.get_categories()
    return dict(zip(df["name"], df["icon"]))


def load_transactions(
    sheets: GoogleSheetsService,
    start_date: date,
    end_date: date,
    user: str | None = None,
) -> pd.DataFrame:
    """Load transactions for a date range (not cached — always fresh)."""
    return sheets.get_transactions(
        start_date=start_date, end_date=end_date, user=user
    )


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Finance Assistant",
    page_icon="💰",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Sidebar — filters
# ---------------------------------------------------------------------------

settings = get_settings()
sheets = get_sheets_service()
icons = load_categories(sheets)

st.sidebar.title("💰 Finance Assistant")
st.sidebar.divider()

# Date range preset
preset = st.sidebar.selectbox(
    "📅 Period",
    options=["this_month", "this_week", "today", "last_30_days", "custom"],
    format_func=lambda x: {
        "today": "Today",
        "this_week": "This Week",
        "this_month": "This Month",
        "last_30_days": "Last 30 Days",
        "custom": "Custom Range",
    }[x],
    index=0,
)

if preset == "custom":
    start_date = st.sidebar.date_input("Start date", value=date.today() - timedelta(days=30))
    end_date = st.sidebar.date_input("End date", value=date.today())
else:
    start_date, end_date = get_date_range(preset)

currency = settings.currency_symbol

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

df = load_transactions(sheets, start_date, end_date, user="user1")
cat_summary = build_category_summary(df)

# ---------------------------------------------------------------------------
# Session state for drill-down
# ---------------------------------------------------------------------------

if "selected_category" not in st.session_state:
    st.session_state.selected_category = None


def select_category(category: str | None) -> None:
    """Set or clear the selected category."""
    st.session_state.selected_category = category


# ---------------------------------------------------------------------------
# DRILL-DOWN VIEW
# ---------------------------------------------------------------------------

if st.session_state.selected_category is not None:
    cat_name = st.session_state.selected_category
    cat_icon = icons.get(cat_name, "📦")

    # Back button
    if st.button("← Back to Overview"):
        select_category(None)
        st.rerun()

    # Filter data for this category
    cat_df = df[df["category"] == cat_name].copy()
    cat_total = cat_df["amount"].sum()
    cat_count = len(cat_df)

    txn_word = "transaction" if cat_count == 1 else "transactions"
    st.title(f"{cat_icon} {cat_name}")
    st.subheader(f"{format_currency(cat_total, currency)} — {cat_count} {txn_word}")
    st.divider()

    if cat_df.empty:
        st.info("No transactions in this category for the selected period.")
    else:
        # Daily spending bar chart for this category
        daily = (
            cat_df.groupby("date")["amount"]
            .sum()
            .reset_index()
            .sort_values("date")
        )
        daily["date"] = pd.to_datetime(daily["date"])
        fig = px.bar(
            daily,
            x="date",
            y="amount",
            title=f"Daily {cat_name} Spending",
            labels={"date": "Date", "amount": f"Amount ({currency})"},
            color_discrete_sequence=["#636EFA"],
        )
        fig.update_layout(
            xaxis_title="", yaxis_title=f"Amount ({currency})", showlegend=False
        )
        st.plotly_chart(fig, use_container_width=True)

        # Transactions table
        st.subheader("📋 Transactions")
        display_df = (
            cat_df[["date", "description", "amount"]]
            .sort_values("date", ascending=False)
            .reset_index(drop=True)
        )
        display_df.columns = ["Date", "Description", "Amount"]
        display_df["Amount"] = display_df["Amount"].apply(
            lambda x: format_currency(x, currency)
        )
        st.dataframe(display_df, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# TOP-LEVEL OVERVIEW
# ---------------------------------------------------------------------------

else:
    st.title("💰 Spending Overview")

    period_labels = {
        "today": "Today",
        "this_week": "This Week",
        "this_month": "This Month",
        "last_30_days": "Last 30 Days",
        "custom": f"{start_date.strftime('%b %d')} – {end_date.strftime('%b %d, %Y')}",
    }
    st.caption(period_labels.get(preset, ""))

    if df.empty:
        st.info(
            "🚀 No transactions yet for this period.\n\n"
            "Add expenses via Telegram: `/add 25 Whole Foods`"
        )
    else:
        # --- KPI cards ---
        total_spent = df["amount"].sum()
        num_transactions = len(df)
        top_category = cat_summary.iloc[0]["category"] if not cat_summary.empty else "—"
        top_icon = icons.get(top_category, "📦")

        col1, col2, col3 = st.columns(3)
        col1.metric("💰 Total Spent", format_currency(total_spent, currency))
        col2.metric("📝 Transactions", num_transactions)
        col3.metric("📊 Top Category", f"{top_icon} {top_category}")

        # --- Budget progress bars (if budgets exist) ---
        budget_statuses = get_budget_status(sheets, user="user1")
        if budget_statuses:
            st.divider()
            st.subheader("📊 Budget Status")

            for bs in budget_statuses:
                cat_name = bs["category"]
                spent = bs["spent"]
                limit = bs["limit"]
                percent = bs["percent_used"]

                # Color: green < 70%, yellow 70-100%, red > 100%
                if percent >= 100:
                    bar_color = "🔴"
                elif percent >= 80:
                    bar_color = "⚠️"
                else:
                    bar_color = "✅"

                label = (
                    f"{bar_color} **{cat_name}**: "
                    f"{format_currency(spent, currency)} / "
                    f"{format_currency(limit, currency)} ({percent:.0f}%)"
                )
                st.markdown(label)
                st.progress(min(percent / 100, 1.0))

        st.divider()

        # --- Charts row ---
        chart_left, chart_right = st.columns(2)

        with chart_left:
            # Donut chart — spending by category
            fig_donut = px.pie(
                cat_summary,
                names="category",
                values="total",
                hole=0.45,
                title="Spending by Category",
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig_donut.update_traces(
                textposition="inside",
                textinfo="label+percent",
                hovertemplate="%{label}: %{value:$.2f}<extra></extra>",
            )
            fig_donut.update_layout(showlegend=False)
            st.plotly_chart(fig_donut, use_container_width=True)

        with chart_right:
            # Bar chart — daily spending
            daily_all = (
                df.groupby("date")["amount"]
                .sum()
                .reset_index()
                .sort_values("date")
            )
            daily_all["date"] = pd.to_datetime(daily_all["date"])
            fig_bar = px.bar(
                daily_all,
                x="date",
                y="amount",
                title="Daily Spending",
                labels={"date": "Date", "amount": f"Amount ({currency})"},
                color_discrete_sequence=["#636EFA"],
            )
            fig_bar.update_layout(
                xaxis_title="", yaxis_title=f"Amount ({currency})", showlegend=False
            )
            st.plotly_chart(fig_bar, use_container_width=True)

        st.divider()

        # --- Category cards (clickable drill-down) ---
        st.subheader("📂 Categories")
        st.caption("Click a category to see its transactions")

        # Display in a grid of 3 columns
        cols = st.columns(3)
        for idx, row in cat_summary.iterrows():
            cat_name = row["category"]
            cat_icon = icons.get(cat_name, "📦")
            cat_total = row["total"]
            cat_count = int(row["count"])
            txn_word = "txn" if cat_count == 1 else "txns"

            col = cols[idx % 3]
            with col:
                if st.button(
                    f"{cat_icon} {cat_name}\n{format_currency(cat_total, currency)} · {cat_count} {txn_word}",
                    key=f"cat_{cat_name}",
                    use_container_width=True,
                ):
                    select_category(cat_name)
                    st.rerun()

        st.divider()

        # --- Recent transactions table ---
        st.subheader("📋 Recent Transactions")
        display_df = (
            df[["date", "category", "description", "amount"]]
            .sort_values("date", ascending=False)
            .head(20)
            .reset_index(drop=True)
        )
        # Add icons to category column
        display_df["category"] = display_df["category"].apply(
            lambda c: f"{icons.get(c, '📦')} {c}"
        )
        display_df.columns = ["Date", "Category", "Description", "Amount"]
        display_df["Amount"] = display_df["Amount"].apply(
            lambda x: format_currency(x, currency)
        )
        st.dataframe(display_df, use_container_width=True, hide_index=True)
