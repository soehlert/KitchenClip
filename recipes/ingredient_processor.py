import re
from fractions import Fraction

import ingredient_slicer


def _safe_float(value) -> float:
    """Internal helper to safely convert values to a float."""
    if not value:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0

def _extract_numbers(text: str) -> list[float]:
    """Internal helper to extract all numbers from a string as floats."""
    extracted_floats = []
    # Regex finds digits, optionally followed by a decimal point and more digits
    number_matches = re.findall(r"(\d+(?:\.\d+)?)", text)
    
    for match in number_matches:
        # We can use standard float() here because the regex guarantees it's a valid number format
        extracted_floats.append(float(match))
        
    return extracted_floats


def parse_ingredient_line(line: str) -> dict:
    """
    Centralized parsing for a single ingredient line.
    """
    
    # TODO fix this comment
    # If the line contains "or", we only parse the first half so the slicer
    or_split = re.split(r'(?:\s+|,)\s*or\s+', line, maxsplit=1, flags=re.IGNORECASE)
    if len(or_split) > 1:
        line_to_parse = or_split[0]
        or_remainder = " or " + or_split[1]
    else:
        line_to_parse = line
        or_remainder = ""

    slicer = ingredient_slicer.IngredientSlicer(line_to_parse)
    parsed_item = slicer.to_json()

    # IngredientSlicer often gets confused by weights in parentheses:
    # - Multiplication: 6 eggs (305g) -> quantity=1830
    # - Hijacking: 4 scallions (60g) -> quantity=60
    qty = _safe_float(parsed_item.get("quantity"))
    sec_qty = _safe_float(parsed_item.get("secondary_quantity"))
    
    # Extract "Safe" numbers (outside parentheses) from the parsed half
    line_no_parens = re.sub(r'\(.*?\)', '', line_to_parse)
    safe_nums = _extract_numbers(line_no_parens)
    
    # Extract "Danger" numbers (inside parentheses) from the parsed half
    paren_matches = re.findall(r'\((.*?)\)', line_to_parse)
    danger_nums = []
    for p_content in paren_matches:
        danger_nums.extend(_extract_numbers(p_content))
    
    # RECONCILIATION HEURISTIC:
    # If the parser's quantity is NOT found in the 'Safe' zone but IS found
    # in the 'Danger' zone (either directly or as a product), we revert.
    reverted = False
    if qty > 0 and qty not in safe_nums:
        # Check Case A: Multiplication (6 * 305 = 1830)
        if sec_qty in safe_nums and danger_nums:
            for dn in danger_nums:
                if abs(sec_qty * dn - qty) < 0.1:
                    qty = sec_qty
                    reverted = True
                    break
        
        # Check Case B: Pure Hijacking (4 scallions (60g) -> 60)
        if not reverted and qty in danger_nums and safe_nums:
            # We assume the first safe number is the intended count
            qty = safe_nums[0]
            reverted = True

    # If we reverted, we should also clear any unit that was likely hijacked from the parens
    if reverted:
        u_temp = (parsed_item.get("unit") or "").lower()
        if u_temp and any(u_temp in p_c.lower() for p_c in paren_matches):
            parsed_item["unit"] = ""

    # 1.5 Generic Rogue Unit Heuristics
    # ingredient_slicer has no spatial awareness and will frequently:
    # 1. Hijack unit words from preparation phrases ("seeds and ribs removed" -> unit: ribs)
    # 2. Split compound nouns ("hoagie rolls" -> unit: rolls, food: hoagie)
    u_current = (parsed_item.get("unit") or "").lower().strip()
    food_current = (parsed_item.get("food") or "").strip()
    
    if u_current and food_current:
        # If the unit is already part of the food name ("yellow onion" & "onion"), just clear the unit
        if u_current in food_current.lower().split() or u_current == food_current.lower():
            parsed_item["unit"] = ""
        else:
            u_idx = line_to_parse.lower().find(u_current)
            f_words = food_current.lower().split()
            f_idx = line_to_parse.lower().find(f_words[0]) if f_words else -1
            
            # If the parsed unit appears AFTER the food noun in the raw string...
            if u_idx > f_idx and f_idx != -1:
                # Check if there is a deliberate separation (comma, parenthesis) between them
                text_between = line_to_parse.lower()[f_idx:u_idx]
                if ',' in text_between or '(' in text_between:
                    # Hijacked from prep (e.g. "2 green bell peppers, ... ribs removed")
                    parsed_item["unit"] = ""
                else:
                    # Split noun phrase (e.g. "4 hoagie rolls")
                    # Exception: unless it's a size modifier like "chunks" in "tomatoes, chunks" without comma
                    parsed_item["food"] = f"{food_current} {u_current}".strip()
                    parsed_item["unit"] = ""

    # 2. "Or" Restoration
    food = (parsed_item.get("food") or "").strip()
    if food:
        # Clean rogue "unit"
        food = re.sub(r'\bunit\b', '', food, flags=re.IGNORECASE).strip()
        # Append the "or" remainder we stripped earlier
        if or_remainder:
            food = f"{food}{or_remainder}".strip()
        parsed_item["food"] = food

    # 3. Prep Extraction/Heuristic
    # If prep is empty, try pulling from parentheses (common for "chopped", etc.)
    prep_list = parsed_item.get("prep") or []
    if not prep_list and parsed_item.get("parenthesis_content"):
        prep_list = parsed_item.get("parenthesis_content")
    parsed_item["prep"] = prep_list
    
    # Clean units like "of an onion", "of pepper", etc. and "Unit" string
    u = parsed_item.get("unit") or ""
    if u:
        parsed_item["unit"] = re.sub(r'\b(of|an|a|the|of an|of a|unit)\b', '', u, flags=re.IGNORECASE).strip()

    # Let's ensure quantity is always returned as a float, never a string
    parsed_item["quantity"] = qty
    
    # 4. Filter Junk Headers (e.g. "Ingredients", "Finish")
    # If the quantity is 0 and the food is just a section header, empty it so it gets skipped
    food = parsed_item.get("food", "").lower().strip()
    if qty == 0.0 and food in {"ingredients", "finish", "sauce", "garnish", "for the", "serve with", "to serve", "marinade", "dressing"}:
        parsed_item["food"] = ""
        
    return parsed_item

FRACTION_MAP = {
    0.5: '½', 0.333: '⅓', 0.666: '⅔', 0.25: '¼', 0.75: '¾', 
    0.2: '⅕', 0.4: '⅖', 0.6: '⅗', 0.8: '⅘', 0.166: '⅙', 
    0.833: '⅚', 0.125: '⅛', 0.375: '⅜', 0.625: '⅝', 0.875: '⅞'
}

def decimal_to_fraction(decimal_str: str) -> str:
    """Converts a decimal string to a unicode fraction if possible."""
    try:
        val = float(decimal_str)
        
        # Check standard unicode fractions (allowing slight floating point variance)
        for dec_val, frac_char in FRACTION_MAP.items():
            if abs(val - dec_val) < 0.01:
                return frac_char
        
        # Fallback to Fraction string if it's a simple denominator
        if val > 0 and val < 1:
            f = Fraction(val).limit_denominator(10)
            return f"{f.numerator}/{f.denominator}"
        
        if val.is_integer():
            return str(int(val))
            
        return str(val)
    except (ValueError, TypeError):
        return decimal_str

def normalize_ounces(quantity: float, unit: str) -> (float, str):
    """Converts ounces to lbs and oz if > 16."""
    unit_lower = unit.lower()
    if unit_lower in ['oz', 'ounce', 'ounces'] and quantity >= 16:
        lbs = int(quantity // 16)
        remaining_oz = quantity % 16
        if remaining_oz == 0:
            return lbs, "lb"
        return quantity, unit
    return quantity, unit

def format_quantity(quantity: float | str) -> str:
    """Formats a float as a string or fraction, including mixed numbers."""
    try:
        if isinstance(quantity, str):
            quantity = float(quantity)
    except (ValueError, TypeError):
        return str(quantity)

    if quantity == 0.0:
        return ""
    if hasattr(quantity, 'is_integer') and quantity.is_integer():
        return str(int(quantity))
    
    whole = int(quantity)
    fractional = quantity - whole
    
    # We pass the float string to decimal_to_fraction.
    # It will either return a unicode character or fallback to the string format.
    frac_str = decimal_to_fraction(str(round(fractional, 3)))
    
    if whole > 0:
        if "/" in frac_str or frac_str in FRACTION_MAP.values():
            return f"{whole}{frac_str}"
        return str(round(quantity, 3))
    return frac_str

def process_ingredients(parsed_ingredients: list[dict[str, any]]) -> list[dict[str, any]]:
    """
    Consolidates identical ingredients and normalizes quantities/units.
    Each dict in parsed_ingredients should have: quantity, unit, food.
    """
    consolidated = {}

    for item in parsed_ingredients:
        food = (item.get("food") or "").strip().lower()
        if not food:
            continue
            
        unit = (item.get("unit") or "").strip().lower()
        
        # Quantity is now guaranteed to be a float or converted to float
        raw_quantity = item.get("quantity", 0.0)
        try:
            if isinstance(raw_quantity, str):
                quantity = float(raw_quantity)
            else:
                quantity = float(raw_quantity)
        except (ValueError, TypeError):
            quantity = 0.0

        # Create a unique key for grouping (food + unit + prep)
        prep_val = item.get("prep") or ""
        if isinstance(prep_val, list):
            prep = ", ".join(prep_val).strip().lower()
        else:
            prep = str(prep_val).strip().lower()
        key = (food, unit, prep)
        
        if key in consolidated:
            consolidated[key]["quantity"] += quantity
        else:
            consolidated[key] = {
                "food": food,
                "unit": unit,
                "quantity": quantity,
                "prep": prep,
            }

    # Second pass: normalize and format
    results = []
    for key, data in consolidated.items():
        q = data["quantity"]
        u = data["unit"]
        f = data["food"]
        
        # Prevent unit/food redundancy (e.g., unit "onion" & food "yellow onion")
        if u and f and (set(u.split()) & set(f.split())):
            u = ""
        
        display_q = format_quantity(q)
        
        # Normalize Ounces to Lbs
        if u in ['oz', 'ounce', 'ounces'] and q >= 16:
            lbs = int(q // 16)
            remain = q % 16
            if remain == 0:
                display_q = str(lbs)
                u = "lb" if lbs == 1 else "lbs"
            else:
                remain_fmt = format_quantity(remain)
                # For display we combine them
                display_q = f"{lbs} lb {remain_fmt}"
                u = "oz"

        results.append({
            "food": f.capitalize(),
            "unit": u,
            "quantity": q,
            "display_quantity": display_q,
            "prep": data.get("prep", "")
        })
        
    return results

def format_time_h_m(minutes: int | None) -> str:
    """Format minutes into HH:MM."""
    if minutes is None:
        return ""
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours:02d}:{mins:02d}"
    