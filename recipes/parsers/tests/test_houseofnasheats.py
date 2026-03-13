import pytest
from recipes.parsers.houseofnasheats import HouseOfNashEatsParser

@pytest.mark.recipe_fixture("houseofnasheats_banana_bread.html")
def test_houseofnasheats_parsing():
    url = "https://houseofnasheats.com/best-banana-bread-recipe/"
    parser = HouseOfNashEatsParser(url)
    
    assert "Banana Bread" in parser.title
    assert "Super moist, EASY, and delicious" in parser.description
    assert len(parser.ingredients) == 11
    assert any("ripe bananas" in ing.lower() for ing in parser.ingredients)
    assert len(parser.instructions.splitlines()) == 9
    assert "Preheat oven to 350" in parser.instructions
    assert parser.servings == 1
    
    # Check times
    assert parser.prep_time == 15
    assert parser.cook_time == 55
    assert parser.total_time == 70
    
    # Check image URL
    assert "Banana-Bread-Square.jpg" in parser.image_url
