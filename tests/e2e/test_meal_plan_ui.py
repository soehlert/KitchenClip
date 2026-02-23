import pytest
from playwright.sync_api import Page, expect
from recipes.models import Recipe

@pytest.mark.django_db(transaction=True)
def test_meal_plan_page_load(page: Page, live_server):
    """Test the Meal Planner page rendering and sidebar."""
    # Create a dummy recipe that will display in the sidebar
    Recipe.objects.create(title="E2E Sidebar Recipe")
    
    page.goto(f"{live_server.url}/meal-plan/")
    
    # Assert page headers and sidebar loaded
    expect(page.locator("text=Meal Planner")).to_be_visible()
    expect(page.locator("text=Recipes & Ideas")).to_be_visible()
    
    # Verify the global flatpickr inputs are initialized
    expect(page.locator("#global-lunch")).to_be_attached()
    expect(page.locator("#global-dinner")).to_be_attached()

@pytest.mark.django_db(transaction=True)
def test_recipes_list_page(page: Page, live_server):
    Recipe.objects.create(title="Existing Recipe")
    page.goto(f"{live_server.url}/")
    
    expect(page.locator("text=Existing Recipe")).to_be_visible()

@pytest.mark.django_db(transaction=True)
def test_meal_plan_drag_and_drop(page: Page, live_server):
    """Test dragging a recipe from the sidebar to a meal slot."""
    from django.utils import timezone
    from recipes.models import MealPlan
    
    recipe = Recipe.objects.create(title="Drag Me Recipe")
    today = timezone.localtime().date().isoformat()
    
    page.goto(f"{live_server.url}/meal-plan/")
    
    # Sidebar recipe locator
    sidebar_recipe = page.locator(f".recipe-card[data-id='{recipe.id}']")
    expect(sidebar_recipe).to_be_visible()
    
    # Target slot locator
    target_slot = page.locator(f".meal-slot[data-date='{today}'][data-type='LUNCH']")
    
    # Perform drag and drop using HTML5 DataTransfer
    page.evaluate(f'''
        const source = document.querySelector(".recipe-card[data-id='{recipe.id}']");
        const target = document.querySelector(".meal-slot[data-date='{today}'][data-type='LUNCH']");
        
        const dataTransfer = new DataTransfer();
        dataTransfer.setData('text/plain', '{recipe.id}');
        
        source.dispatchEvent(new DragEvent('dragstart', {{ dataTransfer: dataTransfer, bubbles: true }}));
        target.dispatchEvent(new DragEvent('dragenter', {{ dataTransfer: dataTransfer, bubbles: true }}));
        target.dispatchEvent(new DragEvent('dragover', {{ dataTransfer: dataTransfer, bubbles: true }}));
        target.dispatchEvent(new DragEvent('drop', {{ dataTransfer: dataTransfer, bubbles: true }}));
    ''')
    
    # Verify UI updated
    expect(target_slot.locator("text=Drag Me Recipe")).to_be_visible()
    
    # Verify Database updated
    assert MealPlan.objects.filter(date=today, meal_type='LUNCH', recipe=recipe).exists()
