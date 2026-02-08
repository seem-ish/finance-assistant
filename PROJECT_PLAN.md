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

---

## Development Phases

### Phase 1: Foundation (Weeks 1-2) - LOCAL DEVELOPMENT
**Goal**: Working bot + basic dashboard running locally

#### Week 1: Core Setup
- [x] Project structure and dependencies
- [ ] Google Cloud project setup (Sheets API, Drive API)
- [ ] Google Sheets database schema design
- [ ] Google Sheets connection and CRUD operations
- [ ] Basic Telegram bot with `/start`, `/help`, `/add` commands
- [ ] Manual expense entry via bot

#### Week 2: Dashboard & Parsing
- [ ] Streamlit dashboard - overview page
- [ ] Spending charts (category pie, daily bar, trend line)
- [ ] Basic PDF statement parser (start with 1-2 bank formats)
- [ ] CSV import support
- [ ] Bill tracking data model and basic reminders

### Phase 2: Intelligence (Week 3) - ENHANCE LOCALLY
**Goal**: Smart features and automated summaries

- [ ] Automated daily/weekly/monthly summaries via Telegram
- [ ] Budget tracking and alerts
- [ ] Spending pattern analysis
- [ ] Dual-user support (separate + shared views)
- [ ] Transaction categorization improvements
- [ ] Bill reminder automation

### Phase 3: Deployment (Week 4+) - GOOGLE CLOUD
**Goal**: Running 24/7 on Google Cloud

- [ ] Dockerize the application
- [ ] Deploy Telegram bot to Cloud Run
- [ ] Deploy Streamlit dashboard to Cloud Run
- [ ] Set up Cloud Scheduler for automated tasks
- [ ] Configure Google Drive for statement storage
- [ ] Cost optimization (stay within $10/month)

### Phase 4: Polish (Ongoing)
- [ ] Add more bank statement formats
- [ ] Credit card optimization insights
- [ ] Receipt photo parsing (OCR)
- [ ] Export reports as PDF
- [ ] Shared expense splitting logic

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
