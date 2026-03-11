import json
import re

import ingredient_slicer
from bs4 import BeautifulSoup

from recipes.ingredient_processor import format_time_h_m, process_ingredients

from ..utils import extract_servings
from .base import BaseParser
from .registry import register_parser


def parse_iso_duration(duration_str: str) -> int | None:
    if not duration_str:
        return None
    match = re.match(r'P(?:T(?:(\d+)H)?(?:(\d+)M)?)?', duration_str)
    if match:
        hours = int(match.group(1)) if match.group(1) else 0
        minutes = int(match.group(2)) if match.group(2) else 0
        total = hours * 60 + minutes
        return total if total > 0 else None
    return None

@register_parser
class PurelyYumParser(BaseParser):
    """
    Parser for purelyyumrecipes.com utilizing JSON-LD application/ld+json script block.
    """
    SUPPORTED_DOMAINS = ["purelyyumrecipes.com"]

    def __init__(self, url: str, html: str | None = None):
        super().__init__(url, html)
        self._recipe_data = None
        self._parse_json_ld()

    def _parse_json_ld(self):
        if not self.html:
            return
            
        soup = BeautifulSoup(self.html, 'html.parser')
        scripts = soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            try:
                content = script.string if script.string else ""
                data = json.loads(content)
                
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe':
                            self._recipe_data = item
                            return
                elif data.get('@type') == 'Recipe':
                    self._recipe_data = data
                    return
            except json.JSONDecodeError:
                continue

    @property
    def title(self) -> str:
        if self._recipe_data and 'name' in self._recipe_data:
            return self._recipe_data['name']
        return ""

    @property
    def description(self) -> str:
        if self._recipe_data and 'description' in self._recipe_data:
            return self._recipe_data['description']
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
        return None

    @property
    def ingredients(self) -> list[str]:
        if not self._recipe_data or 'recipeIngredient' not in self._recipe_data:
            return []
            
        raw_ingredients = self._recipe_data['recipeIngredient']
        parsed_ingredients = []
        
        for ing_str in raw_ingredients:
            try:
                parsed = ingredient_slicer.IngredientSlicer(ing_str)
                parsed_ingredients.append(parsed.to_json())
            except Exception:
                # Fallback to appending a dummy dict to preserve something or skip
                parsed_ingredients.append({
                    "food": ing_str,
                    "quantity": "0",
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
        if not self._recipe_data or 'recipeInstructions' not in self._recipe_data:
            return ""
            
        instructions = self._recipe_data['recipeInstructions']
        result = []
        
        for step in instructions:
            if isinstance(step, dict):
                text = step.get('text', '')
            else:
                text = str(step)
                
            if text:
                clean_text = re.sub('<.*?>', '', text).strip()
                result.append(clean_text)
                
        return "\n".join(result)
