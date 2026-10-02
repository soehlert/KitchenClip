import pytest
from recipes.models import Household, Ingredient, Recipe, RecipeIngredient
from recipes.utils import clean_instruction_line, parse_instruction_steps


def test_parse_instruction_steps_bulleted_wrapped():
    """Test marker-based grouping on wrapped lines with bullet markers."""
    text = """
    • Adjust rack to top position and
    preheat oven to 450 degrees. Wash
    and dry produce.
    • Cut broccoli into bite-size pieces if
    necessary. Peel and mince or grate garlic.
    • Finely chop parsley. Quarter lemon.
    """
    steps = parse_instruction_steps(text)
    assert len(steps) == 3
    assert steps[0] == "Adjust rack to top position and preheat oven to 450 degrees. Wash and dry produce."
    assert steps[1] == "Cut broccoli into bite-size pieces if necessary. Peel and mince or grate garlic."
    assert steps[2] == "Finely chop parsley. Quarter lemon."


def test_parse_instruction_steps_numbered_wrapped():
    """Test numbered steps with hard wrapped lines."""
    text = """
    1. Adjust rack to top position and
    preheat oven to 450 degrees.
    2. Cut broccoli into bite-size pieces if
    necessary.
    """
    steps = parse_instruction_steps(text)
    assert len(steps) == 2
    assert steps[0] == "Adjust rack to top position and preheat oven to 450 degrees."
    assert steps[1] == "Cut broccoli into bite-size pieces if necessary."


def test_parse_instruction_steps_paragraphs():
    """Test multi-paragraph steps separated by blank lines."""
    text = """
    Adjust rack to top position and preheat oven to 450 degrees.
    Wash and dry produce.

    Cut broccoli into bite-size pieces if necessary.
    Peel and mince or grate garlic.
    """
    steps = parse_instruction_steps(text)
    assert len(steps) == 2
    assert steps[0] == "Adjust rack to top position and preheat oven to 450 degrees. Wash and dry produce."
    assert steps[1] == "Cut broccoli into bite-size pieces if necessary. Peel and mince or grate garlic."


def test_parse_instruction_steps_unmarked_wrapped():
    """Test sentence-continuation heuristic on unmarked wrapped text."""
    text = """
    Adjust rack to top position and
    preheat oven to 450 degrees. Wash
    and dry produce.
    Cut broccoli into bite-size pieces if
    necessary. Peel and mince or grate garlic.
    Finely chop parsley. Quarter lemon.
    Toss broccoli on a baking sheet with a
    drizzle of olive oil, ½ tsp chili flakes
    (¾ tsp for 4 servings) (use less if you
    prefer less heat), salt, and pepper. Roast
    on top rack until browned and tender,
    12-15 minutes.
    Meanwhile, heat a drizzle of olive oil in a
    small pot over medium-high heat.
    Add half the garlic; cook until fragrant.
    """
    steps = parse_instruction_steps(text)
    assert len(steps) == 6
    assert steps[0] == "Adjust rack to top position and preheat oven to 450 degrees. Wash and dry produce."
    assert steps[1] == "Cut broccoli into bite-size pieces if necessary. Peel and mince or grate garlic."
    assert steps[2] == "Finely chop parsley. Quarter lemon."
    assert "12-15 minutes." in steps[3]
    assert steps[4] == "Meanwhile, heat a drizzle of olive oil in a small pot over medium-high heat."
    assert steps[5] == "Add half the garlic; cook until fragrant."


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


def test_parse_instruction_steps_removes_headers_and_preserves_tips():
    """Test header removal and TIP styling."""
    text = """
    Instructions:
    • Step one
    • TIP: Toast almonds before adding
    """
    steps = parse_instruction_steps(text)
    assert len(steps) == 2
    assert steps[0] == "Step one"
    assert "<strong>TIP:</strong>" in steps[1]


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
def test_recipe_ingredient_display_preparation():
    """Test that display_preparation suppresses redundant unit indicators."""
    household = Household.objects.create(name="Test Kitchen")
    recipe = Recipe.objects.create(title="Salmon Dinner", household=household)
    salt_ing = Ingredient.objects.create(name="salt")
    butter_ing = Ingredient.objects.create(name="butter")

    # Redundant unit indicator (tsp)
    ri_salt = RecipeIngredient.objects.create(
        recipe=recipe,
        ingredient=salt_ing,
        raw_text="1 teaspoon salt (tsp)",
        quantity="1",
        unit="teaspoon",
        preparation="tsp",
    )
    assert ri_salt.display_preparation == ""

    # Genuine preparation note (melted)
    ri_butter = RecipeIngredient.objects.create(
        recipe=recipe,
        ingredient=butter_ing,
        raw_text="2 tablespoons butter (melted)",
        quantity="2",
        unit="tablespoons",
        preparation="melted",
    )
    assert ri_butter.display_preparation == "melted"
