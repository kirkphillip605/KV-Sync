# src/core/utils.py
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)


def sanitize_filename(artist, title, song_id):
    """Sanitize the filename by removing invalid characters and produce a .zip name."""
    regex_pattern = r"[^a-zA-Z0-9\s\-\(\)&']"
    sanitized_artist = re.sub(regex_pattern, "", artist).strip()
    sanitized_title = re.sub(regex_pattern, "", title).strip()
    return f"{sanitized_artist} - {sanitized_title} - {song_id}.zip"


def standardize_date(date_str):
    """Try to standardize a date string to YYYY-MM-DD by testing various formats."""
    if not date_str:
        return None
    for fmt in ('%Y-%m-%d', '%m/%d/%y', '%m/%d/%Y'):
        try:
            parsed_date = datetime.strptime(date_str, fmt)
            return parsed_date.strftime('%Y-%m-%d')
        except ValueError:
            continue
    logger.error(f"Date format not recognized: {date_str}")
    return None
