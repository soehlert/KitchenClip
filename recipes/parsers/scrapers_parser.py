import logging
from recipe_scrapers import scrape_me, scrape_html
from .base import BaseParser

logger = logging.getLogger(__name__)
from ..utils import extract_servings, clean_instruction_line

class ScrapersParser(BaseParser):
    """
    Parser that uses the recipe-scrapers library.
    Acts as a fallback for domains without custom parsers.
    """
    
    def __init__(self, url: str, html: str | None = None):
        super().__init__(url, html)
        self.scraper = None
        try:
            # Try recipe-scrapers' custom downloader first (best for JSON-LD/dynamic sites)
            self.scraper = scrape_me(self.url)
        except Exception as e:
            logger.warning(f"ScrapersParser: scrape_me failed for {self.url}: {e}")
            # Fallback to the HTML that BaseParser downloaded with custom headers
            if self.html:
                try:
                    self.scraper = scrape_html(self.html, org_url=self.url)
                    logger.info(f"ScrapersParser: successfully fell back to scrape_html for {self.url}")
                except Exception as e2:
                    logger.error(f"ScrapersParser: scrape_html also failed for {self.url}: {e2}")
            
        if not self.scraper:
            raise ValueError(f"Could not scrape recipe from {self.url}")

    @property
    def title(self) -> str:
        return self.scraper.title()

    @property
    def ingredients(self) -> list[str]:
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
    def prep_time(self) -> int | None:
        return self.scraper.prep_time()

    @property
    def cook_time(self) -> int | None:
        return self.scraper.cook_time()

    @property
    def total_time(self) -> int | None:
        return self.scraper.total_time()

    @property
    def servings(self) -> int | None:
        servings_raw = self.scraper.yields()
        return extract_servings(servings_raw) if servings_raw else None
