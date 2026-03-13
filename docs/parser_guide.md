# The Ultimate KitchenClip Recipe Parser Guide

This guide is the complete resource for anyone looking to build, debug, or understand recipe parsers in KitchenClip. It covers discovery, implementation using shared helpers, and the full data lifecycle.

---

## 1. Discovery: Finding the Data (JSON-LD)

Before writing any code, you need to see if the website provides "machine-readable" data. Most recipe sites use **JSON-LD** (Linked Data).

### How to Find JSON-LD:
1.  **View Source**: Right-click on a recipe page and select "View Page Source".
2.  **Search**: Search for `application/ld+json`.
3.  **Inspect**: Look for a `<script>` tag that contains a JSON object with `"@type": "Recipe"`.

### Mapping Chart: JSON-LD to KitchenClip
When you find the JSON, you map its keys to these parser properties:

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

## 2. Selection: The Factory Pattern

When you click "Import Recipe", KitchenClip uses a **Factory Method**.

> [!NOTE]
> **What is a Factory Method?** 
> It's a design pattern where one central function (`get_parser`) is responsible for deciding exactly which class to create based on the input provided (the URL). You don't have to know which parser to use; the Factory figures it out for you.

### Logic Flow in `ParserRegistry.get_parser(url)`:
1.  **Domain Extraction**: It strips the URL to its base domain (e.g., `lesswithlaur.com`).
2.  **Registration Check**: It iterates through `_parsers` (a list of all classes that used the `@register_parser` decorator).
3.  **Domain Matching**: 
    - Inside each parser class, we define a list of domains it handles: `SUPPORTED_DOMAINS = ["lesswithlaur.com"]`.
    - The registry uses `getattr(parser_class, "SUPPORTED_DOMAINS", [])` to check that list.
    - If it find a match, it **instantiates** that specific parser.
4.  **Fallback**: If no custom parser matches the domain, it returns a `ScrapersParser` (which uses a 3rd-party library as a "catch-all").

---

## 3. Extraction: The Parser Lifecycle & Shared Helpers

KitchenClip provides shared helpers to make writing parsers faster and more reliable.

### BaseParser Helpers
- **`self._get_json_ld_data(target_type="Recipe")`**: This method (defined in `BaseParser`) handles searching all `<script>` tags, parsing JSON, and looking through `@graph` arrays to find the recipe data.

### Utility Helpers
- **`parse_iso_duration(duration_str)`**: (from `.utils`) Converts ISO 8601 durations like `PT1H30M` into a simple integer of total minutes (`90`).

### The Extraction Path:
1.  **`BaseParser.__init__`**: Fetches the HTML from the web using `httpx`.
2.  **`CustomParser._parse_json_ld()`**:
    - Simply calls `self._recipe_data = self._get_json_ld_data()`.
3.  **Property Access**: The system now asks for data. For example:
    - `parser.ingredients` calls `return self._recipe_data.get('recipeIngredient', [])`.

---

## 4. Processing: The Ingredient Pipeline

This is where raw text becomes structured database entries.

### The Function Call Path:
1.  **`views.RecipeCreateView.form_valid`**: Loops through the list of raw strings from `parser.ingredients`.
2.  **`ingredient_processor.parse_ingredient_line(line)`**:
    - **Calls `ingredient_slicer.IngredientSlicer(line)`**: This external library breaks "1 cup chopped onions" into `quantity: 1`, `unit: cup`, `food: onions`.
    - **Applies Heuristics**: Our code then fixes common mistakes (e.g., ensuring "1 (15oz) can" doesn't return 15 as the quantity).
3.  **`ingredient_processor.process_ingredients(parsed_list)`**:
    - **Consolidates**: If two lines both say "salt", it adds the quantities together.
    - **Normalizes**: Converts "32 oz" to "2 lbs".
    - **Beautifies**: Converts `0.5` to `½`.
4.  **Database Storage**:
    - `Ingredient.objects.get_or_create(name=name)`: Finds or makes the base ingredient (e.g., "Onion").
    - `RecipeIngredient.objects.create(...)`: Saves the specific amount for *this* recipe (e.g., "1 cup").

---

## 5. Testing: Proving it Works

Always create an automated test to ensure your parser doesn't break later.

1.  **Capture a Fixture**: `curl -L "URL" -o recipes/parsers/tests/fixtures/site_name.html`.
2.  **Mock the Network**: In the test, we pass this local HTML to the parser so it doesn't actually hit the internet.
3.  **Assert**: Check that the parsed results match the website.
    ```python
    def test_parsing(load_fixture):
        html = load_fixture("site_name.html")
        parser = MyParser(url, html)
        assert parser.title == "Example Cake"
        assert "1 cup flour" in parser.ingredients
    ```
