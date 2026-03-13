import html
import logging
import re

from recipe_scrapers import scrape_me

from recipes.ingredient_processor import (format_time_h_m,
                                          parse_ingredient_line,
                                          process_ingredients)

from ..utils import extract_servings
from .base import BaseParser
from .registry import register_parser
from .utils import parse_iso_duration

logger = logging.getLogger(__name__)


@register_parser
class AllrecipesParser(BaseParser):
    """
    Parser for allrecipes.com utilizing JSON-LD application/ld+json script block.
    """
    SUPPORTED_DOMAINS = ["allrecipes.com"]

    def __init__(self, url: str, html: str | None = None):
        super().__init__(url, html)
        self._recipe_data = None
        self._scraper_fallback = None
        self._parse_json_ld()
        
        # If JSON-LD failed (likely due to a 403 on our manual fetch), fall back to recipe-scrapers
        if not self._recipe_data:
            logger.info(f"JSON-LD extraction failed for {url}, falling back to recipe-scrapers")
            try:
                self._scraper_fallback = scrape_me(url)
            except Exception as e:
                logger.warning(f"recipe-scrapers fallback also failed for {url}: {e}")
                pass
        else:
            logger.info(f"Successfully extracted JSON-LD for {url}")

    def _parse_json_ld(self):
        self._recipe_data = self._get_json_ld_data()

    @property
    def title(self) -> str:
        t = ""
        if self._recipe_data and 'name' in self._recipe_data:
            t = str(self._recipe_data['name'])
        elif self._scraper_fallback:
            try:
                t = self._scraper_fallback.title()
            except Exception:
                pass
        return html.unescape(t) if t else ""

    @property
    def description(self) -> str:
        if self._recipe_data and 'description' in self._recipe_data:
            return str(self._recipe_data['description'])
        if self._scraper_fallback:
            try:
                return self._scraper_fallback.description()
            except Exception:
                pass
        return ""

    @property
    def image_url(self) -> str:
        if not self._recipe_data or 'image' not in self._recipe_data:
            return ""
            
        img = self._recipe_data['image']
        if isinstance(img, list) and len(img) > 0:
            item = img[0]
            if isinstance(item, str):
                return item
            elif isinstance(item, dict) and 'url' in item:
                return item['url']
        elif isinstance(img, dict) and 'url' in img:
            return img['url']
        elif isinstance(img, str):
            return img
            
        return ""

    @property
    def prep_time(self) -> int | None:
        if self._recipe_data and 'prepTime' in self._recipe_data:
            return parse_iso_duration(str(self._recipe_data['prepTime']))
        if self._scraper_fallback:
            try:
                return self._scraper_fallback.prep_time()
            except Exception:
                pass
        return None

    @property
    def cook_time(self) -> int | None:
        if self._recipe_data and 'cookTime' in self._recipe_data:
            return parse_iso_duration(str(self._recipe_data['cookTime']))
        if self._scraper_fallback:
            try:
                return self._scraper_fallback.cook_time()
            except Exception:
                pass
        return None

    @property
    def total_time(self) -> int | None:
        if self._recipe_data and 'totalTime' in self._recipe_data:
            return parse_iso_duration(str(self._recipe_data['totalTime']))
        if self._scraper_fallback:
            try:
                return self._scraper_fallback.total_time()
            except Exception:
                pass
        return None

    @property
    def prep_time_str(self) -> str:
        return format_time_h_m(self.prep_time)

    @property
    def cook_time_str(self) -> str:
        return format_time_h_m(self.cook_time)

    @property
    def total_time_str(self) -> str:
        return format_time_h_m(self.total_time)

    @property
    def servings(self) -> int | None:
        if self._recipe_data and 'recipeYield' in self._recipe_data:
            yield_data = self._recipe_data['recipeYield']
            if isinstance(yield_data, list) and len(yield_data) > 0:
                return extract_servings(str(yield_data[0]))
            return extract_servings(str(yield_data))
        if self._scraper_fallback:
            try:
                y = self._scraper_fallback.yields()
                return extract_servings(str(y)) if y else None
            except Exception:
                pass
        return None

    @property
    def ingredients(self) -> list[str]:
        if self._recipe_data and 'recipeIngredient' in self._recipe_data:
            raw_ingredients = self._recipe_data['recipeIngredient']
        elif self._scraper_fallback:
            try:
                raw_ingredients = self._scraper_fallback.ingredients()
            except Exception:
                return []
        else:
            return []
        parsed_ingredients = []
        
        for ing_str in raw_ingredients:
            try:
                parsed_item = parse_ingredient_line(str(ing_str))
                parsed_ingredients.append(parsed_item)
            except Exception as e:
                logger.error(f"Error parsing ingredient line '{ing_str}': {e}")
                parsed_ingredients.append({
                    "food": str(ing_str),
                    "quantity": 0.0,
                    "unit": ""
                })

        processed = process_ingredients(parsed_ingredients)
        
        final_list = []
        for p in processed:
            dq = p.get("display_quantity", "")
            u = p.get("unit", "")
            f = p.get("food", "")
            
            parts = [str(dq), str(u), str(f)]
            final_list.append(" ".join(part for part in parts if part).strip())

        return final_list

    @property
    def instructions(self) -> str:
        if self._recipe_data and 'recipeInstructions' in self._recipe_data:
            instructions = self._recipe_data['recipeInstructions']
            result = []
            for step in instructions:
                if isinstance(step, dict):
                    text = step.get('text', step.get('name', ''))
                else:
                    text = str(step)
                if text:
                    clean_text = re.sub('<.*?>', '', str(text)).strip()
                    result.append(clean_text)
            return "\n".join(result)
            
        if self._scraper_fallback:
            try:
                return self._scraper_fallback.instructions()
            except Exception:
                pass
        return ""
