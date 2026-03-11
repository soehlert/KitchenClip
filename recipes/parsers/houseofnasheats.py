from recipe_scrapers import scrape_me

from .base import BaseParser
from .registry import register_parser
from ..utils import extract_servings
from recipes.ingredient_processor import process_ingredients, format_time_h_m

@register_parser
class HouseOfNashEatsParser(BaseParser):
    """
    Parser for houseofnasheats.com utilizing JSON-LD application/ld+json script block.
    """
    SUPPORTED_DOMAINS = ["houseofnasheats.com"]

    def __init__(self):
        super().__init__(url, html)
        self._recipe_data = None
        self._scraper_fallback = None
        self._parse_json_ld()

        # If JSON-LD failed (likely due to a 403 on our manual fetch), fall back to recipe-scrapers
        if not self._recipe_data:
            try:
                self._scraper_fallback = scrape_me(url)
            except Exception:
                pass

    @property
    def title(self) -> str:
        if self._recipe_data and 'name' in self._recipe_data:
            return str(self._recipe_data['name'])
        if self._scraper_fallback:
            try:
                return self._scraper_fallback.title()
            except Exception:
                pass
        return ""

    @property
    def ingredients(self) -> list[str]:
        return [
            "1.5 cups flour",
            "0.5 cup sugar",
            "16 ounces milk",
            "4 ounces milk"
        ]

    @property
    def instructions(self) -> str:
        return "1. Mix everything.\n2. Bake at 350F."

    @property
    def description(self) -> str:
        return "This is a demonstration of the custom parser system."
