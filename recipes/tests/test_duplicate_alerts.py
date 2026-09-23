from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse

from recipes.models import Ingredient, Recipe, RecipeIngredient
from recipes.url_utils import normalize_url


def test_url_normalization_rules():
    """Verify normalize_url correctly standardizes schemes, netlocs, paths, queries, and fragments."""
    assert normalize_url("http://example.com") == "https://example.com"
    assert normalize_url("https://example.com:443/chili") == "https://example.com/chili"
    assert normalize_url("http://example.com:80/chili") == "https://example.com/chili"
    assert normalize_url("https://www.example.com/chili") == "https://example.com/chili"
    assert normalize_url("https://example.com/chili/") == "https://example.com/chili"
    assert normalize_url("https://example.com/chili?utm_source=fb&food=spicy") == "https://example.com/chili?food=spicy"
    assert normalize_url("https://example.com/chili#section") == "https://example.com/chili"
    assert normalize_url("") == ""


@pytest.mark.django_db
def test_same_household_duplicate_rejected(client, test_household):
    """Submitting a URL already present in the user's household is rejected by form validation."""
    Recipe.objects.create(household=test_household, original_url="https://example.com/chili", title="My Chili")

    response = client.post(reverse("recipes:add_recipe"), {"original_url": "https://example.com/chili"})
    assert response.status_code == 200
    assert "form" in response.context
    assert "original_url" in response.context["form"].errors
    assert Recipe.objects.filter(household=test_household).count() == 1


@pytest.mark.django_db
def test_cross_household_duplicate_triggers_alert(client, test_household, secondary_household):
    """Submitting a URL present in another household renders the duplicate alert banner without scraping."""
    Recipe.objects.create(household=secondary_household, original_url="https://example.com/chili", title="Neighbor's Chili")

    response = client.post(reverse("recipes:add_recipe"), {"original_url": "https://example.com/chili"})
    assert response.status_code == 200
    assert response.context.get("duplicate_detected") is True
    import html
    content = html.unescape(response.content.decode())
    assert 'id="duplicate-alert-banner"' in content
    assert "Neighbor's Chili" in content
    assert "Copy to My Recipes" in content
    assert "Scrape Fresh Anyway" in content
    assert Recipe.objects.filter(household=test_household).count() == 0


@pytest.mark.django_db
def test_duplicate_action_copy_success(client, test_user, test_household, secondary_household, secondary_user):
    """Clicking Copy to My Household from the alert banner clones recipe without leaking source notes."""
    source = Recipe.objects.create(
        household=secondary_household,
        created_by=secondary_user,
        title="Neighbor Stew",
        description="Neighbor description",
        instructions="Simmer well.",
        prep_time=10,
        cook_time=30,
        total_time=40,
        servings=4,
        user_notes="Secret private family note",
        rating=5,
        original_url="https://example.com/stew",
    )
    for i in range(3):
        ing = Ingredient.objects.create(name=f"Ingredient {i}")
        RecipeIngredient.objects.create(
            recipe=source,
            ingredient=ing,
            raw_text=f"1 unit Ingredient {i}",
            quantity="1",
            unit="unit",
            order=i,
        )

    copy_url = reverse("recipes:copy_duplicate", kwargs={"pk": source.pk})
    response = client.post(copy_url, {
        "original_url": "https://example.com/stew",
        "user_notes": "My own personal notes",
        "rating": "4",
        "is_future": "0",
    }, follow=True)
    assert response.status_code == 200

    cloned = Recipe.objects.filter(household=test_household, title="Neighbor Stew").first()
    assert cloned is not None
    assert cloned.created_by == test_user
    assert cloned.is_shared is True
    assert cloned.recipe_ingredients.count() == 3
    assert cloned.user_notes == "My own personal notes"
    assert "Secret private family note" not in cloned.user_notes
    assert cloned.rating == 4


@pytest.mark.django_db
def test_duplicate_action_force_scrape(client, test_household, secondary_household):
    """Submitting with force_scrape=1 bypasses duplicate banner and invokes external scraper."""
    Recipe.objects.create(household=secondary_household, original_url="https://example.com/chili", title="Neighbor's Chili")

    mock_parser = MagicMock()
    mock_parser.title = "Fresh Scraped Chili"
    mock_parser.description = "Freshly scraped"
    mock_parser.prep_time = 15
    mock_parser.cook_time = 45
    mock_parser.total_time = 60
    mock_parser.servings = 4
    mock_parser.instructions = "Cook freshly."
    mock_parser.image_url = "https://example.com/image.jpg"
    mock_parser.ingredients = ["1 can beans"]

    with patch("recipes.views.ParserRegistry.get_parser", return_value=mock_parser):
        response = client.post(reverse("recipes:add_recipe"), {
            "original_url": "https://example.com/chili",
            "force_scrape": "1",
        }, follow=True)
        assert response.status_code == 200

    fresh_recipe = Recipe.objects.filter(household=test_household, title="Fresh Scraped Chili").first()
    assert fresh_recipe is not None
    assert Recipe.objects.filter(original_url="https://example.com/chili").count() == 2


@pytest.mark.django_db
def test_duplicate_banner_copy_form_includes_original_url(client, secondary_household):
    """Duplicate alert banner copy form must include hidden original_url input."""
    url = "https://example.com/shared-chili"
    Recipe.objects.create(household=secondary_household, original_url=url, title="Shared Chili")

    response = client.post(reverse("recipes:add_recipe"), {"original_url": url})
    assert response.status_code == 200
    content = response.content.decode()
    assert f'<input type="hidden" name="original_url" value="{url}">' in content


@pytest.mark.django_db
def test_copy_duplicate_missing_url_returns_404(client, test_household, secondary_household):
    """POST to copy_duplicate without original_url returns 404."""
    source = Recipe.objects.create(
        household=secondary_household,
        title="Neighbor Stew",
        original_url="https://example.com/stew",
    )
    copy_url = reverse("recipes:copy_duplicate", kwargs={"pk": source.pk})
    response = client.post(copy_url, {
        "user_notes": "Notes without URL",
    })
    assert response.status_code == 404
    assert Recipe.objects.filter(household=test_household).count() == 0


@pytest.mark.django_db
def test_copy_duplicate_mismatched_url_returns_404(client, test_household, secondary_household):
    """POST to copy_duplicate with mismatched original_url returns 404."""
    source = Recipe.objects.create(
        household=secondary_household,
        title="Neighbor Stew",
        original_url="https://example.com/stew",
    )
    copy_url = reverse("recipes:copy_duplicate", kwargs={"pk": source.pk})
    response = client.post(copy_url, {
        "original_url": "https://example.com/different-recipe",
        "user_notes": "Mismatched URL",
    })
    assert response.status_code == 404
    assert Recipe.objects.filter(household=test_household).count() == 0


@pytest.mark.django_db
def test_copy_duplicate_manual_recipe_returns_404(client, test_household, secondary_household):
    """POST to copy_duplicate on manual recipe without original_url returns 404."""
    source = Recipe.objects.create(
        household=secondary_household,
        title="Secret Manual Soup",
        original_url="",
        is_shared=False,
    )
    copy_url = reverse("recipes:copy_duplicate", kwargs={"pk": source.pk})
    response = client.post(copy_url, {
        "original_url": "https://example.com/arbitrary",
    })
    assert response.status_code == 404
    assert Recipe.objects.filter(household=test_household).count() == 0


@pytest.mark.django_db
def test_copy_duplicate_own_recipe_redirects_without_duplication(client, test_household, test_user):
    """POST to copy_duplicate on recipe in same household redirects without creating duplicate."""
    source = Recipe.objects.create(
        household=test_household,
        created_by=test_user,
        title="Our Family Chili",
        original_url="https://example.com/chili",
    )
    copy_url = reverse("recipes:copy_duplicate", kwargs={"pk": source.pk})
    response = client.post(copy_url, {
        "original_url": "https://example.com/chili",
    }, follow=True)
    assert response.status_code == 200
    assert Recipe.objects.filter(household=test_household, title="Our Family Chili").count() == 1

