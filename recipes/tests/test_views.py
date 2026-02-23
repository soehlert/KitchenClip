import pytest
import json
from django.urls import reverse
from recipes.models import Recipe, MealPlan
from django.utils import timezone

@pytest.mark.django_db
def test_recipe_list_view(client):
    url = reverse('recipes:list_recipe')
    response = client.get(url)
    assert response.status_code == 200

@pytest.mark.django_db
def test_recipe_manual_create(client):
    url = reverse('recipes:manual_add')
    data = {
        'title': 'Test Manual Recipe',
        'prep_time': '10',
        'cook_time': '20',
        'total_time': '30',
        'servings': '2',
        'ingredients_text': '1 cup flour',
        'instructions_text': 'Mix and bake.',
    }
    response = client.post(url, data)
    
    if response.status_code == 200:
        print("CREATE FORM ERRORS:", response.context['form'].errors)

    assert response.status_code == 302
    
    # Verify the recipe was actually created in the DB
    recipe = Recipe.objects.filter(title='Test Manual Recipe').first()
    assert recipe is not None
    assert recipe.total_time == 30

@pytest.mark.django_db
def test_recipe_edit(client):
    recipe = Recipe.objects.create(title="Old Title", prep_time=10)
    url = reverse('recipes:edit_recipe', args=[recipe.pk])
    data = {
        'title': 'New Title',
        'prep_time': '15',
        'cook_time': '5',
        'total_time': '20',
        'servings': '2',
        'instructions': 'Eat sugar.',
        'ingredients_text': '1/2 cup sugar',
        'instructions_text': 'Eat sugar.',
    }
    response = client.post(url, data)
    
    if response.status_code == 200:
        print("EDIT FORM ERRORS:", response.context['form'].errors)

    assert response.status_code == 302
    
    recipe.refresh_from_db()
    assert recipe.title == 'New Title'
    assert recipe.total_time == 20

@pytest.mark.django_db
def test_meal_plan_api_update(client):
    # Tests the /api/meal-plan/update/ endpoint utilized by javascript 'Apply All'
    recipe = Recipe.objects.create(title="Lunch Wrap")
    today = timezone.now().date().isoformat()
    
    payload = {
        'date': today,
        'meal_type': 'LUNCH',
        'recipe_id': recipe.pk,
        'ready_at': '12:30' # Ensure time formatting matches
    }
    
    url = reverse('recipes:update_meal_plan')
    response = client.post(url, data=json.dumps(payload), content_type='application/json')
    assert response.status_code == 200
    resp_data = response.json()
    assert resp_data['status'] == 'success'
    
    plan = MealPlan.objects.filter(date=today, meal_type='LUNCH').first()
    assert plan is not None
    assert plan.recipe == recipe
    assert plan.ready_at.strftime('%H:%M') == '12:30'
