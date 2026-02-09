"""One-time Gmail OAuth2 setup.

Run:
    python -m scripts.setup_gmail

This will:
1. Open a browser window for Google account login
2. Request read-only Gmail access
3. Save the token to config/gmail_token.json

Prerequisites:
    - Enable Gmail API in Google Cloud Console
    - Create OAuth2 Desktop credentials
    - Download as config/gmail_oauth_credentials.json
"""

import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

# Only request read-only access
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def main():
    credentials_file = os.environ.get(
        "GMAIL_OAUTH_CREDENTIALS_FILE", "config/gmail_oauth_credentials.json"
    )
    token_file = os.environ.get("GMAIL_TOKEN_FILE", "config/gmail_token.json")

    if not os.path.exists(credentials_file):
        print(f"\n❌ OAuth2 credentials file not found: {credentials_file}")
        print("\nTo set up Gmail integration:")
        print("1. Go to https://console.cloud.google.com/apis/credentials")
        print("2. Create an OAuth 2.0 Client ID (Desktop app type)")
        print(f"3. Download the JSON and save as {credentials_file}")
        print("4. Run this script again")
        sys.exit(1)

    print("\n📧 Gmail OAuth2 Setup")
    print("=" * 40)
    print("A browser window will open for Google login.")
    print("Grant read-only access to your Gmail.\n")

    flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
    creds = flow.run_local_server(port=0)

    # Save the token
    with open(token_file, "w") as f:
        f.write(creds.to_json())

    print(f"\n✅ Gmail token saved to {token_file}")
    print("\nNext steps:")
    print("1. Add GMAIL_SYNC_ENABLED=true to your .env file")
    print("2. Restart the bot")
    print("3. Use /syncgmail to manually sync, or wait for auto-sync")


if __name__ == "__main__":
    main()
