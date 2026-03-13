import pytest

from recipes.parsers.allrecipes import AllrecipesParser


@pytest.mark.recipe_fixture("allrecipes_100_grand.html")
def test_allrecipes_parsing():
    url = "https://www.allrecipes.com/100-grand-bars-recipe-11918066"
    parser = AllrecipesParser(url)
    
    # Check basic info
    assert "100 Grand Bars" in parser.title
    assert "4-Ingredient Copycat" in parser.title
    assert parser.servings == 12
    
    # Check ingredients
    assert len(parser.ingredients) == 4
    ingredients_str = " ".join(parser.ingredients).lower()
    assert "chocolate chips" in ingredients_str
    assert "dulce de leche" in ingredients_str
    assert "crispy rice cereal" in ingredients_str
    
    # Check instructions
    assert len(parser.instructions.splitlines()) == 5
    assert "Line an 8x8-inch baking pan" in parser.instructions
    
    # Check times (converted to minutes)
    assert parser.prep_time == 20
    assert parser.cook_time == 5
    assert parser.total_time == 95