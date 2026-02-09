"""One-time Google Calendar OAuth2 setup.

Run:
    python -m scripts.setup_calendar

This will:
1. Open a browser window for Google account login
2. Request access to create/manage calendar events
3. Save the token to config/calendar_token.json

Prerequisites:
    - Enable Google Calendar API in Google Cloud Console
    - OAuth2 credentials file at config/gmail_oauth_credentials.json
      (same file used for Gmail setup)
"""

import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def main():
    credentials_file = os.environ.get(
        "GMAIL_OAUTH_CREDENTIALS_FILE", "config/gmail_oauth_credentials.json"
    )
    token_file = os.environ.get("CALENDAR_TOKEN_FILE", "config/calendar_token.json")

    if not os.path.exists(credentials_file):
        print(f"\n❌ OAuth2 credentials file not found: {credentials_file}")
        print("\nTo set up Calendar integration:")
        print("1. Go to https://console.cloud.google.com/apis/credentials")
        print("2. Use the same OAuth 2.0 Client ID from Gmail setup")
        print("   (or create a new one — Desktop app type)")
        print(f"3. Ensure {credentials_file} exists")
        print("4. Enable Google Calendar API in your project")
        print("5. Run this script again")
        sys.exit(1)

    print("\n📅 Google Calendar OAuth2 Setup")
    print("=" * 40)
    print("A browser window will open for Google login.")
    print("Grant access to manage calendar events.\n")

    flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
    creds = flow.run_local_server(port=0)

    with open(token_file, "w") as f:
        f.write(creds.to_json())

    print(f"\n✅ Calendar token saved to {token_file}")
    print("\nNext steps:")
    print("1. Add CALENDAR_SYNC_ENABLED=true to your .env file")
    print("2. Restart the bot")
    print("3. Use /synccalendar to sync bills, or wait for auto-sync")


if __name__ == "__main__":
    main()
