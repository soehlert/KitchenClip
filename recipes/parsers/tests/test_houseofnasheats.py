from recipes.parsers.houseofnasheats import HouseOfNashEatsParser


def test_houseofnasheats_parsing(load_fixture):
    # Use the shared fixture loader
    mock_html = load_fixture("houseofnasheats_banana_bread.html")

    url = "https://houseofnasheats.com/best-banana-bread-recipe/"
    parser = HouseOfNashEatsParser(url, html=mock_html)
    
    assert "Banana Bread" in parser.title
    assert len(parser.ingredients) == 11
    # Check a few specific ingredients
    ingredients_str = " ".join(parser.ingredients)
    assert "ripe bananas" in ingredients_str.lower()
    assert "salted butter" in ingredients_str.lower()
    assert "walnuts" in ingredients_str.lower()
    
    # Check instructions
    assert "preheat oven" in parser.instructions.lower()
    assert len(parser.instructions.splitlines()) >= 5
    
    # New assertions
    assert parser.image_url.startswith("http")
    assert "banana bread" in parser.description.lower()
    assert "Preheat oven" in parser.instructions
    
    # Check times and yields
    assert parser.servings == 1
    assert parser.prep_time == 15
    assert parser.cook_time == 55
    assert parser.total_time == 70
