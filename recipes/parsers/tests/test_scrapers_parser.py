from recipes.parsers.scrapers_parser import ScrapersParser


def test_scrapers_parser_fallback(load_fixture):
    # Use the shared fixture loader
    mock_html = load_fixture("mock_recipe.html")
    url = "https://www.allrecipes.com/recipe/99999/mock-recipe/"
    
    parser = ScrapersParser(url, html=mock_html)
    
    assert "Mock Recipe" in parser.title
    assert "1 cup water" in parser.ingredients[0]
    assert "Drink it" in parser.instructions
