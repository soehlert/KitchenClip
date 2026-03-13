# The Ultimate KitchenClip Recipe Parser Guide

This guide is the complete resource for anyone looking to build, debug, or understand recipe parsers in KitchenClip. It covers discovery, the automated inheritance architecture, and the detailed data lifecycle from URL to database.

---

## 1. Discovery: Finding the Data (JSON-LD)

Before writing any code, you need to see if the website provides "machine-readable" data. Most recipe sites use **JSON-LD** (Linked Data).

### How to Find JSON-LD:
1.  **View Source**: Right-click on a recipe page and select "View Page Source".
2.  **Search**: Search for `application/ld+json`.
3.  **Inspect**: Look for a `<script>` tag that contains a JSON object with `"@type": "Recipe"`.

### Mapping Chart: JSON-LD to KitchenClip
When you find the JSON, you map its keys to these parser properties (handled automatically by `BaseParser`):

| Component | JSON-LD Key (Standard) | KitchenClip Property | Notes |
| :--- | :--- | :--- | :--- |
| **Title** | `name` | `title` | |
| **Body** | `description` | `description` | |
| **Image** | `image` | `image_url` | Can be a String, List, or Dict with a `url` key. |
| **Times** | `prepTime`, `cookTime` | `prep_time`, `cook_time` | Usually ISO 8601 (e.g., `PT15M` = 15 mins). |
| **Yield** | `recipeYield` | `servings` | e.g., "4", "4 servings", or `["4"]`. |
| **List** | `recipeIngredient` | `ingredients` | **Crucial**: Return a list of RAW strings. |
| **Steps** | `recipeInstructions` | `instructions` | Often a list of `HowToStep` objects. |

---

## 2. Selection

When you click "Import Recipe", KitchenClip uses a **Factory Method**.

### Logic Flow in `ParserRegistry.get_parser(url)`:
1.  **Domain Extraction**: It strips the URL to its base domain (e.g., `allrecipes.com`).
2.  **Registration Check**: It iterates through `_parsers` (all classes using the `@register_parser` decorator).
3.  **Domain Matching**: It checks `SUPPORTED_DOMAINS` in each class. If it finds a match, it **instantiates** that specific parser.
4.  **Fallback**: If no custom parser matches, it returns a `ScrapersParser` (a catch-all 3rd-party scraper).

---

## 3. Extraction: The Automated Lifecycle

KitchenClip uses an inheritance-based architecture where `BaseParser` handles the heavy lifting.

### The Standard Parser Example
```python
from .base import BaseParser
from .registry import register_parser

@register_parser
class MyNewParser(BaseParser):
    SUPPORTED_DOMAINS = ["example.com"]
```

### The Function Call Stack:
1.  **`BaseParser.__init__`**: 
    - Fetches the HTML from the web using `httpx`.
    - calls **`self._get_json_ld_data()`**: Searches `<script>` tags for `"@type": "Recipe"`. result maps to `self._recipe_data`.
    - calls **`self._setup_scraper_fallback()`**: If JSON-LD is missing, it initializes `recipe-scrapers`.
2.  **Property Access**: When the system needs a title, it calls `parser.title`.
    - `BaseParser.title` checks `self._recipe_data.get('name')`.
    - If empty, it checks `self._scraper.title()`.

---

## 4. Advanced: Overriding Defaults

If a site is truly unique, you can still override anything in the parser:

```python
@property
def title(self):
    # Do custom regex or soup parsing here
    return "Custom Title"
```

---

## 5. Processing: The Ingredient Pipeline

This is where raw text becomes structured database entries.

### The Function Call Stack:
1.  **`views.RecipeCreateView.form_valid`**: Loops through the list of raw strings from `parser.ingredients`.
2.  **`ingredient_processor.parse_ingredient_line(line)`**:
    - **Calls `ingredient_slicer.IngredientSlicer(line)`**: This external library breaks "1 cup chopped onions" into `quantity: 1`, `unit: cup`, `food: onions`.
    - **KitchenClip Heuristics**: Our code then fixes common mistakes (e.g., ensuring "1 (15oz) can" doesn't return 15 as the quantity).
3.  **`ingredient_processor.process_ingredients(parsed_list)`**:
    - **Consolidates**: Adds quantities together for duplicate ingredients.
    - **Normalizes/Beautifies**: Converts units (ounces to lbs) and formats numbers (0.5 to ½).
4.  **Database Storage**:
    - `Ingredient.objects.get_or_create(name=name)`
    - `RecipeIngredient.objects.create(...)`

---

## 6. Fallbacks: When it Fails

1.  **No JSON-LD**: `BaseParser` automatically attempts a fallback via `_setup_scraper_fallback`.
2.  **Total Failure**: If `RecipeCreateView` detects that critical fields (title/ingredients) are missing after all attempts, it redirects the user to the **Manual Add** page so they don't lose the data they were trying to import.

---

## 7. Testing: Proving it Works

KitchenClip uses **pytest** for testing. Since the application runs in Docker, you must execute the tests within the container environment.

### 1. How to Run Tests
Because we use `pytest-django`, standard `python manage.py test` will not find our tests. Use this command:

```bash
docker compose exec web pytest recipes/parsers/tests
```

### 2. The Fixture Pattern
Always capture a local fixture to verify your parser offline without hitting the internet:
1.  **Capture**: `curl -L "URL" -o recipes/parsers/tests/fixtures/site_name.html`.
2.  **Mock**: In your test, use the `load_fixture` utility to pass this local HTML to your parser.

### 3. Comprehensive Test Example
A good test ensures every component (title, ingredients, instructions, etc.) is extracted correctly.

```python
from recipes.parsers.my_parser import MyParser

def test_my_parser_parsing(load_fixture):
    # Load the captured local HTML
    html = load_fixture("site_name.html")
    url = "https://example.com/recipe-url/"
    
    # Initialize parser with mock data
    parser = MyParser(url, html)
    
    # 1. Assert Basic Info
    assert parser.title == "Awesome Chocolate Cake"
    assert "best cake ever" in parser.description.lower()
    assert parser.servings == 8
    
    # 2. Assert Ingredients (check count and specific items)
    assert len(parser.ingredients) == 5
    assert "2 cups flour" in parser.ingredients
    assert "1 tsp salt" in parser.ingredients
    
    # 3. Assert Instructions
    assert "Preheat oven to 350F." in parser.instructions
    assert len(parser.instructions.splitlines()) >= 3
    
    # 4. Assert Times (KitchenClip converts ISO 8601 to minutes)
    assert parser.prep_time == 15
    assert parser.cook_time == 45
    assert parser.total_time == 60
    
    # 5. Assert Image URL
    assert "chocolate-cake.jpg" in parser.image_url
```
