import pytest

from recipes.parsers.purelyyum import PurelyYumParser


@pytest.mark.recipe_fixture("purelyyum_shrimp_ramen.html")
def test_purelyyum_parsing():
    url = "https://purelyyumrecipes.com/spicy-shrimp-ramen-bowls-flavorful-and-quick-meal/"
    parser = PurelyYumParser(url)
    
    # Check basic info
    assert parser.title == "Spicy Shrimp Ramen Bowls"
    assert "Flavorful and quick meal" in parser.description
    assert parser.servings == 4
    
    # Check ingredients
    assert len(parser.ingredients) == 15
    assert any("ramen noodles" in ing.lower() for ing in parser.ingredients)
    
    # Check instructions
    assert len(parser.instructions.splitlines()) == 7
    assert "Cook the ramen noodles" in parser.instructions
    
    # Check times
    assert parser.prep_time == 15
    assert parser.cook_time == 15
    assert parser.total_time == 30
    
    # Check image URL
    assert parser.image_url is not None
