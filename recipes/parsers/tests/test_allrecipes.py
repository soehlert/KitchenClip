from recipes.parsers.allrecipes import AllrecipesParser


def test_allrecipes_parsing(load_fixture):
    # Use the shared fixture loader
    mock_html = load_fixture("allrecipes_100_grand.html")

    url = "https://www.allrecipes.com/100-grand-bars-recipe-11918066"
    parser = AllrecipesParser(url, html=mock_html)
    
    assert "100 Grand Bars" in parser.title
    assert len(parser.ingredients) == 4
    assert len(parser.instructions.splitlines()) == 5
    assert parser.servings == 12
    
    # Check specific ingredients
    ingredients_str = " ".join(parser.ingredients)
    assert "chocolate chips" in ingredients_str.lower()
    assert "dulce leche" in ingredients_str.lower()
