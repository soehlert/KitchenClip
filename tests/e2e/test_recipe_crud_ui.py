import pytest
from playwright.sync_api import Page, expect
from recipes.models import Recipe

@pytest.mark.django_db(transaction=True)
def test_manual_recipe_add_and_view(page: Page, live_server):
    """Test the complete UI flow for creating a recipe manually and viewing it in the list."""
    # 1. Navigate to Manual Add
    page.goto(f"{live_server.url}/add/manual/")
    
    # Assert page loaded
    expect(page.locator("text=Ingredients")).to_be_visible()
    
    # 2. Fill the form
    page.fill("input[name='title']", "E2E UI Recipe")
    page.fill("input[name='prep_time']", "10")
    page.fill("input[name='cook_time']", "20")
    page.fill("input[name='total_time']", "30")
    page.fill("input[name='servings']", "4")
    page.fill("textarea[name='ingredients_text']", "1 cup flour\n2 eggs")
    page.fill("textarea[name='instructions_text']", "Mix.\nBake.")
    
    # 3. Submit
    page.click("button[type='submit']")
    
    # Wait for the redirect back to the recipe list
    page.wait_for_url(f"{live_server.url}/")
    
    # 4. Verify the recipe is in the list
    expect(page.locator("text=E2E UI Recipe")).to_be_visible()
    
    # 5. Verify the DB was actually updated
    assert Recipe.objects.filter(title="E2E UI Recipe").exists()

@pytest.mark.django_db(transaction=True)
def test_recipe_view_edit_delete(page: Page, live_server):
    """Test viewing, editing, and deleting an existing recipe."""
    recipe = Recipe.objects.create(
        title="Initial Delete Me Recipe", 
        prep_time=10, 
        cook_time=15, 
        total_time=25, 
        servings=2
    )
    
    # 1. View
    page.goto(f"{live_server.url}/{recipe.id}/")
    expect(page.locator("h1").filter(has_text="Initial Delete Me Recipe")).to_be_visible()
    
    # 2. Edit
    page.click("text=Edit")
    expect(page.locator("text=Ingredients")).to_be_visible()
    
    page.fill("input[name='title']", "Edited Recipe Title")
    page.fill("textarea[name='ingredients_text']", "1 cup water")
    page.fill("textarea[name='instructions']", "Boil.")
    page.click("button[type='submit']")
    
    # Wait for redirect back to details page
    page.wait_for_url(f"{live_server.url}/{recipe.id}/")
    expect(page.locator("h1").filter(has_text="Edited Recipe Title")).to_be_visible()
    
    recipe.refresh_from_db()
    assert recipe.title == "Edited Recipe Title"
    
    # 3. Delete
    page.click("text=Delete")
    expect(page.locator("text=Are you sure you want to delete")).to_be_visible()
    
    # Click confirmation button
    page.click("button:has-text('Yes, Delete Recipe')")
    
    # Wait for redirect back to recipes list
    page.wait_for_url(f"{live_server.url}/")
    assert not Recipe.objects.filter(id=recipe.id).exists()
