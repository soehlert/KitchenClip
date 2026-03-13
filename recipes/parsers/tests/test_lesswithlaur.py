from recipes.parsers.lesswithlaur import LessWithLaurParser


def test_lesswithlaur_parsing(load_fixture):
    html = load_fixture("lesswithlaur_chicken_gnocchi.html")
    url = "https://lesswithlaur.com/one-pan-lemon-chicken-gnocchi/"
    parser = LessWithLaurParser(url, html)
    
    # Check title
    assert parser.title == "One Pan Lemon Chicken Gnocchi"
    
    # Check description (cleaned of HTML entities)
    assert "light and fresh dinner" in parser.description
    assert "one pan lemon chicken gnocchi!" in parser.description
    
    # Check ingredients
    assert len(parser.ingredients) == 10
    assert "1 lb chicken breasts" in parser.ingredients
    assert "1 package gnocchi" in parser.ingredients
    assert "1/4 cup fresh basil" in parser.ingredients
    
    # Check instructions
    assert "Gather your ingredients." in parser.instructions
    assert "Top dish with chicken, lemon slices and basil and enjoy!" in parser.instructions
    assert len(parser.instructions.splitlines()) == 6
    
    # Check times (PT5M, PT25M)
    assert parser.prep_time == 5
    assert parser.cook_time == 25
    assert parser.total_time == 30
    
    # Check servings
    assert parser.servings == 2
    
    # Check image URL
    assert "lemon-chicken-gnocchi-pan-scaled.jpg" in parser.image_url
