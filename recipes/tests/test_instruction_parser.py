import pytest
from recipes.models import Ingredient, RecipeIngredient
from recipes.utils import clean_instruction_line, parse_instruction_steps


def test_parse_instruction_steps_bullet_markers():
    """Test marker-based grouping on wrapped lines with varied bullet types."""
    text = """
    • Adjust rack to top position and
    preheat oven to 450 degrees.
    - Toss vegetables on a baking sheet with
    olive oil and seasonings.
    * Roast on top rack until tender,
    12-15 minutes.
    """
    steps = parse_instruction_steps(text)
    assert len(steps) == 3
    assert steps[0] == "Adjust rack to top position and preheat oven to 450 degrees."
    assert steps[1] == "Toss vegetables on a baking sheet with olive oil and seasonings."
    assert steps[2] == "Roast on top rack until tender, 12-15 minutes."


def test_parse_instruction_steps_numbered_markers():
    """Test numbered steps with prefixes and hard-wrapped lines."""
    text = """
    1. Preheat oven to 400 degrees and
    line a baking sheet with foil.
    Step 2: Dice onions and mince garlic.
    (3) Simmer sauce until thickened,
    about 10 minutes.
    """
    steps = parse_instruction_steps(text)
    assert len(steps) == 3
    assert steps[0] == "Preheat oven to 400 degrees and line a baking sheet with foil."
    assert steps[1] == "Dice onions and mince garlic."
    assert steps[2] == "Simmer sauce until thickened, about 10 minutes."


def test_parse_instruction_steps_paragraph_blocks():
    """Test multi-paragraph steps separated by blank lines."""
    text = """
    In a large bowl, whisk together the flour, sugar, and baking powder.
    Make a well in the center of the dry ingredients.

    In a separate bowl, whisk milk, eggs, and melted butter.
    Pour wet ingredients into the well and stir until just combined.
    """
    steps = parse_instruction_steps(text)
    assert len(steps) == 2
    assert steps[0] == "In a large bowl, whisk together the flour, sugar, and baking powder. Make a well in the center of the dry ingredients."
    assert steps[1] == "In a separate bowl, whisk milk, eggs, and melted butter. Pour wet ingredients into the well and stir until just combined."


def test_parse_instruction_steps_unmarked_wrapped_prose():
    """Test sentence-continuation heuristic on unmarked wrapped text with dangling prepositions and parentheticals."""
    text = """
    Heat olive oil in a skillet over
    medium-high heat. Add garlic and
    cook until fragrant.
    Transfer to a serving bowl with a
    sprinkle of fresh herbs
    (use more if desired) and
    flaky sea salt.
    """
    steps = parse_instruction_steps(text)
    assert len(steps) == 2
    assert steps[0] == "Heat olive oil in a skillet over medium-high heat. Add garlic and cook until fragrant."
    assert steps[1] == "Transfer to a serving bowl with a sprinkle of fresh herbs (use more if desired) and flaky sea salt."


def test_parse_instruction_steps_plain_commands():
    """Test simple unpunctuated commands remain independent steps."""
    text = """
    Preheat oven
    Chop veggies
    Bake 20 mins
    """
    steps = parse_instruction_steps(text)
    assert len(steps) == 3
    assert steps[0] == "Preheat oven"
    assert steps[1] == "Chop veggies"
    assert steps[2] == "Bake 20 mins"


def test_clean_instruction_line():
    """Test clean_instruction_line returns unified newline-delimited steps."""
    text = """
    • Step one wrapped
    continuation line.
    • Step two.
    """
    cleaned = clean_instruction_line(text)
    assert cleaned == "Step one wrapped continuation line.\nStep two."


@pytest.mark.django_db
def test_recipe_ingredient_display_preparation(recipe_factory):
    """Test that display_preparation suppresses redundant unit indicators while keeping actual prep notes."""
    recipe = recipe_factory(title="Sample Recipe")
    salt_ing = Ingredient.objects.create(name="sea salt")
    butter_ing = Ingredient.objects.create(name="salted butter")

    # Redundant unit indicator (tsp)
    ri_salt = RecipeIngredient.objects.create(
        recipe=recipe,
        ingredient=salt_ing,
        raw_text="1 teaspoon sea salt (tsp)",
        quantity="1",
        unit="teaspoon",
        preparation="tsp",
    )
    assert ri_salt.display_preparation == ""

    # Genuine preparation note (melted)
    ri_butter = RecipeIngredient.objects.create(
        recipe=recipe,
        ingredient=butter_ing,
        raw_text="2 tablespoons salted butter (melted)",
        quantity="2",
        unit="tablespoons",
        preparation="melted",
    )
    assert ri_butter.display_preparation == "melted"
