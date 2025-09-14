# src/core/date_utils.py
import logging
import re
from datetime import datetime
from typing import Optional, List

logger = logging.getLogger('vibe_manager')

# Common date format patterns that the website might use
DATE_PATTERNS = [
    # US formats
    ('%m/%d/%y', r'^\d{1,2}/\d{1,2}/\d{2}$'),          # 9/2/24, 11/21/23
    ('%m/%d/%Y', r'^\d{1,2}/\d{1,2}/\d{4}$'),          # 9/2/2024, 11/21/2023
    ('%m-%d-%y', r'^\d{1,2}-\d{1,2}-\d{2}$'),          # 9-2-24, 11-21-23
    ('%m-%d-%Y', r'^\d{1,2}-\d{1,2}-\d{4}$'),          # 9-2-2024, 11-21-2023
    ('%B %d, %Y', r'^[A-Za-z]+ \d{1,2}, \d{4}$'),     # September 2, 2024
    ('%b %d, %Y', r'^[A-Za-z]{3} \d{1,2}, \d{4}$'),   # Sep 2, 2024
    ('%Y-%m-%d', r'^\d{4}-\d{2}-\d{2}$'),              # 2024-09-02 (ISO format)
    ('%d/%m/%y', r'^\d{1,2}/\d{1,2}/\d{2}$'),          # 2/9/24 (European, fallback)
    ('%d/%m/%Y', r'^\d{1,2}/\d{1,2}/\d{4}$'),          # 2/9/2024 (European, fallback)
]

# Display format mappings for user preferences
DISPLAY_FORMATS = {
    'yyyy-MM-dd': '%Y-%m-%d',           # 2024-09-02
    'MM/dd/yyyy': '%m/%d/%Y',           # 09/02/2024
    'M/d/yy': '%m/%d/%y',               # 9/2/24
    'MMMM d, yyyy': '%B %d, %Y',        # September 2, 2024
    'MMM d, yyyy': '%b %d, %Y',         # Sep 2, 2024
}


def intelligent_date_parse(date_str: str) -> Optional[str]:
    """
    Intelligently parse a date string from various formats and return ISO-8601 format.
    
    Args:
        date_str: The date string to parse
        
    Returns:
        ISO-8601 formatted date string (YYYY-MM-DD) or None if parsing fails
    """
    if not date_str or not date_str.strip():
        return None
    
    date_str = date_str.strip()
    
    # Try each pattern until one works
    for fmt, pattern in DATE_PATTERNS:
        if re.match(pattern, date_str):
            try:
                parsed_date = datetime.strptime(date_str, fmt)
                iso_date = parsed_date.strftime('%Y-%m-%d')
                logger.debug(f"Successfully parsed '{date_str}' using format '{fmt}' -> '{iso_date}'")
                return iso_date
            except ValueError:
                continue
    
    # If no pattern matches, log an error
    logger.error(f"Failed to parse date: '{date_str}' - no matching pattern found")
    return None


def format_date_for_display(iso_date_str: str, display_format: str = 'yyyy-MM-dd') -> Optional[str]:
    """
    Format an ISO-8601 date string for display according to user preference.
    
    Args:
        iso_date_str: ISO-8601 formatted date string (YYYY-MM-DD)
        display_format: User's preferred display format key
        
    Returns:
        Formatted date string or original string if formatting fails
    """
    if not iso_date_str or not iso_date_str.strip():
        return iso_date_str
    
    try:
        # Parse the ISO date
        date_obj = datetime.strptime(iso_date_str.strip(), '%Y-%m-%d')
        
        # Get the format string for the display preference
        fmt = DISPLAY_FORMATS.get(display_format, '%Y-%m-%d')
        
        # Format and return
        formatted_date = date_obj.strftime(fmt)
        logger.debug(f"Formatted '{iso_date_str}' as '{formatted_date}' using format '{display_format}'")
        return formatted_date
        
    except ValueError as e:
        logger.warning(f"Failed to format date '{iso_date_str}' with format '{display_format}': {e}")
        return iso_date_str  # Return original if formatting fails


def get_available_display_formats() -> List[tuple]:
    """
    Get list of available display formats for the settings dropdown.
    
    Returns:
        List of (format_key, format_description) tuples
    """
    return [
        ('yyyy-MM-dd', '2024-09-02 (ISO Standard)'),
        ('MM/dd/yyyy', '09/02/2024 (US Long)'),
        ('M/d/yy', '9/2/24 (US Short)'),
        ('MMMM d, yyyy', 'September 2, 2024 (Full Month)'),
        ('MMM d, yyyy', 'Sep 2, 2024 (Abbreviated Month)'),
    ]


def validate_date_format(date_str: str) -> bool:
    """
    Validate if a date string can be parsed by our intelligent parser.
    
    Args:
        date_str: The date string to validate
        
    Returns:
        True if the date can be parsed, False otherwise
    """
    return intelligent_date_parse(date_str) is not None


# Backward compatibility functions for existing code
def parse_date(date_str: str) -> Optional[str]:
    """
    Legacy function name for backward compatibility.
    Same as intelligent_date_parse.
    """
    return intelligent_date_parse(date_str)


def standardize_date(date_str: str) -> Optional[str]:
    """
    Legacy function name for backward compatibility.
    Same as intelligent_date_parse.
    """
    return intelligent_date_parse(date_str)