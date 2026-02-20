from typing import List, Optional
from recipe_scrapers import scrape_me
from .base import BaseParser
from ..utils import extract_servings, clean_instruction_line

class ScrapersParser(BaseParser):
    """
    Parser that uses the recipe-scrapers library.
    Acts as a fallback for domains without custom parsers.
    """
    
    def __init__(self, url: str, html: Optional[str] = None):
        super().__init__(url, html)
        self.scraper = scrape_me(url)

    @property
    def title(self) -> str:
        return self.scraper.title()

    @property
    def ingredients(self) -> List[str]:
        return self.scraper.ingredients()

    @property
    def instructions(self) -> str:
        raw_instructions = self.scraper.instructions()
        return clean_instruction_line(raw_instructions)

    @property
    def description(self) -> str:
        return getattr(self.scraper, "description", lambda: "")()

    @property
    def image_url(self) -> str:
        return getattr(self.scraper, "image", lambda: "")()

    @property
    def prep_time(self) -> Optional[int]:
        return self.scraper.prep_time()

    @property
    def cook_time(self) -> Optional[int]:
        return self.scraper.cook_time()

    @property
    def total_time(self) -> Optional[int]:
        return self.scraper.total_time()

    @property
    def servings(self) -> Optional[str]:
        servings_raw = self.scraper.yields()
        return str(extract_servings(servings_raw)) if servings_raw else None
