# Personal Finance Assistant - Project Plan

## Overview
A personal finance assistant with a Telegram bot for daily interactions and a Streamlit web dashboard for visualizations. Designed for dual-user support (two partners with shared and individual views), powered by Google Sheets as the database and Google Drive for document storage.

---

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Language | Python 3.11+ | Great ecosystem for data, APIs, and automation |
| Bot | python-telegram-bot | Mature, async, well-documented Telegram library |
| Dashboard | Streamlit | Fast to build, Python-native, great for data apps |
| Database | Google Sheets (via gspread) | Free, familiar, easy to inspect/edit manually |
| File Storage | Google Drive (1TB) | Store credit card statements, receipts |
| Charts | Plotly + Altair | Interactive, beautiful visualizations |
| PDF Parsing | pdfplumber + tabula-py | Handle different PDF formats from banks |
| Scheduling | APScheduler | Automated reminders and scheduled summaries |
| Deployment | Google Cloud Run | Fits within $10/month budget |

---

## Features

### 1. Telegram Bot
- **Daily Summary**: Automated morning message with yesterday's spending
- **Weekly Summary**: Every Monday - week's spending by category, trends
- **Monthly Summary**: 1st of month - full month review, comparisons
- **Interactive Commands**:
  - `/today` - Today's spending so far
  - `/week` - This week's summary
  - `/month` - This month's summary
  - `/add <amount> <category> <description>` - Quick expense entry
  - `/bills` - Upcoming bills and due dates
  - `/budget` - Budget status and remaining amounts
  - `/compare` - Compare spending with previous periods
  - `/shared` - Shared expenses view
  - `/help` - List all commands

### 2. Web Dashboard (Streamlit)
- **Overview Page**: Monthly totals, top categories, recent transactions
- **Spending Analysis**: Category breakdowns, trend charts, month-over-month
- **Budget Tracker**: Budget vs actual by category, visual progress bars
- **Bill Calendar**: Upcoming bills, payment history, overdue alerts
- **Statement Upload**: Drag-and-drop PDF/CSV parsing interface
- **User Switcher**: Toggle between User 1, User 2, and Combined view

### 3. Statement Parser
- PDF parsing for major bank/credit card formats
- CSV import support
- Automatic categorization of transactions
- Duplicate detection
- Support for multiple bank formats (extensible)

### 4. Bill Tracking
- Recurring bill definitions (rent, utilities, subscriptions)
- Due date reminders via Telegram (3 days before, day of)
- Payment confirmation tracking
- Monthly bill summary

### 5. Smart Insights
- Budget alerts when approaching/exceeding limits
- Spending pattern detection (unusual spending, trends)
- Credit card optimization suggestions
- Monthly savings rate tracking

### 6. Dual-User Support
- Separate transaction tracking per user
- Individual budget settings
- Shared expenses view and splitting
- Combined household dashboard

### 7. Gmail Integration
- Daily/weekly/monthly summaries mirrored to email
- Bill payment reminders via email
- Budget alerts via email
- HTML-formatted emails with tables and charts

### 8. Google Calendar Integration
- Bill due dates as recurring calendar events
- Weekly/monthly budget review reminders
- Daily/weekly/monthly summary schedule markers
- Color-coded by type (bills, reviews, summaries)
- Auto-update when bills change

### 9. Telegram Financial Q&A
- Natural language spending queries ("how much on dining?")
- Period comparisons ("am I spending more than last month?")
- Budget status queries ("how's my grocery budget?")
- Bill info ("when is rent due?")
- Savings insights ("how can I save more?" with actionable suggestions)

---

## Development Phases

**Workflow:** Build → Write tests → Claude tests + you test → Green light → Push to GitHub → Next phase

### Phase 1: Google Sheets Service Layer
- [ ] `services/sheets.py` — CRUD operations, auto-create sheets
- [ ] `tests/test_sheets.py`

### Phase 2: Basic Telegram Bot
- [ ] `bot/main.py`, `bot/handlers.py` — `/start`, `/help`, `/add`, `/today`, `/week`, `/month`
- [ ] `tests/test_bot.py`

### Phase 3: Transaction Categorizer
- [ ] `services/categorizer.py` — keyword matching, fuzzy matching
- [ ] `tests/test_categorizer.py`

### Phase 4: Streamlit Dashboard
- [ ] `dashboard/app.py` — overview, charts, user switcher
- [ ] `tests/test_dashboard.py`

### Phase 5: CSV Statement Parser
- [ ] `parsers/base.py`, `parsers/csv_parser.py`
- [ ] `tests/test_csv_parser.py`

### Phase 6: PDF Statement Parser
- [ ] `parsers/pdf_parser.py`
- [ ] `tests/test_pdf_parser.py`

### Phase 7: Bill Tracking & Reminders
- [ ] `services/bills.py`, bot commands `/bills`, `/addbill`, `/paybill`
- [ ] `tests/test_bills.py`

### Phase 8: Budget Tracking & Alerts
- [ ] `services/insights.py`, bot commands `/budget`, `/setbudget`
- [ ] `tests/test_insights.py`

### Phase 9: Automated Summaries (Telegram)
- [ ] `bot/summaries.py` — daily/weekly/monthly via APScheduler
- [ ] `tests/test_summaries.py`

### Phase 10: Gmail Integration
- [ ] `services/gmail.py` — mirror all summaries + reminders to email
- [ ] `tests/test_gmail.py`

### Phase 11: Google Calendar Integration
- [ ] `services/calendar.py` — bill dates, review reminders, summary schedule
- [ ] `tests/test_calendar.py`

### Phase 12: Telegram Financial Q&A
- [ ] `bot/qa.py` — natural language queries, savings suggestions
- [ ] `tests/test_qa.py`

### Phase 13: Dual-User & Shared Expenses
- [ ] Shared expense splitting, `/shared` command, combined dashboard view
- [ ] `tests/test_dual_user.py`

### Phase 14: Google Cloud Deployment
- [ ] Dockerfile, Cloud Run configs, Cloud Scheduler
- [ ] Stay within $10/month budget

---

## Google Sheets Database Schema

### Sheet: "Transactions"
| Column | Type | Description |
|--------|------|-------------|
| id | string | Unique transaction ID |
| date | date | Transaction date |
| amount | number | Transaction amount |
| category | string | Spending category |
| description | string | Transaction description |
| user | string | "user1" or "user2" |
| source | string | "manual", "statement", "csv" |
| card | string | Which credit card |
| is_shared | boolean | Whether it's a shared expense |
| created_at | datetime | When the record was created |

### Sheet: "Bills"
| Column | Type | Description |
|--------|------|-------------|
| id | string | Unique bill ID |
| name | string | Bill name (e.g., "Rent", "Netflix") |
| amount | number | Bill amount |
| due_day | number | Day of month (1-31) |
| frequency | string | "monthly", "quarterly", "annual" |
| category | string | Bill category |
| user | string | "user1", "user2", or "shared" |
| auto_pay | boolean | Whether it's on auto-pay |
| active | boolean | Whether the bill is active |

### Sheet: "Budgets"
| Column | Type | Description |
|--------|------|-------------|
| category | string | Spending category |
| monthly_limit | number | Budget limit |
| user | string | "user1", "user2", or "shared" |

### Sheet: "Categories"
| Column | Type | Description |
|--------|------|-------------|
| name | string | Category name |
| keywords | string | Comma-separated matching keywords |
| icon | string | Emoji icon for display |

---

## Spending Categories (Default)
| Category | Icon | Example Keywords |
|----------|------|-----------------|
| Groceries | 🛒 | supermarket, grocery, whole foods |
| Dining | 🍽️ | restaurant, doordash, uber eats |
| Transport | 🚗 | gas, uber, lyft, parking |
| Shopping | 🛍️ | amazon, target, walmart |
| Entertainment | 🎬 | netflix, spotify, movies |
| Health | 🏥 | pharmacy, doctor, gym |
| Utilities | 💡 | electric, water, internet |
| Housing | 🏠 | rent, mortgage, maintenance |
| Subscriptions | 📱 | software, apps, memberships |
| Travel | ✈️ | hotel, airline, airbnb |
| Education | 📚 | courses, books, tuition |
| Personal | 💅 | salon, clothing, gifts |
| Insurance | 🛡️ | auto, health, life insurance |
| Other | 📦 | uncategorized |

---

## Credentials Checklist

Before you can run the project, you'll need to set up:

### 1. Google Cloud Project
- [ ] Create a Google Cloud project at https://console.cloud.google.com
- [ ] Enable the Google Sheets API
- [ ] Enable the Google Drive API
- [ ] Enable the Gmail API (needed for Phase 10)
- [ ] Enable the Google Calendar API (needed for Phase 11)
- [ ] Create a Service Account
- [ ] Download the Service Account JSON key file
- [ ] Save it as `config/google_credentials.json`

### 2. Google Sheets Setup
- [ ] Create a new Google Spreadsheet
- [ ] Share the spreadsheet with the Service Account email
- [ ] Copy the Spreadsheet ID from the URL
- [ ] Add the ID to your `.env` file

### 3. Telegram Bot
- [ ] Message @BotFather on Telegram
- [ ] Create a new bot with `/newbot`
- [ ] Copy the bot token
- [ ] Add the token to your `.env` file
- [ ] Get your Telegram user ID (message @userinfobot)
- [ ] Get your husband's Telegram user ID too

### 4. Environment Variables
- [ ] Copy `.env.example` to `.env`
- [ ] Fill in all values (see `.env.example` for descriptions)

---

## Budget Estimate (Google Cloud Deployment)

| Service | Estimated Cost |
|---------|---------------|
| Cloud Run (Bot) | $2-3/month |
| Cloud Run (Dashboard) | $2-3/month |
| Cloud Scheduler | Free tier (3 jobs) |
| Google Sheets API | Free tier |
| Google Drive API | Free tier |
| **Total** | **~$4-6/month** ✅ Under $10 budget |

---

## File Structure
```
finance-assistant/
├── bot/                    # Telegram bot
│   ├── __init__.py
│   ├── main.py            # Bot entry point
│   ├── handlers.py        # Command handlers
│   └── summaries.py       # Automated summary generation
├── dashboard/              # Streamlit web app
│   ├── __init__.py
│   ├── app.py             # Dashboard entry point
│   ├── pages/             # Multi-page dashboard
│   └── components/        # Reusable UI components
├── parsers/                # Statement parsing
│   ├── __init__.py
│   ├── base.py            # Base parser interface
│   ├── pdf_parser.py      # PDF statement parser
│   └── csv_parser.py      # CSV statement parser
├── services/               # Business logic
│   ├── __init__.py
│   ├── sheets.py          # Google Sheets operations
│   ├── drive.py           # Google Drive operations
│   ├── categorizer.py     # Transaction categorization
│   ├── bills.py           # Bill tracking logic
│   └── insights.py        # Smart insights and alerts
├── config/                 # Configuration
│   ├── __init__.py
│   ├── settings.py        # App settings (Pydantic)
│   └── google_credentials.json  # (gitignored)
├── data/                   # Local storage
│   ├── statements/        # Uploaded statements
│   └── exports/           # Generated reports
├── tests/                  # Tests
├── scripts/                # Utility scripts
├── .env                    # Environment variables (gitignored)
├── .env.example            # Environment template
├── .gitignore
├── requirements.txt
├── PROJECT_PLAN.md         # This file
└── README.md
```
