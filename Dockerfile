# Finance Assistant — Docker image for Cloud Run
# Runs both the Telegram bot (default) and Streamlit dashboard (override CMD)

FROM python:3.13-slim

# Install system dependencies
# - Java: required by tabula-py for PDF table extraction
# - gcc: required for some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-jre-headless \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY config/ config/
COPY bot/ bot/
COPY services/ services/
COPY parsers/ parsers/
COPY dashboard/ dashboard/
COPY scripts/ scripts/
COPY .streamlit/ .streamlit/

# Cloud Run will set PORT environment variable
ENV PORT=8080

# Default: run the Telegram bot
# Override for dashboard: CMD ["streamlit", "run", "dashboard/app.py", "--server.port=8080", "--server.address=0.0.0.0"]
CMD ["python", "-m", "bot.main"]
