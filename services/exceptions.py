"""Custom exceptions for the finance assistant services."""


class SheetsConnectionError(Exception):
    """Raised when unable to connect to Google Sheets."""
    pass


class InvalidDataError(Exception):
    """Raised when data fails validation."""
    pass


class DuplicateTransactionError(Exception):
    """Raised when a duplicate transaction is detected."""
    pass


class SheetNotFoundError(Exception):
    """Raised when a required sheet cannot be found or created."""
    pass
