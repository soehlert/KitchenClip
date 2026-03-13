import pytest
from recipes.parsers.scrapers_parser import ScrapersParser

@pytest.mark.recipe_fixture("mock_recipe.html")
def test_scrapers_parser_fallback():
    url = "https://www.allrecipes.com/recipe/99999/mock-recipe/"
    parser = ScrapersParser(url)
    
    assert parser.title == "Mock Recipe"
    assert "simple mock recipe" in parser.description
    assert "1 cup water" in parser.ingredients
    assert "Drink it" in parser.instructions
    assert parser.servings == 1
    
    # Check times
    assert parser.prep_time == 0
    assert parser.cook_time == 0
    assert parser.total_time == 0
    
    # Check image URL
    assert "mock.jpg" in parser.image_url
