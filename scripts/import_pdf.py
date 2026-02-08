"""CLI script to import a credit card PDF statement.

Usage:
    python -m scripts.import_pdf <pdf_file> --card "Chase Sapphire"
    python -m scripts.import_pdf statement.pdf --card "Amex Gold" --user user2

Supports: Chase, Amex, Discover, Capital One (auto-detected from PDF text).
"""

import argparse
import logging
import sys
from pathlib import Path

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings
from parsers.pdf_parser import import_pdf
from services.categorizer import Categorizer
from services.sheets import GoogleSheetsService


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import a credit card PDF statement into Google Sheets."
    )
    parser.add_argument("pdf_file", help="Path to the PDF file")
    parser.add_argument(
        "--card",
        default="",
        help='Credit card name (e.g., "Chase Sapphire", "Amex Gold")',
    )
    parser.add_argument(
        "--user",
        default="user1",
        choices=["user1", "user2"],
        help="Which user owns these transactions (default: user1)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )
    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")

    # Check file exists
    pdf_path = Path(args.pdf_file)
    if not pdf_path.exists():
        print(f"❌ File not found: {pdf_path}")
        sys.exit(1)

    # Initialize services
    settings = get_settings()
    sheets = GoogleSheetsService(
        credentials_file=settings.google_credentials_file,
        spreadsheet_id=settings.google_spreadsheet_id,
    )
    sheets.initialize()
    categorizer = Categorizer(sheets)

    print(f"📄 Importing: {pdf_path.name}")
    if args.card:
        print(f"💳 Card: {args.card}")

    # Import
    try:
        result = import_pdf(
            filepath=str(pdf_path),
            sheets=sheets,
            categorizer=categorizer,
            user=args.user,
            card=args.card,
        )
    except Exception as e:
        print(f"❌ {e}")
        sys.exit(1)

    # Print summary
    print(f"\n🏦 Bank detected: {result['bank']}")
    print(f"✅ Imported: {result['imported']} transactions")
    print(f"⏭️  Skipped (duplicates): {result['skipped_duplicates']}")
    if result["errors"] > 0:
        print(f"❌ Errors: {result['errors']}")
    print("\nDone! Check your Google Sheet or dashboard.")


if __name__ == "__main__":
    main()
