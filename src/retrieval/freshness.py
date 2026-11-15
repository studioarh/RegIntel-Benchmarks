import re
from datetime import date, datetime
from typing import Final

_WINDOW_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(?:last|past|previous)\s+(?:(\d{1,3})\s+)?(day|days|week|weeks|month|months|year|years|yr|yrs)\b",
    re.IGNORECASE,
)


def extract_requested_window_days(query: str) -> int | None:
    """Extract an explicit lookback window in days from a user query."""
    match = _WINDOW_PATTERN.search(query)
    if match is None:
        return None

    raw_qty = match.group(1)
    quantity = int(raw_qty) if raw_qty is not None else 1
    if quantity <= 0:
        return None

    unit = match.group(2).lower()
    if unit.startswith("day"):
        return quantity
    if unit.startswith("week"):
        return quantity * 7
    if unit.startswith("month"):
        return quantity * 30
    if unit.startswith("year") or unit.startswith("yr"):
        return quantity * 365
    return None


def is_chunk_within_window(
    publication_date: date | datetime | str | None,
    query: str,
    reference_date: date | None = None,
    default_staleness_days: int = 365,
) -> bool:
    """Return True if chunk publication_date is within the query or default window.

    If publication_date is None, returns False so the chunk cannot masquerade
    as fresh evidence when a time window is requested.
    """
    if publication_date is None:
        return False

    if isinstance(publication_date, str):
        try:
            pub_date = date.fromisoformat(publication_date.strip()[:10])
        except ValueError:
            return False
    elif isinstance(publication_date, datetime):
        pub_date = publication_date.date()
    else:
        pub_date = publication_date

    effective_today = reference_date or date.today()
    requested_window = extract_requested_window_days(query)
    threshold_days = requested_window if requested_window is not None else default_staleness_days

    age_days = max(0, (effective_today - pub_date).days)
    return age_days <= threshold_days
