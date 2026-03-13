import re

from recipes.ingredient_processor import format_time_h_m, process_ingredients
from ..utils import extract_servings
from .base import BaseParser
from .registry import register_parser
from .utils import parse_iso_duration


@register_parser
class LessWithLaurParser(BaseParser):
    """
    Parser for lesswithlaur.com utilizing JSON-LD application/ld+json script block.
    """
    SUPPORTED_DOMAINS = ["lesswithlaur.com"]

    def __init__(self, url: str, html: str | None = None):
        super().__init__(url, html)
        self._recipe_data = None
        self._parse_json_ld()

    def _parse_json_ld(self):
        self._recipe_data = self._get_json_ld_data()

    @property
    def title(self) -> str:
        if self._recipe_data and 'name' in self._recipe_data:
            # HTML entities like &#39; might be present in name
            name = self._recipe_data['name']
            return BeautifulSoup(name, "html.parser").get_text()
        return ""

    @property
    def description(self) -> str:
        if self._recipe_data and 'description' in self._recipe_data:
            desc = self._recipe_data['description']
            return BeautifulSoup(desc, "html.parser").get_text()
        return ""

    @property
    def image_url(self) -> str:
        if not self._recipe_data or 'image' not in self._recipe_data:
            return ""

        img = self._recipe_data['image']
        if isinstance(img, list) and len(img) > 0:
            if isinstance(img[0], str):
                return img[0]
            elif isinstance(img[0], dict) and 'url' in img[0]:
                return img[0]['url']
        elif isinstance(img, dict) and 'url' in img:
            return img['url']
        elif isinstance(img, str):
            return img

        return ""

    @property
    def prep_time(self) -> int | None:
        if self._recipe_data and 'prepTime' in self._recipe_data:
            return parse_iso_duration(self._recipe_data['prepTime'])
        return None

    @property
    def cook_time(self) -> int | None:
        if self._recipe_data and 'cookTime' in self._recipe_data:
            return parse_iso_duration(self._recipe_data['cookTime'])
        return None

    @property
    def total_time(self) -> int | None:
        if self._recipe_data and 'totalTime' in self._recipe_data:
            return parse_iso_duration(self._recipe_data['totalTime'])
        # If totalTime isn't explicitly provided, we could sum prep and cook
        pt = self.prep_time or 0
        ct = self.cook_time or 0
        return pt + ct if pt + ct > 0 else None

    @property
    def servings(self) -> int | None:
        if self._recipe_data and 'recipeYield' in self._recipe_data:
            yield_data = self._recipe_data['recipeYield']
            if isinstance(yield_data, list) and len(yield_data) > 0:
                return extract_servings(str(yield_data[0]))
            return extract_servings(str(yield_data))
        return None

    @property
    def ingredients(self) -> list[str]:
        if not self._recipe_data or 'recipeIngredient' not in self._recipe_data:
            return []

        raw_ingredients = self._recipe_data['recipeIngredient']
        return raw_ingredients

    @property
    def instructions(self) -> str:
        if not self._recipe_data or 'recipeInstructions' not in self._recipe_data:
            return ""

        instructions = self._recipe_data['recipeInstructions']
        result = []

        for step in instructions:
            if isinstance(step, dict):
                text = step.get('text', step.get('name', ''))
            else:
                text = str(step)

            if text:
                # Remove any existing HTML tags
                clean_text = re.sub('<.*?>', '', text).strip()
                result.append(clean_text)

        return "\n".join(result)
