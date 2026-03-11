from abc import ABC, abstractmethod
import httpx
import logging
from recipes.ingredient_processor import format_time_h_m

logger = logging.getLogger(__name__)


class BaseParser(ABC):
    """
    Abstract base class for all recipe parsers.
    Any custom parser should inherit from this and implement the methods.
    """
    
    def __init__(self, url: str, html: str | None = None):
        self.url = url
        if html is None:
            self.html = self._fetch_html(url)
        else:
            self.html = html

    def _fetch_html(self, url: str) -> str | None:
        """Fetch HTML content from the URL with robust headers using httpx."""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Referer': 'https://www.google.com/',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'cross-site',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        }
        try:
            with httpx.Client(follow_redirects=True, timeout=15.0) as client:
                response = client.get(url, headers=headers)
                
                if response.status_code == 403:
                    logger.warning(f"Access forbidden (403) for {url}. Possible bot detection.")
                
                response.raise_for_status()
                return response.text
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code} fetching HTML from {url}")
            return None
        except Exception as e:
            logger.error(f"Failed to fetch HTML from {url}: {e}")
            return None

    @property
    @abstractmethod
    def title(self) -> str:
        """Return the recipe title."""
        pass

    @property
    @abstractmethod
    def ingredients(self) -> list[str]:
        """Return a list of raw ingredient strings."""
        pass

    @property
    @abstractmethod
    def instructions(self) -> str:
        """Return the instructions as a single string."""
        pass

    @property
    def description(self) -> str:
        """Return a brief description of the recipe."""
        return ""

    @property
    def image_url(self) -> str:
        """Return the main recipe image URL."""
        return ""

    @property
    def prep_time(self) -> int | None:
        """Return prep time in minutes."""
        return None

    @property
    def cook_time(self) -> int | None:
        """Return cook time in minutes."""
        return None

    @property
    def total_time(self) -> int | None:
        """Return total time in minutes."""
        return None

    @property
    def servings(self) -> int | None:
        """Return servings/yield as an integer."""
        return None

    @property
    def prep_time_str(self) -> str:
        """Return prep time as HH:MM or M min."""
        return format_time_h_m(self.prep_time)

    @property
    def cook_time_str(self) -> str:
        """Return cook time as HH:MM or M min."""
        return format_time_h_m(self.cook_time)

    @property
    def total_time_str(self) -> str:
        """Return total time as HH:MM or M min."""
        return format_time_h_m(self.total_time)
