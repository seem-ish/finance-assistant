# Personal Finance Assistant

A personal finance management tool with a **Telegram bot** for daily interactions and a **Streamlit dashboard** for visual analytics. Built for two users with shared and individual expense tracking.

## Features

- **Telegram Bot** - Daily/weekly/monthly spending summaries, quick expense entry, bill reminders
- **Web Dashboard** - Interactive charts, category breakdowns, budget tracking
- **Statement Parser** - Automatically parse credit card PDFs and CSVs
- **Bill Tracking** - Recurring bill reminders sent via Telegram
- **Dual-User Support** - Separate and combined views for two users
- **Google Sheets Backend** - Easy to inspect, edit, and share

## Quick Start

### Prerequisites
- Python 3.11+
- A Google Cloud account (free tier works)
- A Telegram account

### 1. Clone and install

```bash
git clone <your-repo-url>
cd finance-assistant
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Set up credentials

Follow the **Credentials Checklist** in [PROJECT_PLAN.md](PROJECT_PLAN.md#credentials-checklist) to set up:
- Google Cloud project with Sheets & Drive APIs
- Telegram bot via @BotFather
- Environment variables

```bash
cp .env.example .env
# Edit .env with your credentials
```

### 3. Run the Telegram bot

```bash
python -m bot.main
```

### 4. Run the dashboard

```bash
streamlit run dashboard/app.py
```

## Project Structure

```
bot/          → Telegram bot (commands, scheduled summaries)
dashboard/    → Streamlit web dashboard
parsers/      → Credit card statement parsers (PDF/CSV)
services/     → Business logic (Sheets, Drive, categorization)
config/       → Settings and credentials
data/         → Local file storage
tests/        → Unit tests
scripts/      → Utility scripts
```

## Development

See [PROJECT_PLAN.md](PROJECT_PLAN.md) for the full development roadmap, database schema, and detailed feature specs.

```bash
# Run tests
pytest

# Format code
black .

# Lint
ruff check .
```
