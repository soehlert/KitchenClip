import json
import logging
import re

from recipes.ingredient_processor import (parse_ingredient_line,
                                          process_ingredients)

from .base import BaseParser
from .registry import register_parser
from .utils import get_soup, parse_iso_duration

logger = logging.getLogger(__name__)

@register_parser
class HouseOfNashEatsParser(BaseParser):
    """
    Parser for houseofnasheats.com.
    """
    SUPPORTED_DOMAINS = ["houseofnasheats.com"]

    def __init__(self, url: str, html: str | None = None):
        super().__init__(url, html)
        self._recipe_data = self._parse_json_ld()

    def _parse_json_ld(self) -> dict | None:
        if not self.html:
            logger.warning(f"HouseOfNashEatsParser: No HTML content to parse for {self.url}")
            return None

        soup = get_soup(self.html)
        scripts = soup.find_all("script", type="application/ld+json")
        logger.debug(f"HouseOfNashEatsParser: Found {len(scripts)} JSON-LD scripts")

        for script in scripts:
            try:
                data = json.loads(script.string)
                
                items = []
                if isinstance(data, dict):
                    if "@graph" in data:
                        items.extend(data["@graph"])
                    else:
                        items.append(data)
                elif isinstance(data, list):
                    items.extend(data)

                for item in items:
                    if not isinstance(item, dict):
                        continue
                    
                    item_type = item.get("@type")
                    # Handle string, list, or absolute schema.org URL
                    types = item_type if isinstance(item_type, list) else [item_type]
                    types = [str(t).lower().replace("https://schema.org/", "").replace("http://schema.org/", "") for t in types if t]
                    
                    if "recipe" in types:
                        logger.info(f"HouseOfNashEatsParser: Successfully found Recipe in JSON-LD for {self.url}")
                        return item
                    else:
                        logger.debug(f"HouseOfNashEatsParser: Item type(s) {types} did not match 'Recipe'")
            except (json.JSONDecodeError, TypeError) as e:
                logger.debug(f"HouseOfNashEatsParser: Error decoding JSON script: {e}")
                continue
        
        logger.warning(f"HouseOfNashEatsParser: Could not find Recipe data in JSON-LD for {self.url}")
        return None

    @property
    def title(self) -> str:
        if self._recipe_data:
            return self._recipe_data.get("name", "")
        soup = get_soup(self.html)
        return soup.title.string if soup.title else ""

    @property
    def ingredients(self) -> list[str]:
        if not self._recipe_data:
            return []
        
        raw_ingredients = self._recipe_data.get("recipeIngredient", [])
        logger.debug(f"HouseOfNashEatsParser: Found {len(raw_ingredients)} raw ingredients")
        parsed_ingredients = []
        for ing_str in raw_ingredients:
            try:
                parsed_item = parse_ingredient_line(str(ing_str))
                parsed_ingredients.append(parsed_item)
            except Exception as e:
                logger.error(f"HouseOfNashEatsParser: Error parsing ingredient '{ing_str}': {e}")
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

    def _extract_steps(self, items: list) -> list[str]:
        """Private helper to recursively extract instruction text."""
        extracted = []
        for item in items:
            if isinstance(item, dict):
                if item.get("@type") == "HowToStep":
                    extracted.append(item.get("text", ""))
                elif item.get("@type") == "HowToSection":
                    extracted.extend(self._extract_steps(item.get("itemListElement", [])))
            elif isinstance(item, str):
                extracted.append(item)
        return extracted

    @property
    def instructions(self) -> str:
        if not self._recipe_data:
            return ""
        
        steps = self._recipe_data.get("recipeInstructions", [])
        instruction_list = []
        
        if isinstance(steps, list):
            instruction_list = self._extract_steps(steps)
        elif isinstance(steps, str):
            instruction_list.append(steps)
            
        logger.debug(f"HouseOfNashEatsParser: Extracted {len(instruction_list)} instruction steps")
        return "\n".join(filter(None, instruction_list))

    @property
    def servings(self) -> int | None:
        if not self._recipe_data:
            return None
        
        yield_data = self._recipe_data.get("recipeYield", "")
        if isinstance(yield_data, list):
            yield_str = str(yield_data[0]) if yield_data else ""
        else:
            yield_str = str(yield_data)

        match = re.search(r"(\d+)", yield_str)
        if match:
            return int(match.group(1))
        return None

    @property
    def prep_time(self) -> int | None:
        return parse_iso_duration(self._recipe_data.get("prepTime")) if self._recipe_data else None

    @property
    def cook_time(self) -> int | None:
        return parse_iso_duration(self._recipe_data.get("cookTime")) if self._recipe_data else None

    @property
    def total_time(self) -> int | None:
        return parse_iso_duration(self._recipe_data.get("totalTime")) if self._recipe_data else None

    @property
    def description(self) -> str:
        if not self._recipe_data:
            return ""
        return self._recipe_data.get("description", "")

    @property
    def image_url(self) -> str:
        if not self._recipe_data:
            return ""
        
        image_data = self._recipe_data.get("image")
        if not image_data:
            return ""

        # Handle list of images
        if isinstance(image_data, list):
            image_item = image_data[0] if image_data else ""
        else:
            image_item = image_data
            
        # Handle ImageObject or string
        if isinstance(image_item, dict):
            # Try to get 'url' or 'contentUrl'
            return image_item.get("url") or image_item.get("contentUrl") or ""
            
        return str(image_item)
