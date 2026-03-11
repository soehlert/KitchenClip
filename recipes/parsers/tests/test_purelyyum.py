from recipes.parsers.purelyyum import PurelyYumParser


def test_purelyyum_parsing(load_fixture):
    html = load_fixture("purelyyum_shrimp_ramen.html")
    url = "https://purelyyumrecipes.com/spicy-shrimp-ramen-bowls-flavorful-and-quick-meal/"
    parser = PurelyYumParser(url, html)
    
    # Check title
    assert parser.title == "Spicy Shrimp Ramen Bowls"
    
    # Check ingredients
    # The parser should now handle the strings and return processed ingredients
    # In the fixture, we have "8 oz ramen noodles", "1 lb shrimp", etc.
    assert len(parser.ingredients) == 15
    
    ingredients_str = " ".join(parser.ingredients).lower()
    assert "ramen noodles" in ingredients_str
    assert "shrimp" in ingredients_str
    assert "soy sauce" in ingredients_str
    
    # Check specifically for the quantities that might have caused issues
    # "8 oz ramen noodles" -> "8 oz ramen noodles"
    assert any("8 oz" in ing for ing in parser.ingredients)
    assert any("1 lb" in ing for ing in parser.ingredients)
    
    # Check instructions
    assert "Cook the ramen noodles" in parser.instructions
    assert "Serve immediately" in parser.instructions
    assert len(parser.instructions.splitlines()) == 7
    
    # Check times
    assert parser.prep_time == 15
    assert parser.cook_time == 15
    assert parser.total_time == 30
    
    # Check servings
    assert parser.servings == 4
