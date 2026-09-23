import re
import pytest
from playwright.sync_api import Page, expect
from django.utils import timezone
from recipes.models import Recipe, MealPlan

@pytest.mark.django_db(transaction=True)
def test_meal_plan_mobile_layout_and_interactions(page: Page, live_server):
    # Set up sample recipes
    recipe1 = Recipe.objects.create(
        title="Instant Pot Salmon and Rice",
        is_on_menu=True,
        image_url="https://images.unsplash.com/photo-1467003909585-2f8a72700288?w=300"
    )
    recipe2 = Recipe.objects.create(
        title="Mediterranean Chicken Pesto Pasta",
        is_on_menu=True,
        image_url="https://images.unsplash.com/photo-1473093295043-cdd812d0e601?w=300"
    )

    today = timezone.localtime().date()
    today_str = today.isoformat()

    # Place recipe1 in today's Lunch
    MealPlan.objects.create(recipe=recipe1, date=today, meal_type="LUNCH")

    # Set mobile viewport: 375x812 (standard iPhone)
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(f"{live_server.url}/meal-plan/")

    # 1. Verify layout & zero horizontal overflow
    info = page.evaluate("""() => {
        const bodyWidth = document.body.scrollWidth;
        const windowWidth = window.innerWidth;
        const applyBtn = document.getElementById('apply-global-times');
        const handle = document.getElementById('sidebar-handle');
        const openBtn = document.getElementById('open-library-btn');
        const handleStyle = handle ? window.getComputedStyle(handle).display : null;
        const openBtnStyle = openBtn ? window.getComputedStyle(openBtn).display : null;

        return {
            bodyWidth,
            windowWidth,
            applyBtnRight: applyBtn ? applyBtn.getBoundingClientRect().right : null,
            handleDisplay: handleStyle,
            openBtnDisplay: openBtnStyle
        };
    }""")

    # Assert no horizontal overflow
    assert info['bodyWidth'] <= info['windowWidth'] + 1, f"Body overflowed: {info['bodyWidth']} > {info['windowWidth']}"
    assert info['applyBtnRight'] <= info['windowWidth'] + 1, f"Apply button overflowed: {info['applyBtnRight']} > {info['windowWidth']}"
    assert info['handleDisplay'] == 'none', "Sidebar handle should be hidden on mobile"
    assert info['openBtnDisplay'] != 'none', "Mobile Recipes & Ideas button should be visible"

    # 2. Test Slot-to-Recipe tap: tap today's Dinner (empty)
    dinner_slot = page.locator(f".meal-slot[data-date='{today_str}'][data-type='DINNER']")
    expect(dinner_slot).to_be_visible()
    dinner_slot.click()

    # Active slot banner should now be visible in the open sidebar
    overlay = page.locator("#sidebar-overlay")
    expect(overlay).to_have_class(re.compile(r"open"))
    banner = page.locator("#active-slot-banner")
    expect(banner).to_be_visible()
    expect(banner).to_contain_text("Dinner")

    # Click recipe2 in sidebar to add to today's dinner
    recipe2_card = page.locator(f".recipe-card[data-id='{recipe2.id}']")
    recipe2_card.click()

    # Overlay should close and dinner slot should now contain recipe2
    expect(overlay).not_to_have_class(re.compile(r"open"))
    expect(dinner_slot.locator(".draggable-meal")).to_be_visible()
    expect(dinner_slot).to_contain_text("Mediterranean Chicken Pesto Pasta")

    # 3. Test Move Meal: click move on today's Lunch (recipe1) and tap tomorrow's Dinner
    tomorrow = today + timezone.timedelta(days=1)
    tomorrow_str = tomorrow.isoformat()

    lunch_slot = page.locator(f".meal-slot[data-date='{today_str}'][data-type='LUNCH']")
    move_btn = lunch_slot.locator(".move-meal-btn")
    expect(move_btn).to_be_visible()
    move_btn.click()

    # Tap destination slot directly
    tomorrow_dinner = page.locator(f".meal-slot[data-date='{tomorrow_str}'][data-type='DINNER']")
    tomorrow_dinner.click()

    # Lunch slot should now be empty and tomorrow dinner slot populated
    expect(tomorrow_dinner.locator(".draggable-meal")).to_be_visible()
    expect(tomorrow_dinner).to_contain_text("Instant Pot Salmon and Rice")
    expect(lunch_slot.locator(".draggable-meal")).to_have_count(0)

    # 4. Test Mobile Remove Meal: remove today's Dinner (recipe2)
    remove_btn = dinner_slot.locator(".remove-meal")
    expect(remove_btn).to_be_visible()
    remove_btn.click()

    expect(dinner_slot.locator(".draggable-meal")).to_have_count(0)
    expect(dinner_slot.locator(".empty-slot-prompt")).to_be_visible()

    # Take screenshot of final mobile view
    page.screenshot(path="/Users/soehlert/.gemini/antigravity/brain/0801dc3b-1f5b-45e0-9bbc-6f8c7fb8c4cd/scratch/mobile_after.png", full_page=True)
