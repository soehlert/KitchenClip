import json
import logging
import re
from abc import ABC, abstractmethod

import httpx
from bs4 import BeautifulSoup

from recipes.ingredient_processor import format_time_h_m

logger = logging.getLogger(__name__)


class BaseParser(ABC):
    """
    Abstract base class for all recipe parsers.
    Any custom parser should inherit from this and implement the methods.
    """
    
    def __init__(self, url: str):
        self.url = url
        self._recipe_data = {}
        self._scraper = None  # Optional recipe-scrapers instance
        self.html = self._fetch_html(url)
        
        # Perform standard discovery automatically
        self._recipe_data = self._get_json_ld_data()
        self._setup_scraper_fallback()

    def _fetch_html(self, url: str) -> str | None:
        """Fetch HTML content from the URL with robust headers using httpx."""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
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

    def _get_json_ld_data(self, target_type: str = "Recipe") -> dict | None:
        """
        Extract JSON-LD data of a specific type from the HTML.
        Handles both single objects and @graph arrays.
        """
        if not self.html:
            return None

        try:
            soup = BeautifulSoup(self.html, 'html.parser')
            scripts = soup.find_all('script', type='application/ld+json')

            for script in scripts:
                content = script.string if script.string else ""
                if not content:
                    continue
                
                try:
                    data = json.loads(content)
                except json.JSONDecodeError:
                    continue

                # JSON-LD can be a single object, a list of objects, or an @graph array
                blocks = []
                if isinstance(data, list):
                    blocks.extend(data)
                else:
                    blocks.append(data)

                for block in blocks:
                    # Check for @graph
                    if '@graph' in block:
                        for item in block['@graph']:
                            item_type = item.get('@type')
                            if item_type == target_type or (isinstance(item_type, list) and target_type in item_type):
                                return item
                    # Check direct type
                    else:
                        block_type = block.get('@type')
                        if block_type == target_type or (isinstance(block_type, list) and target_type in block_type):
                            return block
            
            return None
        except Exception as e:
            logger.error(f"Error extracting JSON-LD for {self.url}: {e}")
            return None

    def _setup_scraper_fallback(self):
        """Optional helper to initialize recipe-scrapers if needed."""
        if self._scraper:
            return

        try:
            from recipe_scrapers import scrape_me
            if self.html:
                self._scraper = scrape_me(self.url, html=self.html)
            else:
                self._scraper = scrape_me(self.url)
            logger.info(f"Initialized scraper fallback for {self.url}")
        except Exception as e:
            logger.warning(f"Scraper fallback failed for {self.url}: {e}")

    def _get_scraper_val(self, method_name: str, default: any = None) -> any:
        """Safely extract a value from the scraper fallback."""
        if not self._scraper:
            return default
        try:
            method = getattr(self._scraper, method_name)
            val = method()
            return val if val is not None else default
        except Exception:
            return default

    @property
    def title(self) -> str:
        """Return the recipe title from JSON-LD name or scraper fallback."""
        t = ""
        if self._recipe_data and 'name' in self._recipe_data:
            t = BeautifulSoup(str(self._recipe_data['name']), "html.parser").get_text().strip()
        
        if not t:
            t = self._get_scraper_val("title", "")
        
        if t:
            import html
            return html.unescape(t)
        return ""

    @property
    def ingredients(self) -> list[str]:
        """Return a list of raw ingredient strings from JSON-LD or scraper fallback."""
        if self._recipe_data and 'recipeIngredient' in self._recipe_data:
            return self._recipe_data['recipeIngredient']
        
        return self._get_scraper_val("ingredients", [])

    def _extract_steps(self, items: list | dict | str) -> list[str]:
        """Recursive helper to extract instruction text from HowToStep and HowToSection."""
        extracted = []
        if isinstance(items, dict):
            items = [items]
        elif isinstance(items, str):
            items = [items]
            
        if not isinstance(items, list):
            return extracted
            
        for item in items:
            if isinstance(item, dict):
                # Standard HowToStep
                if item.get("@type") == "HowToStep":
                    text = item.get("text", item.get("name", ""))
                    if text:
                        extracted.append(text)
                # Standard HowToSection or nested list
                elif item.get("@type") == "HowToSection" or "itemListElement" in item:
                    element = item.get("itemListElement", [])
                    extracted.extend(self._extract_steps(element))
                else:
                    # Catch-all for dicts with text
                    text = item.get("text", item.get("name", ""))
                    if text:
                        extracted.append(text)
            elif isinstance(item, str):
                extracted.append(item)
        return extracted

    @property
    def instructions(self) -> str:
        """Return instructions from JSON-LD or scraper fallback, cleaned of HTML."""
        instr = ""
        if self._recipe_data and 'recipeInstructions' in self._recipe_data:
            instructions = self._recipe_data['recipeInstructions']
            steps = self._extract_steps(instructions)
            
            result = []
            for text in steps:
                if text:
                    # Remove HTML tags and extra whitespace
                    clean_text = re.sub('<.*?>', '', text).strip()
                    if clean_text:
                        result.append(clean_text)
            instr = "\n".join(result)

        if not instr:
            instr = self._get_scraper_val("instructions", "")
        
        return instr

    @property
    def description(self) -> str:
        """Return a brief description from JSON-LD or scraper fallback."""
        d = ""
        if self._recipe_data and 'description' in self._recipe_data:
            d = BeautifulSoup(str(self._recipe_data['description']), "html.parser").get_text().strip()
        
        if not d:
            d = self._get_scraper_val("description", "")
        return d

    @property
    def image_url(self) -> str:
        """Return the main recipe image URL from JSON-LD or scraper fallback."""
        img_url = ""
        if self._recipe_data and 'image' in self._recipe_data:
            img = self._recipe_data['image']
            # Handle string, list, or dict
            if isinstance(img, list) and len(img) > 0:
                item = img[0]
                if isinstance(item, str):
                    img_url = item
                elif isinstance(item, dict):
                    img_url = item.get('url', item.get('contentUrl', ''))
            elif isinstance(img, dict):
                img_url = img.get('url', img.get('contentUrl', ''))
            elif isinstance(img, str):
                img_url = img

        if not img_url:
            img_url = self._get_scraper_val("image", "")
            
        return img_url

    @property
    def prep_time(self) -> int | None:
        """Return prep time from JSON-LD or scraper fallback."""
        t = None
        if self._recipe_data and 'prepTime' in self._recipe_data:
            from .utils import parse_iso_duration
            t = parse_iso_duration(str(self._recipe_data['prepTime']))
        
        if t is None:
            t = self._get_scraper_val("prep_time", 0)
        return t

    @property
    def cook_time(self) -> int | None:
        """Return cook time from JSON-LD or scraper fallback."""
        t = None
        if self._recipe_data and 'cookTime' in self._recipe_data:
            from .utils import parse_iso_duration
            t = parse_iso_duration(str(self._recipe_data['cookTime']))
        
        if t is None:
            t = self._get_scraper_val("cook_time", 0)
        return t

    @property
    def total_time(self) -> int | None:
        """Return total time from JSON-LD or scraper fallback."""
        t = None
        if self._recipe_data and 'totalTime' in self._recipe_data:
            from .utils import parse_iso_duration
            t = parse_iso_duration(str(self._recipe_data['totalTime']))
        
        if t is None:
            t = self._get_scraper_val("total_time", 0)
        
        if t is not None and t > 0:
            return t

        # Fallback to sum
        pt = self.prep_time or 0
        ct = self.cook_time or 0
        return pt + ct if pt + ct > 0 else 0

    @property
    def servings(self) -> int | None:
        """Return servings from JSON-LD or scraper fallback."""
        s = None
        if self._recipe_data and 'recipeYield' in self._recipe_data:
            from ..utils import extract_servings
            yield_data = self._recipe_data['recipeYield']
            if isinstance(yield_data, list) and len(yield_data) > 0:
                s = extract_servings(str(yield_data[0]))
            else:
                s = extract_servings(str(yield_data))
        
        if s is None:
            y = self._get_scraper_val("yields", "")
            if y:
                from ..utils import extract_servings
                s = extract_servings(str(y))
        
        return s if s is not None else 1

    @property
    def prep_time_str(self) -> str:
        return format_time_h_m(self.prep_time)

    @property
    def cook_time_str(self) -> str:
        return format_time_h_m(self.cook_time)

    @property
    def total_time_str(self) -> str:
        return format_time_h_m(self.total_time)
