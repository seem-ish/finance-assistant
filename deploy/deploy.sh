#!/bin/bash
# =========================================================================
# Finance Assistant — Deploy to Google Cloud Run
# =========================================================================
#
# Prerequisites:
#   1. gcloud CLI installed and authenticated
#   2. Project set: gcloud config set project YOUR_PROJECT_ID
#   3. APIs enabled: Cloud Run, Cloud Build, Container Registry, Secret Manager
#   4. Secrets created (see setup instructions below)
#
# Usage:
#   chmod +x deploy/deploy.sh
#   ./deploy/deploy.sh
#
# =========================================================================

set -euo pipefail

# --- Configuration ---
PROJECT_ID=$(gcloud config get-value project)
REGION="us-central1"
IMAGE="gcr.io/${PROJECT_ID}/finance-assistant"

echo "📦 Project: ${PROJECT_ID}"
echo "🌎 Region: ${REGION}"
echo ""

# =========================================================================
# Step 1: Create secrets (run once, then comment out)
# =========================================================================
# Uncomment these lines on FIRST deploy to create secrets:
#
# echo "🔐 Creating secrets..."
# echo -n "YOUR_BOT_TOKEN" | gcloud secrets create TELEGRAM_BOT_TOKEN --data-file=-
# echo -n "YOUR_OPENAI_KEY" | gcloud secrets create OPENAI_API_KEY --data-file=-
# gcloud secrets create GOOGLE_CREDENTIALS --data-file=config/google_credentials.json
#
# To update a secret later:
#   echo -n "new-value" | gcloud secrets versions add SECRET_NAME --data-file=-

# =========================================================================
# Step 2: Build and push Docker image
# =========================================================================

echo "🔨 Building Docker image..."
gcloud builds submit \
    --tag "${IMAGE}:latest" \
    --timeout=600s \
    .

echo "✅ Image built and pushed: ${IMAGE}:latest"
echo ""

# =========================================================================
# Step 3: Deploy Telegram Bot (always-on)
# =========================================================================

echo "🤖 Deploying Telegram bot..."
gcloud run deploy finance-bot \
    --image "${IMAGE}:latest" \
    --region "${REGION}" \
    --platform managed \
    --min-instances 1 \
    --max-instances 1 \
    --memory 512Mi \
    --cpu 1 \
    --timeout 3600 \
    --no-allow-unauthenticated \
    --set-env-vars "\
TELEGRAM_USER1_ID=7992938764,\
TELEGRAM_USER2_ID=000000000,\
TELEGRAM_USER1_NAME=Seemran,\
TELEGRAM_USER2_NAME=Amit,\
GOOGLE_SPREADSHEET_ID=1q0xbaCkhqgJ4nXZ65a7OyT7iR4bJjvP7gR1Y4yE4U5M,\
GOOGLE_CREDENTIALS_FILE=/secrets/google-credentials/google_credentials.json,\
CURRENCY_SYMBOL=\$,\
TIMEZONE=America/New_York,\
AUTO_SUMMARIES_ENABLED=true,\
QA_ENABLED=true,\
QA_MODEL=gpt-4o-mini,\
GMAIL_SYNC_ENABLED=false,\
CALENDAR_SYNC_ENABLED=false" \
    --set-secrets "\
TELEGRAM_BOT_TOKEN=TELEGRAM_BOT_TOKEN:latest,\
OPENAI_API_KEY=OPENAI_API_KEY:latest" \
    --set-secrets "/secrets/google-credentials/google_credentials.json=GOOGLE_CREDENTIALS:latest"

BOT_URL=$(gcloud run services describe finance-bot --region "${REGION}" --format 'value(status.url)')
echo "✅ Bot deployed: ${BOT_URL}"
echo ""

# =========================================================================
# Step 4: Deploy Streamlit Dashboard (scales to zero)
# =========================================================================

echo "📊 Deploying dashboard..."
gcloud run deploy finance-dashboard \
    --image "${IMAGE}:latest" \
    --region "${REGION}" \
    --platform managed \
    --min-instances 0 \
    --max-instances 2 \
    --memory 512Mi \
    --cpu 1 \
    --port 8080 \
    --timeout 300 \
    --allow-unauthenticated \
    --command "streamlit" \
    --args "run,dashboard/app.py,--server.port=8080,--server.address=0.0.0.0,--server.headless=true" \
    --set-env-vars "\
TELEGRAM_USER1_ID=7992938764,\
TELEGRAM_USER2_ID=000000000,\
TELEGRAM_USER1_NAME=Seemran,\
TELEGRAM_USER2_NAME=Amit,\
GOOGLE_SPREADSHEET_ID=1q0xbaCkhqgJ4nXZ65a7OyT7iR4bJjvP7gR1Y4yE4U5M,\
GOOGLE_CREDENTIALS_FILE=/secrets/google-credentials/google_credentials.json,\
CURRENCY_SYMBOL=\$,\
TIMEZONE=America/New_York" \
    --set-secrets "/secrets/google-credentials/google_credentials.json=GOOGLE_CREDENTIALS:latest"

DASHBOARD_URL=$(gcloud run services describe finance-dashboard --region "${REGION}" --format 'value(status.url)')
echo "✅ Dashboard deployed: ${DASHBOARD_URL}"
echo ""

# =========================================================================
# Done!
# =========================================================================

echo "🎉 Deployment complete!"
echo ""
echo "  🤖 Bot:       ${BOT_URL} (always-on, responds on Telegram)"
echo "  📊 Dashboard: ${DASHBOARD_URL}"
echo ""
echo "Next steps:"
echo "  1. Test the bot on Telegram — send /start to @alfie_finance_bot"
echo "  2. Open the dashboard URL in your browser"
echo "  3. Monitor logs: gcloud run logs read finance-bot --region ${REGION}"
