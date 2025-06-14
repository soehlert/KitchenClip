import re

from fractions import Fraction

INGREDIENT_STARTERS = [
    "pinch", "dash", "drizzle", "handful", "sprig", "clove", "slice", "piece", "bunch", "can", "bottle", "jar",
    "package", "packet", "stick", "drop", "sheet", "cube", "ear", "fillet", "to taste", "as needed",
    "for serving", "for garnish", "about", "approximately", "a few", "several", "half", "teaspoon", "tsp",
    "tablespoon", "tbsp", "cup", "oz", "ounce", "pound", "lb", "gram", "g", "kilogram", "kg", "liter", "l",
    "milliliter", "ml", "quart", "qt", "pint", "pt", "gallon", "gal"
]

def check_value(val):
    if not val:
        return False
    q = str(val).strip().lower()
    try:
        if float(q) > 0:
            return True
    except ValueError:
        pass
    try:
        if Fraction(q) > 0:
            return True
    except (ValueError, ZeroDivisionError):
        pass
    if q in INGREDIENT_STARTERS:
        return True
    return False

def is_valid_ingredient(quantity, unit, ingredient):
    if check_value(quantity) or check_value(unit):
        return True

    if ingredient:
        i = str(ingredient).strip().lower()
        words = i.split()
        if words and words[0] in INGREDIENT_STARTERS:
            return True
        if len(words) > 1 and f"{words[0]} {words[1]}" in INGREDIENT_STARTERS:
            return True
    return False

def extract_servings(servings_str):
    if not servings_str:
        return None
    for part in servings_str.split():
        try:
            return int(part)
        except ValueError:
            continue
    return None

def clean_instruction_line(text):
    if not text:
        return text

    lines = text.split('\n')
    cleaned_lines = []
    for i, line in enumerate(lines):
        stripped_line = re.sub(r'^[^A-Za-z]+', '', line.strip())
        bullet_free_line = re.sub(r'[•◦▪▫]\s*', '', stripped_line)
        cleaned_line = re.sub(r'\bTIP:\s*', '<strong>TIP:</strong> ', bullet_free_line)

        if cleaned_line:
            cleaned_lines.append(cleaned_line)

    result = '\n'.join(cleaned_lines)
    return result

import re

def remove_instruction_headers(text):
    """Remove common instruction header lines."""
    if not text:
        return text

    header_patterns = [
        r'^instructions?:?\s*$',
        r'^directions?:?\s*$',
        r'^steps?:?\s*$',
        r'^method:?\s*$',
        r'^preparation:?\s*$',
        r'^how to make:?\s*$',
        r'^cooking instructions?:?\s*$'
    ]

    lines = text.split('\n')
    filtered_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        is_header = False
        for pattern in header_patterns:
            if re.match(pattern, line, re.IGNORECASE):
                is_header = True
                break

        if not is_header:
            filtered_lines.append(line)

    return '\n'.join(filtered_lines)
