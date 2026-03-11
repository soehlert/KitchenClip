
import re

from bs4 import BeautifulSoup


def parse_iso_duration(duration_str: str) -> int | None:
    """Parse ISO 8601 duration string (e.g., PT1H30M) into total minutes."""
    if not duration_str:
        return None
    match = re.match(r'P(?:T(?:(\d+)H)?(?:(\d+)M)?)?', duration_str)
    if match:
        hours = int(match.group(1)) if match.group(1) else 0
        minutes = int(match.group(2)) if match.group(2) else 0
        total = hours * 60 + minutes
        return total if total > 0 else None
    return None

def get_soup(html: str) -> BeautifulSoup:
    """Return a BeautifulSoup object for the given HTML."""
    return BeautifulSoup(html, 'html.parser')
