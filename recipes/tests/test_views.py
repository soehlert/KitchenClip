import json

import pytest
from django.urls import reverse
from django.utils import timezone

from recipes.models import MealPlan, Recipe


@pytest.mark.django_db
def test_recipe_list_view(client):
    url = reverse('recipes:list_recipe')
    response = client.get(url)
    assert response.status_code == 200
    # Navbar contains search input and sidebar does not contain old search field
    assert 'id="navbar-search"' in response.content.decode()
    assert 'for="search"' not in response.content.decode()


@pytest.mark.django_db
def test_search_both_active_and_future_recipes(client):
    active = Recipe.objects.create(title="Active Chicken Dish", is_future=False)
    future = Recipe.objects.create(title="Future Chicken Dish", is_future=True)
    unrelated = Recipe.objects.create(title="Beef Stew", is_future=False)

    # Without search: only active recipes shown
    response = client.get(reverse('recipes:list_recipe'))
    recipes = list(response.context['recipes'])
    assert active in recipes
    assert unrelated in recipes
    assert future not in recipes

    # With search: matches both active and future recipes
    search_response = client.get(reverse('recipes:list_recipe'), {'search': 'Chicken'})
    search_recipes = list(search_response.context['recipes'])
    assert active in search_recipes
    assert future in search_recipes
    assert unrelated not in search_recipes
    content = search_response.content.decode()
    assert 'Saved for Later' in content
    assert '<input type="hidden" name="search" value="Chicken">' in content

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
    
    plan = MealPlan.objects.filter(household=client.household, date=today, meal_type='LUNCH').first()
    assert plan is not None
    assert plan.recipe == recipe
    assert plan.ready_at.strftime('%H:%M') == '12:30'


@pytest.mark.django_db
def test_scratch_create_get(client):
    url = reverse('recipes:scratch_add')
    response = client.get(url)
    assert response.status_code == 200
    assert "Create Recipe from Scratch" in response.context['title']
    assert len(response.context['ingredient_rows']) >= 1
    assert len(response.context['instruction_steps']) >= 1
    assert "import by URL" not in response.content.decode()
    # Also verify alias create_scratch works
    alias_url = reverse('recipes:create_scratch')
    alias_response = client.get(alias_url)
    assert alias_response.status_code == 200


@pytest.mark.django_db
def test_scratch_create_success_structured(client):
    url = reverse('recipes:scratch_add')
    data = {
        'title': 'Scratch Pancakes',
        'description': 'Fluffy homemade pancakes.',
        'user_notes': 'Flip when bubbles burst.',
        'prep_time': '10',
        'cook_time': '15',
        'total_time': '25',
        'servings': '4',
        'rating': '5',
        'image_url': 'https://example.com/pancakes.jpg',
        'original_url': 'https://example.com/original-pancakes',
        'tags': 'breakfast, sweet',
        'ingredient_quantity': ['2', '1', '2'],
        'ingredient_unit': ['cups', 'tbsp', ''],
        'ingredient_food': ['flour', 'sugar', 'eggs'],
        'instruction_step': [
            'Whisk dry ingredients.',
            'Add eggs and milk.',
            'Cook on griddle until golden brown.',
        ],
    }
    response = client.post(url, data)
    recipe = Recipe.objects.filter(title='Scratch Pancakes').first()
    assert recipe is not None
    assert response.status_code == 302
    assert response.url == recipe.get_absolute_url()

    assert recipe.description == 'Fluffy homemade pancakes.'
    assert recipe.user_notes == 'Flip when bubbles burst.'
    assert recipe.prep_time == 10
    assert recipe.cook_time == 15
    assert recipe.total_time == 25
    assert recipe.servings == 4
    assert recipe.rating == 5
    assert recipe.image_url == 'https://example.com/pancakes.jpg'
    assert recipe.original_url == 'https://example.com/original-pancakes'

    # Verify instructions
    instructions = recipe.instructions.splitlines()
    assert len(instructions) == 3
    assert 'Whisk dry ingredients.' in instructions[0]
    assert 'Add eggs and milk.' in instructions[1]
    assert 'Cook on griddle until golden brown.' in instructions[2]

    # Verify ingredients
    ingredients = list(recipe.recipe_ingredients.all().order_by('order'))
    assert len(ingredients) == 3
    assert ingredients[0].quantity == '2'
    assert ingredients[0].unit == 'cups'
    assert ingredients[0].ingredient.name == 'flour'
    assert ingredients[0].raw_text == '2 cups flour'
    assert ingredients[0].order == 0

    assert ingredients[1].quantity == '1'
    assert ingredients[1].unit == 'tbsp'
    assert ingredients[1].ingredient.name == 'sugar'
    assert ingredients[1].order == 1

    assert ingredients[2].quantity == '2'
    assert ingredients[2].unit == ''
    assert ingredients[2].ingredient.name == 'eggs'
    assert ingredients[2].order == 2

    # Verify tags
    tags = list(recipe.tags.values_list('name', flat=True))
    assert 'breakfast' in tags
    assert 'sweet' in tags


@pytest.mark.django_db
def test_scratch_create_validation_missing_title(client):
    url = reverse('recipes:scratch_add')
    data = {
        'title': '',
        'ingredient_quantity': ['1'],
        'ingredient_unit': ['cup'],
        'ingredient_food': ['flour'],
        'instruction_step': ['Mix and bake.'],
    }
    response = client.post(url, data)
    assert response.status_code == 200
    assert 'title' in response.context['form'].errors
    assert not Recipe.objects.filter(instructions__icontains='Mix and bake').exists()


@pytest.mark.django_db
def test_scratch_create_validation_missing_ingredients(client):
    url = reverse('recipes:scratch_add')
    data = {
        'title': 'No Ingredients Recipe',
        'ingredient_quantity': ['', ''],
        'ingredient_unit': ['', ''],
        'ingredient_food': ['', ''],
        'instruction_step': ['Mix and bake.'],
    }
    response = client.post(url, data)
    assert response.status_code == 200
    assert not response.context['form'].is_valid()
    assert 'ingredient_error' in response.context or any(
        'ingredient' in str(e).lower() for e in response.context['form'].non_field_errors()
    )
    assert not Recipe.objects.filter(title='No Ingredients Recipe').exists()


@pytest.mark.django_db
def test_scratch_create_validation_missing_instructions(client):
    url = reverse('recipes:scratch_add')
    data = {
        'title': 'No Instructions Recipe',
        'ingredient_quantity': ['1'],
        'ingredient_unit': ['cup'],
        'ingredient_food': ['flour'],
        'instruction_step': ['', '   '],
    }
    response = client.post(url, data)
    assert response.status_code == 200
    assert not response.context['form'].is_valid()
    assert 'instruction_error' in response.context or any(
        'instruction' in str(e).lower() for e in response.context['form'].non_field_errors()
    )
    assert not Recipe.objects.filter(title='No Instructions Recipe').exists()


@pytest.mark.django_db
def test_scratch_create_preserves_rows_on_validation_failure(client):
    url = reverse('recipes:scratch_add')
    data = {
        'title': '',  # missing title triggers validation failure
        'ingredient_quantity': ['1', '2'],
        'ingredient_unit': ['cup', 'tsp'],
        'ingredient_food': ['sugar', 'vanilla'],
        'instruction_step': ['First step.', 'Second step.'],
    }
    response = client.post(url, data)
    assert response.status_code == 200
    rows = response.context['ingredient_rows']
    assert len(rows) == 2
    assert rows[0]['food'] == 'sugar'
    assert rows[1]['food'] == 'vanilla'
    steps = response.context['instruction_steps']
    assert len(steps) == 2
    assert steps[0] == 'First step.'
    assert steps[1] == 'Second step.'


@pytest.mark.django_db
def test_scratch_create_empty_rows_filtered(client):
    url = reverse('recipes:scratch_add')
    data = {
        'title': 'Filtered Empty Rows',
        'ingredient_quantity': ['1', '', '2'],
        'ingredient_unit': ['cup', '', 'tbsp'],
        'ingredient_food': ['milk', '', 'butter'],
        'instruction_step': ['Step 1', '', 'Step 2'],
    }
    response = client.post(url, data)
    assert response.status_code == 302
    recipe = Recipe.objects.filter(title='Filtered Empty Rows').first()
    assert recipe is not None
    ingredients = list(recipe.recipe_ingredients.all().order_by('order'))
    assert len(ingredients) == 2
    assert ingredients[0].ingredient.name == 'milk'
    assert ingredients[0].order == 0
    assert ingredients[1].ingredient.name == 'butter'
    assert ingredients[1].order == 1


@pytest.mark.django_db
def test_scratch_create_navigation_links(client):
    # Main list page has "Create from Scratch" link
    list_resp = client.get(reverse('recipes:list_recipe'))
    assert list_resp.status_code == 200
    assert reverse('recipes:scratch_add') in list_resp.content.decode()

    # Saved for Later page also has "Create from Scratch" link
    future_resp = client.get(reverse('recipes:future_recipes'))
    assert future_resp.status_code == 200
    assert reverse('recipes:scratch_add') in future_resp.content.decode()


@pytest.mark.django_db
def test_scratch_create_text_fallback(client):
    url = reverse('recipes:scratch_add')
    data = {
        'title': 'Text Fallback Recipe',
        'ingredients_text': '1 cup sugar\n2 tsp cinnamon',
        'instructions_text': 'Mix together.',
    }
    response = client.post(url, data)
    assert response.status_code == 302
    recipe = Recipe.objects.filter(title='Text Fallback Recipe').first()
    assert recipe is not None
    ingredients = list(recipe.recipe_ingredients.all().order_by('order'))
    assert len(ingredients) == 2


@pytest.mark.django_db
def test_scratch_create_readonly_user(client):
    url = reverse('recipes:scratch_add')
    data = {
        'title': 'Readonly Scratch Recipe',
        'ingredient_quantity': ['1'],
        'ingredient_unit': ['cup'],
        'ingredient_food': ['oats'],
        'instruction_step': ['Boil water and add oats.'],
    }
    # Simulate a request where is_readonly is set by middleware
    from django.contrib.messages.middleware import MessageMiddleware
    from django.contrib.sessions.middleware import SessionMiddleware
    from django.test import RequestFactory
    from recipes.views import RecipeScratchCreateView

    factory = RequestFactory()
    request = factory.post(url, data)
    SessionMiddleware(lambda req: None).process_request(request)
    request.session.save()
    MessageMiddleware(lambda req: None).process_request(request)
    request.is_readonly = True
    response = RecipeScratchCreateView.as_view()(request)
    assert response.status_code == 302
    recipe = Recipe.objects.filter(title='Readonly Scratch Recipe').first()
    assert recipe is not None
    assert recipe.is_future is True
    assert recipe.is_on_menu is False


@pytest.mark.django_db
def test_scratch_create_error_messages_rendered_in_html(client):
    url = reverse('recipes:scratch_add')
    # Missing everything
    response = client.post(url, {})
    assert response.status_code == 200
    content = response.content.decode()
    # Check that error feedback is present
    assert "This field is required." in content or "required" in content
    assert "At least one ingredient is required." in content
    assert "At least one instruction step is required." in content


@pytest.mark.django_db
def test_scratch_create_preserves_tags_on_validation_failure(client):
    """Ensure user-entered tags are preserved in context when validation fails."""
    url = reverse('recipes:scratch_add')
    data = {
        'title': '',  # missing title triggers validation failure
        'tags': 'dinner, comfort food',
        'ingredient_quantity': ['1'],
        'ingredient_unit': ['cup'],
        'ingredient_food': ['flour'],
        'instruction_step': ['Bake at 350F.'],
    }
    response = client.post(url, data)
    assert response.status_code == 200
    assert 'initial_tags_json' in response.context
    tags_json = response.context['initial_tags_json']
    assert 'dinner' in tags_json
    assert 'comfort food' in tags_json
    assert response.context['initial_tags_csv'] == 'dinner, comfort food'


@pytest.mark.django_db
def test_scratch_create_form_with_python_dict():
    """Ensure RecipeScratchForm operates cleanly when bound to standard Python dicts."""
    from recipes.forms import RecipeScratchForm
    form = RecipeScratchForm(data={
        'title': 'Dict Test Recipe',
        'ingredient_quantity': ['1'],
        'ingredient_unit': ['cup'],
        'ingredient_food': ['sugar'],
        'instruction_step': ['Stir well.'],
    })
    assert form.is_valid(), form.errors
    assert len(form.cleaned_data['valid_ingredients']) == 1
    assert len(form.cleaned_data['valid_steps']) == 1


@pytest.mark.django_db
def test_scratch_create_validation_empty_marker_instruction(client):
    """Ensure steps that only contain bullet/number markers are rejected as empty."""
    url = reverse('recipes:scratch_add')
    data = {
        'title': 'Marker Step Recipe',
        'ingredient_quantity': ['1'],
        'ingredient_unit': ['cup'],
        'ingredient_food': ['flour'],
        'instruction_step': ['1. ', '• '],
    }
    response = client.post(url, data)
    assert response.status_code == 200
    assert not response.context['form'].is_valid()
    assert any('instruction' in str(e).lower() for e in response.context['form'].non_field_errors())


@pytest.mark.django_db
def test_scratch_create_validation_incomplete_ingredient_row(client):
    """Ensure rows specifying quantity/unit without a food name are rejected, preventing silent loss."""
    url = reverse('recipes:scratch_add')
    data = {
        'title': 'Incomplete Row Recipe',
        'ingredient_quantity': ['2'],
        'ingredient_unit': ['cups'],
        'ingredient_food': [''],  # missing food
        'instruction_step': ['Bake at 350F.'],
    }
    response = client.post(url, data)
    assert response.status_code == 200
    assert not response.context['form'].is_valid()
    assert any('ingredient name is missing' in str(e).lower() for e in response.context['form'].non_field_errors())


@pytest.mark.django_db
def test_scratch_create_validation_max_lengths(client):
    """Ensure exceeding maximum field lengths produces clean validation errors."""
    url = reverse('recipes:scratch_add')

    # Food > 100 characters
    data_long_food = {
        'title': 'Long Food Recipe',
        'ingredient_quantity': ['1'],
        'ingredient_unit': ['cup'],
        'ingredient_food': ['x' * 105],
        'instruction_step': ['Bake at 350F.'],
    }
    resp = client.post(url, data_long_food)
    assert resp.status_code == 200
    assert not resp.context['form'].is_valid()
    assert any('100 characters' in str(e) for e in resp.context['form'].non_field_errors())

    # Tag > 50 characters
    data_long_tag = {
        'title': 'Long Tag Recipe',
        'tags': 'x' * 55,
        'ingredient_quantity': ['1'],
        'ingredient_unit': ['cup'],
        'ingredient_food': ['flour'],
        'instruction_step': ['Bake at 350F.'],
    }
    resp_tag = client.post(url, data_long_tag)
    assert resp_tag.status_code == 200
    assert not resp_tag.context['form'].is_valid()
    assert 'tags' in resp_tag.context['form'].errors
    assert 'exceeds maximum length of 50 characters' in resp_tag.content.decode()


@pytest.mark.django_db
def test_scratch_create_raw_text_formatting_no_double_space(client):
    """Ensure raw_text omits redundant spaces when unit is empty."""
    url = reverse('recipes:scratch_add')
    data = {
        'title': 'Eggs Only Recipe',
        'ingredient_quantity': ['2'],
        'ingredient_unit': [''],
        'ingredient_food': ['large eggs'],
        'instruction_step': ['Whisk vigorously.'],
    }
    response = client.post(url, data)
    assert response.status_code == 302
    recipe = Recipe.objects.get(title='Eggs Only Recipe')
    ri = recipe.recipe_ingredients.first()
    assert ri.raw_text == '2 large eggs'
    assert '  ' not in ri.raw_text


@pytest.mark.django_db
def test_scratch_create_tag_deduplication(client):
    """Ensure duplicate tags are deduplicated case-insensitively."""
    url = reverse('recipes:scratch_add')
    data = {
        'title': 'Dedupe Tags Recipe',
        'tags': 'dinner, Dinner, quick, QUICK',
        'ingredient_quantity': ['1'],
        'ingredient_unit': ['cup'],
        'ingredient_food': ['rice'],
        'instruction_step': ['Steam rice.'],
    }
    response = client.post(url, data)
    assert response.status_code == 302
    recipe = Recipe.objects.get(title='Dedupe Tags Recipe')
    tags = list(recipe.tags.values_list('name', flat=True))
    assert len(tags) == 2
    assert set(t.lower() for t in tags) == {'dinner', 'quick'}


@pytest.mark.django_db
def test_scratch_create_numeric_and_symbolic_instructions_preserved(client):
    """Ensure non-alphabetic instructions like temperatures or ratios are not dropped."""
    url = reverse('recipes:scratch_add')
    data = {
        'title': 'Temperature Instruction Recipe',
        'ingredient_quantity': ['1'],
        'ingredient_unit': ['cup'],
        'ingredient_food': ['water'],
        'instruction_step': ['Boil water.', '100°', '20-25 @ 350°'],
    }
    response = client.post(url, data)
    assert response.status_code == 302
    recipe = Recipe.objects.get(title='Temperature Instruction Recipe')
    steps = recipe.instructions.splitlines()
    assert len(steps) == 3
    assert steps[1] == '100°'
    assert steps[2] == '20-25 @ 350°'


@pytest.mark.django_db
def test_scratch_create_unbound_form_safe():
    """Ensure RecipeScratchForm can be instantiated and cleaned unbound without AttributeError."""
    from recipes.forms import RecipeScratchForm
    form = RecipeScratchForm(data=None)
    assert form._get_list('ingredient_quantity') == []


@pytest.mark.django_db
def test_scratch_create_session_cleanup_prevents_stale_contamination(client):
    """Ensure preserved session data from failed import does not leak into subsequent scratch recipes."""
    # Step 1: Simulate failed import setting session flash data
    session = client.session
    session['failed_recipe_url'] = 'https://failed-import.com'
    session['preserved_form_data'] = {
        'rating': 5,
        'tags': 'stale-tag',
        'user_notes': 'Stale note from failed import',
    }
    session.save()

    # Step 2: First GET visit consumes preserved data
    resp1 = client.get(reverse('recipes:scratch_add'))
    assert resp1.status_code == 200
    assert resp1.context['initial_tags_csv'] == 'stale-tag'
    assert resp1.context['form'].initial.get('original_url') == 'https://failed-import.com'

    # Step 3: Subsequent GET visit for another scratch recipe is clean
    resp2 = client.get(reverse('recipes:scratch_add'))
    assert resp2.status_code == 200
    assert resp2.context['initial_tags_csv'] == ''
    assert resp2.context['form'].initial.get('original_url') is None
    assert resp2.context['form'].initial.get('user_notes') is None


@pytest.mark.django_db
def test_scratch_create_tag_slug_collision_handled(client):
    """Ensure tags whose slugs collide are created cleanly with unique slug counters."""
    url = reverse('recipes:scratch_add')
    data = {
        'title': 'Tag Collision Recipe',
        'tags': 'Dessert, Dessert!',
        'ingredient_quantity': ['1'],
        'ingredient_unit': ['cup'],
        'ingredient_food': ['sugar'],
        'instruction_step': ['Mix and serve.'],
    }
    response = client.post(url, data)
    assert response.status_code == 302
    recipe = Recipe.objects.get(title='Tag Collision Recipe')
    tags = list(recipe.tags.all())
    assert len(tags) == 2
    slugs = [t.slug for t in tags]
    assert len(set(slugs)) == 2  # Slugs must be distinct and non-colliding


@pytest.mark.django_db
def test_scratch_create_duplicate_ingredient_names_handled(client):
    """Ensure recipes with multiple rows using the same ingredient name (e.g. for batter and dusting) save cleanly."""
    url = reverse('recipes:scratch_add')
    data = {
        'title': 'Duplicate Ingredients Recipe',
        'ingredient_quantity': ['2', '2'],
        'ingredient_unit': ['cups', 'tbsp'],
        'ingredient_food': ['flour', 'flour'],
        'instruction_step': ['Mix batter.', 'Dust top with flour.'],
    }
    response = client.post(url, data)
    assert response.status_code == 302
    recipe = Recipe.objects.get(title='Duplicate Ingredients Recipe')
    ings = list(recipe.recipe_ingredients.all().order_by('order'))
    assert len(ings) == 2
    assert ings[0].ingredient.name == 'flour'
    assert ings[0].order == 0
    assert ings[0].quantity == '2'
    assert ings[0].unit == 'cups'
    assert ings[1].ingredient.name == 'flour'
    assert ings[1].order == 1
    assert ings[1].quantity == '2'
    assert ings[1].unit == 'tbsp'


@pytest.mark.django_db
def test_scratch_create_is_future_flag_persisted(client):
    """Ensure is_future checkbox is properly persisted when creating a recipe from scratch."""
    url = reverse('recipes:scratch_add')
    data = {
        'title': 'Future Recipe Scratch',
        'is_future': True,
        'ingredient_quantity': ['1'],
        'ingredient_unit': ['cup'],
        'ingredient_food': ['cocoa'],
        'instruction_step': ['Mix cocoa.'],
    }
    response = client.post(url, data)
    assert response.status_code == 302
    recipe = Recipe.objects.get(title='Future Recipe Scratch')
    assert recipe.is_future is True


@pytest.mark.django_db
def test_scratch_form_save_direct_populates_instructions():
    """Ensure RecipeScratchForm.save() sets instructions on Recipe instance even when called directly."""
    from recipes.forms import RecipeScratchForm
    form = RecipeScratchForm(data={
        'title': 'Direct Save Recipe',
        'ingredient_quantity': ['1'],
        'ingredient_unit': ['cup'],
        'ingredient_food': ['sugar'],
        'instruction_step': ['First step.', 'Second step.'],
    })
    assert form.is_valid(), form.errors
    # commit=False
    recipe_uncommitted = form.save(commit=False)
    assert recipe_uncommitted.instructions == 'First step.\nSecond step.'
    # commit=True
    recipe_committed = form.save(commit=True)
    assert recipe_committed.pk is not None
    recipe_from_db = Recipe.objects.get(pk=recipe_committed.pk)
    assert recipe_from_db.instructions == 'First step.\nSecond step.'


@pytest.mark.django_db
def test_scratch_create_tag_case_insensitive_reuse(client):
    """Ensure submitting a tag with different case reuses the existing tag rather than creating duplicate."""
    from recipes.models import RecipeTag
    existing_tag = RecipeTag.objects.create(name='Dinner', color='#E67E22')
    url = reverse('recipes:scratch_add')
    data = {
        'title': 'Dinner Recipe',
        'tags': 'dinner',
        'ingredient_quantity': ['1'],
        'ingredient_unit': ['cup'],
        'ingredient_food': ['rice'],
        'instruction_step': ['Cook rice.'],
    }
    response = client.post(url, data)
    assert response.status_code == 302
    recipe = Recipe.objects.get(title='Dinner Recipe')
    recipe_tags = list(recipe.tags.all())
    assert len(recipe_tags) == 1
    assert recipe_tags[0].id == existing_tag.id
    assert recipe_tags[0].name == 'Dinner'
    assert RecipeTag.objects.filter(name__iexact='dinner').count() == 1


@pytest.mark.django_db
def test_scratch_create_tag_color_preserved_case_insensitive(client):
    """Ensure get_context_data maps tag colors case-insensitively from existing tags."""
    from recipes.models import RecipeTag
    RecipeTag.objects.create(name='Comfort Food', color='#9B59B6')
    url = reverse('recipes:scratch_add')
    data = {
        'title': '',  # trigger validation failure
        'tags': 'comfort food',
        'ingredient_quantity': ['1'],
        'ingredient_unit': ['cup'],
        'ingredient_food': ['pasta'],
        'instruction_step': ['Boil pasta.'],
    }
    response = client.post(url, data)
    assert response.status_code == 200
    tags_json = json.loads(response.context['initial_tags_json'])
    assert len(tags_json) == 1
    assert tags_json[0]['name'] == 'comfort food'
    assert tags_json[0]['color'] == '#9B59B6'


def test_parse_ingredients_api_json(client):
    """Test parsing multiple ingredient lines via JSON request."""
    url = reverse('recipes:parse_ingredients_api')
    payload = {
        'text': "1 tablespoon olive oil\n1 unit Baby lettuce\n1 unit Beef stock concentrate\n2 tablespoon Mayonnaise"
    }
    response = client.post(url, data=json.dumps(payload), content_type='application/json')
    assert response.status_code == 200
    data = response.json()
    assert 'ingredients' in data
    ings = data['ingredients']
    assert len(ings) == 4
    # Olive oil
    assert ings[0]['quantity'] == '1'
    assert ings[0]['unit'] == 'tablespoon'
    assert 'olive oil' in ings[0]['food'].lower()
    # Baby lettuce (unit -> head)
    assert ings[1]['quantity'] == '1'
    assert ings[1]['unit'] == 'head'
    assert 'baby lettuce' in ings[1]['food'].lower()
    # Beef stock concentrate (unit -> packet)
    assert ings[2]['quantity'] == '1'
    assert ings[2]['unit'] == 'packet'
    assert 'beef stock concentrate' in ings[2]['food'].lower()
    # Mayonnaise (pluralized)
    assert ings[3]['quantity'] == '2'
    assert ings[3]['unit'] == 'tablespoons'
    assert 'mayonnaise' in ings[3]['food'].lower()


def test_parse_ingredients_api_empty(client):
    """Test parse API handles empty text gracefully."""
    url = reverse('recipes:parse_ingredients_api')
    response = client.post(url, data=json.dumps({'text': ''}), content_type='application/json')
    assert response.status_code == 200
    assert response.json() == {'ingredients': []}


@pytest.mark.django_db
def test_scratch_create_fallback_parses_full_line_in_quantity_field(client):
    """Ensure full ingredient strings entered in the quantity field are parsed automatically on submission."""
    from recipes.models import Recipe
    url = reverse('recipes:scratch_add')
    data = {
        'title': 'Fallback Paste Recipe',
        'ingredient_quantity': ['1 tablespoon olive oil'],
        'ingredient_unit': [''],
        'ingredient_food': [''],
        'instruction_step': ['Heat oil in pan.'],
    }
    response = client.post(url, data)
    assert response.status_code == 302
    recipe = Recipe.objects.get(title='Fallback Paste Recipe')
    ingredients = list(recipe.recipe_ingredients.all())
    assert len(ingredients) == 1
    assert ingredients[0].quantity == '1'
    assert ingredients[0].unit == 'tablespoon'
    assert 'olive oil' in ingredients[0].ingredient.name.lower()




