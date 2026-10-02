import re
from fractions import Fraction

INGREDIENT_STARTERS = [
    "pinch", "dash", "drizzle", "handful", "sprig", "clove", "slice", "piece", "bunch", "can", "bottle", "jar",
    "package", "packet", "stick", "drop", "sheet", "cube", "ear", "fillet", "to taste", "as needed",
    "for serving", "for garnish", "about", "approximately", "a few", "several", "half", "teaspoon", "tsp",
    "tablespoon", "tbsp", "cup", "oz", "ounce", "pound", "lb", "gram", "g", "kilogram", "kg", "liter", "l",
    "milliliter", "ml", "quart", "qt", "pint", "pt", "gallon", "gal"
]

UNICODE_FRACTIONS_CHARS = {
    '½', '⅓', '⅔', '¼', '¾', '⅕', '⅖', '⅗', '⅘', '⅙', '⅚', '⅛', '⅜', '⅝', '⅞'
}

def check_value(val):
    if not val:
        return False
    q = str(val).strip().lower()
    
    # Check for unicode fractions
    if any(char in q for char in UNICODE_FRACTIONS_CHARS):
        return True

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

def is_valid_ingredient(quantity, unit, ingredient, raw_text=None):
    if check_value(quantity) or check_value(unit):
        return True

    # If we have no quantity/unit, check if the raw text even started with a number or unit
    if raw_text:
        text = str(raw_text).strip()
        if text:
            first_word = text.split()[0].lower()
            # If the first word doesn't have a digit and isn't a known unit/starter,
            # then it's likely just a named ingredient like "Salt" or "Tortilla chips" 
            # and we are "confident" even without a quantity.
            is_numeric = any(char.isdigit() for char in first_word)
            is_fraction = any(char in UNICODE_FRACTIONS_CHARS for char in first_word)
            if not is_numeric and not is_fraction and first_word not in INGREDIENT_STARTERS:
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

def remove_instruction_headers(text: str) -> str:
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
            filtered_lines.append('')
            continue

        is_header = False
        for pattern in header_patterns:
            if re.match(pattern, line, re.IGNORECASE):
                is_header = True
                break

        if not is_header:
            filtered_lines.append(line)

    return '\n'.join(filtered_lines)


STEP_MARKER_REGEX = re.compile(
    r'^(?:(?:Step\s+\d+[:.)\-]*\s*)|(?:\(?\d+[.)\]]\s*)|(?:\(?\d+\s*[:-]\s+)|(?:[•◦▪▫*–—\-]\s+))',
    re.IGNORECASE,
)
DANGLING_ENDINGS = (',', ';', '-', '—', '–', '(', '[')
DANGLING_WORDS = {'and', 'or', 'with', 'in', 'to', 'for', 'of', 'if', 'the', 'a', 'an', 'as', 'at', 'by', 'from'}


BOLD_HTML_TAGS_REGEX = re.compile(r'</?(?:strong|b)[^>]*>', re.IGNORECASE)


def strip_bold_tags(text: str) -> str:
    """Remove strong and b HTML tags and collapse whitespace."""
    if not text:
        return ""
    no_bold = BOLD_HTML_TAGS_REGEX.sub('', text)
    return re.sub(r'[ \t]+', ' ', no_bold).strip()


def parse_instruction_steps(text: str) -> list[str]:
    """Parse raw instruction text into a list of coherent steps."""
    if not text or not text.strip():
        return []

    cleaned = remove_instruction_headers(text)
    cleaned = BOLD_HTML_TAGS_REGEX.sub('', cleaned)
    raw_lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in cleaned.splitlines() if line.strip()]
    if not raw_lines:
        return []

    # 1. Marker-based grouping (bullets or numbered items)
    has_markers = any(STEP_MARKER_REGEX.match(line) for line in raw_lines)
    if has_markers:
        steps = []
        current_step_parts: list[str] = []
        pending_marker = None

        for line in raw_lines:
            if STEP_MARKER_REGEX.match(line):
                if current_step_parts:
                    step_text = re.sub(r'[ \t]+', ' ', ' '.join(current_step_parts)).strip()
                    if step_text:
                        steps.append(step_text)
                    current_step_parts = []
                    pending_marker = None
                elif pending_marker:
                    steps.append(pending_marker)
                    pending_marker = None

                cleaned_line = line
                while STEP_MARKER_REGEX.match(cleaned_line):
                    subbed = STEP_MARKER_REGEX.sub('', cleaned_line, count=1).strip()
                    if not subbed:
                        break
                    cleaned_line = subbed

                if cleaned_line:
                    current_step_parts.append(cleaned_line)
                else:
                    pending_marker = line
            else:
                pending_marker = None
                current_step_parts.append(line)

        if current_step_parts:
            step_text = re.sub(r'[ \t]+', ' ', ' '.join(current_step_parts)).strip()
            if step_text:
                steps.append(step_text)
        elif pending_marker:
            steps.append(pending_marker)
        return steps

    # 2. Blank-line / paragraph-based grouping
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n+', cleaned) if p.strip()]
    if len(paragraphs) > 1:
        steps = []
        for p in paragraphs:
            step_text = ' '.join(p.split())
            if step_text:
                steps.append(step_text)
        return steps

    # 3. Sentence-continuation heuristic for unmarked wrapped text
    steps = []
    current_step_parts = []
    for line in raw_lines:
        is_continuation = False
        if current_step_parts:
            prev_line = current_step_parts[-1]
            if line[0].islower() or line[0] in '([{}])':
                is_continuation = True
            elif prev_line.endswith(DANGLING_ENDINGS):
                is_continuation = True
            else:
                last_word = prev_line.split()[-1].lower() if prev_line.split() else ''
                last_word = re.sub(r'[^a-z]', '', last_word)
                if last_word in DANGLING_WORDS:
                    is_continuation = True

        if is_continuation:
            current_step_parts.append(line)
        else:
            if current_step_parts:
                step_text = re.sub(r'[ \t]+', ' ', ' '.join(current_step_parts)).strip()
                if step_text:
                    steps.append(step_text)
            current_step_parts = [line]

    if current_step_parts:
        step_text = re.sub(r'[ \t]+', ' ', ' '.join(current_step_parts)).strip()
        if step_text:
            steps.append(step_text)

    return steps


def clean_instruction_line(text: str) -> str:
    """Clean instruction text into a newline-separated string of steps."""
    if not text:
        return text
    steps = parse_instruction_steps(text)
    return '\n'.join(steps) if steps else text
