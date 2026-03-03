import pytest
import re
import ingredient_slicer
from recipes.ingredient_processor import process_ingredients

def parse_with_logic(line):
    # This simulates the logic currently in reparse_recipes.py
    slicer = ingredient_slicer.IngredientSlicer(line)
    parsed_item = slicer.to_json()

    # Clean "unit" out of food name (the logic in reparse_recipes.py)
    food = (parsed_item.get("food") or "").strip()
    if food:
        # NEW LOGIC: Restore "or" if it was stripped from the food name
        original_lower = line.lower()
        if " or " in original_lower and " or " not in food.lower():
            food_words = food.lower().split()
            if len(food_words) >= 2:
                for i in range(1, len(food_words)):
                    before = " ".join(food_words[:i])
                    after = " ".join(food_words[i:])
                    candidate = f"{before} or {after}"
                    if candidate in original_lower:
                        food = candidate
                        break

        food = re.sub(r'\bunit\b', '', food, flags=re.IGNORECASE).strip()
        parsed_item["food"] = food
    
    # Extract prep information
    prep_list = parsed_item.get("prep") or []
    if not prep_list and parsed_item.get("parenthesis_content"):
        prep_list = parsed_item.get("parenthesis_content")
    
    parsed_item["prep"] = ", ".join(prep_list) if prep_list else ""
    return parsed_item

def test_or_conjunction_restoration_simulation():
    """
    Test that 'or' is preserved in the food name.
    Currently, this test is expected to FAIL until we apply the fix.
    """
    line = "Tortilla chips or crackers"
    parsed = parse_with_logic(line)
    
    # This is where it currently fails:
    # Parsed['food'] becomes 'tortilla chips crackers'
    
    # We want it to be 'tortilla chips or crackers'
    assert " or " in parsed["food"].lower()

def test_process_ingredients_with_or():
    """Test that process_ingredients correctly handles the restored 'or'."""
    parsed_items = [
        {
            "food": "tortilla chips or crackers",
            "unit": "crackers", # This is what ingredient-slicer often does
            "quantity": 1.0,
            "prep": ""
        }
    ]
    results = process_ingredients(parsed_items)
    # The current process_ingredients logic removes the unit if it's in the food name
    # u_words = "crackers".split() -> ["crackers"]
    # f_words = "tortilla chips or crackers".split() -> ["tortilla", "chips", "or", "crackers"]
    # "crackers" in f_words -> unit becomes ""
    
    assert results[0]["food"] == "Tortilla chips or crackers"
    assert results[0]["unit"] == ""

def test_process_ingredients_with_prep_list():
    """Test that process_ingredients correctly handles a list of preparation strings."""
    parsed_items = [
        {
            "food": "onion",
            "unit": "unit",
            "quantity": 1.0,
            "prep": ["chopped", "diced"]
        }
    ]
    results = process_ingredients(parsed_items)
    assert results[0]["prep"] == "chopped, diced"
