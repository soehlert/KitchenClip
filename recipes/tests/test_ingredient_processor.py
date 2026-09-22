import re

import ingredient_slicer

from recipes.ingredient_processor import (parse_ingredient_line,
                                          process_ingredients)


def parse_with_logic(line):
    # This simulates the logic currently in reparse_recipes.py
    slicer = ingredient_slicer.IngredientSlicer(line)
    parsed_item = slicer.to_json()

    # Clean "unit" out of food name (the logic in reparse_recipes.py)
    food = (parsed_item.get("food") or "").strip()
    if food:
        # Restore "or" if it was stripped from the food name
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
    
    assert results[0]["food"] == "tortilla chips or crackers"
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

def test_parse_ingredient_line_metric_multiplier_fix():
    """Test the heuristic that reverses rogue metric multiplication."""
    
    # 6 eggs (305g) -> 1830g is what Slicer usually produces
    line = "6 large eggs (305g)"
    parsed = parse_ingredient_line(line)
    
    # Should be reverted to 6
    assert float(parsed["quantity"]) == 6.0
    # Unit should be cleared since 'g' was from the parens
    assert parsed["unit"] == ""
    assert parsed["food"] == "eggs"

def test_parse_ingredient_line_clove_fix():
    """Test cloves with metric mass in parentheses."""
    line = "2 cloves garlic (10g)"
    parsed = parse_ingredient_line(line)
    
    assert float(parsed["quantity"]) == 2.0
    assert parsed["unit"] == "cloves"
    assert parsed["food"] == "garlic"
    processed = process_ingredients([parsed])
    assert processed[0]["display_quantity"] == "2"
    assert processed[0]["unit"] == "cloves"
    assert processed[0]["food"] == "garlic"
    assert processed[0]["prep"] == "10 g"


def test_garlic_cloves_parsing_and_pluralization():
    """Test singular/plural normalization for garlic cloves across variations."""
    # 2 clove garlic -> pluralized to 'cloves'
    two_clove = parse_ingredient_line("2 clove garlic")
    assert float(two_clove["quantity"]) == 2.0
    assert two_clove["unit"] == "clove"
    assert two_clove["food"] == "garlic"
    proc_two = process_ingredients([two_clove])
    assert proc_two[0]["display_quantity"] == "2"
    assert proc_two[0]["unit"] == "cloves"
    assert proc_two[0]["food"] == "garlic"

    # 1 clove garlic -> remains singular 'clove'
    one_clove = parse_ingredient_line("1 clove garlic")
    assert float(one_clove["quantity"]) == 1.0
    assert one_clove["unit"] == "clove"
    assert one_clove["food"] == "garlic"
    proc_one = process_ingredients([one_clove])
    assert proc_one[0]["display_quantity"] == "1"
    assert proc_one[0]["unit"] == "clove"
    assert proc_one[0]["food"] == "garlic"

    # 2 garlic cloves -> unit extracted from suffix
    suffix_cloves = parse_ingredient_line("2 garlic cloves")
    assert float(suffix_cloves["quantity"]) == 2.0
    assert suffix_cloves["unit"] == "cloves"
    assert suffix_cloves["food"] == "garlic"
    proc_suffix = process_ingredients([suffix_cloves])
    assert proc_suffix[0]["display_quantity"] == "2"
    assert proc_suffix[0]["unit"] == "cloves"
    assert proc_suffix[0]["food"] == "garlic"


def test_meal_kit_unit_resolution():
    """Test resolution of meal kit 'unit' markers into sensible units."""
    lettuce = parse_ingredient_line("1 unit Baby lettuce")
    assert lettuce["unit"] == "head"
    assert "baby lettuce" in lettuce["food"].lower()

    stock = parse_ingredient_line("1 unit Beef stock concentrate")
    assert stock["unit"] == "packet"
    assert "beef stock concentrate" in stock["food"].lower()

    ketchup = parse_ingredient_line("1 unit Ketchup")
    assert ketchup["unit"] == "packet"
    assert "ketchup" in ketchup["food"].lower()

    cilantro = parse_ingredient_line("1 unit Cilantro")
    assert cilantro["unit"] == "bunch"

    spring_mix = parse_ingredient_line("1 unit Spring mix")
    assert spring_mix["unit"] == "bag"

    tomato = parse_ingredient_line("1 unit Tomato")
    assert tomato["unit"] == ""
    assert "tomato" in tomato["food"].lower()

    pickle = parse_ingredient_line("1 unit Dill pickle (sliced)")
    assert pickle["unit"] == ""
    assert "dill pickle" in pickle["food"].lower()

    # Produce and whole items default to empty unit (count)
    scallions = parse_ingredient_line("2 unit Scallions")
    assert scallions["unit"] == ""
    assert "scallions" in scallions["food"].lower()

    zucchini = parse_ingredient_line("1 unit Zucchini")
    assert zucchini["unit"] == ""
    assert "zucchini" in zucchini["food"].lower()

    jalapeno = parse_ingredient_line("1 unit Jalapeño")
    assert jalapeno["unit"] == ""
    assert "jalapeño" in jalapeno["food"].lower()

    # Heads
    broccoli = parse_ingredient_line("1 unit Broccoli")
    assert broccoli["unit"] == "head"
    assert "broccoli" in broccoli["food"].lower()

    cauliflower = parse_ingredient_line("1 unit Cauliflower")
    assert cauliflower["unit"] == "head"
    assert "cauliflower" in cauliflower["food"].lower()


def test_pouch_and_packet_recognition():
    """Test first-class recognition of pouch and packet units."""
    pouch1 = parse_ingredient_line("1 pouch beef stock concentrate")
    assert pouch1["unit"] == "pouch"
    assert pouch1["food"].lower() == "beef stock concentrate"

    pouch2 = parse_ingredient_line("2 pouches beef stock concentrate")
    assert pouch2["unit"] == "pouches"
    assert pouch2["food"].lower() == "beef stock concentrate"

    packet = parse_ingredient_line("1 packet Southwest spice blend")
    assert packet["unit"] == "packet"
    assert "southwest spice" in packet["food"].lower()


def test_unit_pluralization_in_process_ingredients():
    """Test that units are pluralized when quantity > 1."""
    items = [
        {"food": "mayonnaise", "unit": "tablespoon", "quantity": 2.0},
        {"food": "beef", "unit": "ounce", "quantity": 10.0},
        {"food": "fry seasoning", "unit": "tablespoon", "quantity": 1.0},
    ]
    processed = process_ingredients(items)
    by_food = {p["food"].lower(): p for p in processed}
    assert by_food["mayonnaise"]["unit"] == "tablespoons"
    assert by_food["beef"]["unit"] == "ounces"
    assert by_food["fry seasoning"]["unit"] == "tablespoon"

