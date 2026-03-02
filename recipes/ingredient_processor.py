from fractions import Fraction
import re   

def decimal_to_fraction(decimal_str: str) -> str:
    """Converts a decimal string to a unicode fraction if possible."""
    try:
        val = float(decimal_str)
        if val == 0.25:
            return "¼"
        if val == 0.5:
            return "½"
        if val == 0.75:
            return "¾"
        if val == 0.33:
            return "⅓"
        if val == 0.66:
            return "⅔"
        if val == 0.125:
            return "⅛"
        
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

def format_quantity(quantity: float) -> str:
    """Formats a float as a string or fraction, including mixed numbers."""
    if quantity == 0:
        return ""
    if quantity.is_integer():
        return str(int(quantity))
    
    whole = int(quantity)
    fractional = quantity - whole
    
    frac_str = decimal_to_fraction(str(round(fractional, 3)))
    
    if whole > 0:
        if "/" in frac_str or frac_str in ["¼", "½", "¾", "⅓", "⅔", "⅛"]:
            return f"{whole}{frac_str}"
        return str(quantity)
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
        
        # Clean units like "of an onion", "of pepper", etc. and "Unit" string
        unit = re.sub(r'\b(of|an|a|the|of an|of a|unit)\b', '', unit, flags=re.IGNORECASE).strip()
        
        quantity_str = str(item.get("quantity") or "0")
        
        try:
            quantity = float(QuantityConverter.to_float(quantity_str))
        except Exception:
            quantity = 0.0

        # Create a unique key for grouping (food + unit)
        key = (food, unit)
        
        if key in consolidated:
            consolidated[key]["quantity"] += quantity
        else:
            consolidated[key] = {
                "food": food,
                "unit": unit,
                "quantity": quantity,
            }

    # Second pass: normalize and format
    results = []
    for key, data in consolidated.items():
        q = data["quantity"]
        u = data["unit"]
        f = data["food"]
        
        # Prevent "onion onion" redundancy or "onion yellow onion"
        # If the unit is a word already present in the food name, we drop it.
        if u and f:
            u_words = u.split()
            f_words = f.lower().split()
            # If all words in the unit are already in the food name, clear the unit
            if all(uw in f_words or uw == f.lower() for uw in u_words):
                u = ""
            elif u in f.lower() or f.lower() in u:
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
            "display_quantity": display_q
        })
        
    return results

class QuantityConverter:
    UNICODE_FRACTIONS = {
        '½': 0.5, '⅓': 0.333, '⅔': 0.666, '¼': 0.25, '¾': 0.75, '⅕': 0.2, '⅖': 0.4, '⅗': 0.6, '⅘': 0.8,
        '⅙': 0.166, '⅚': 0.833, '⅛': 0.125, '⅜': 0.375, '⅝': 0.625, '⅞': 0.875
    }

    @staticmethod
    def to_float(val_str: str) -> float:
        if not val_str:
            return 0.0
            
        val_str = val_str.strip()
        
        # Handle unicode fractions
        for char, decimal in QuantityConverter.UNICODE_FRACTIONS.items():
            if char in val_str:
                val_str = val_str.replace(char, f" {decimal}").strip()
                try:
                    parts = val_str.split()
                    return sum(float(p) for p in parts)
                except ValueError:
                    return decimal

        try:
            return float(val_str)
        except ValueError:
            try:
                parts = val_str.split()
                if len(parts) == 2:
                    return float(parts[0]) + float(Fraction(parts[1]))
                return float(Fraction(parts[0]))
            except Exception:
                return 0.0

def format_time_h_m(minutes: int | None) -> str:
    """Format minutes into HH:MM."""
    if minutes is None:
        return ""
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours:02d}:{mins:02d}"

