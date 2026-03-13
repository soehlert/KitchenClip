import pytest
from recipes.parsers.lesswithlaur import LessWithLaurParser

@pytest.mark.recipe_fixture("lesswithlaur_chicken_gnocchi.html")
def test_lesswithlaur_parsing():
    url = "https://lesswithlaur.com/one-pan-lemon-chicken-gnocchi/"
    parser = LessWithLaurParser(url)
    
    # Check basic info
    assert parser.title == "One Pan Lemon Chicken Gnocchi"
    assert "craving a light and fresh dinner" in parser.description
    assert parser.servings == 2
    
    # Check ingredients
    assert len(parser.ingredients) == 10
    assert any("chicken breasts" in ing.lower() for ing in parser.ingredients)
    assert any("coconut cream" in ing.lower() for ing in parser.ingredients)
    
    # Check instructions
    assert len(parser.instructions.splitlines()) == 6
    assert "Gather your ingredients." in parser.instructions
    
    # Check times (converted to minutes)
    assert parser.prep_time == 5
    assert parser.cook_time == 25
    assert parser.total_time == 30
    
    # Check image URL
    assert "lemon-chicken-gnocchi-pan-scaled.jpg" in parser.image_url
