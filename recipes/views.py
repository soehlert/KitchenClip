from django.shortcuts import render, get_object_or_404
from django.utils.timezone import now
import datetime
from django.db import IntegrityError
from django.urls import reverse_lazy, reverse
from django.db.models import Q
from django.contrib import messages
from django.http import JsonResponse, HttpResponseRedirect
from functools import reduce
import operator
from urllib.parse import urlencode
from django.core.serializers.json import DjangoJSONEncoder

from recipe_scrapers import scrape_me
import ingredient_slicer
import json
from django.views.generic import (
    ListView, DetailView, CreateView, UpdateView, DeleteView
)
from django.core.exceptions import ValidationError
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt

from recipes.models import Recipe, Ingredient, RecipeIngredient, RecipeTag, MealPlan
from recipes.forms import RecipeImportForm, RecipeUpdateForm, RecipeManualForm
from recipes.utils import clean_instruction_line, extract_servings, is_valid_ingredient

import logging
logger = logging.getLogger(__name__)

def tag_autocomplete(request):
    q = request.GET.get("q", "")
    tags = RecipeTag.objects.filter(name__icontains=q).values("name", "color")
    return JsonResponse(list(tags), safe=False)

def move_to_recipes(request, pk):
    recipe = get_object_or_404(Recipe, pk=pk)
    recipe.is_future = False
    recipe.save()
    messages.success(request, f'"{recipe.title}" has been saved to your recipes!')
    return HttpResponseRedirect(reverse('recipes:detail_recipe', kwargs={'pk': pk}))

class RecipeListView(ListView):
    model = Recipe
    template_name = "recipes/recipe_list.html"
    context_object_name = "recipes"
    paginate_by = 15

    def get_queryset(self):
        queryset = Recipe.objects.filter(is_future=False)

        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) |
                Q(ingredients__name__icontains=search) |
                Q(description__icontains=search)
            ).distinct()

        time_ranges = self.request.GET.getlist('time_range')
        if time_ranges:
            time_conditions = []

            for time_range in time_ranges:
                if time_range == '0-20':
                    time_conditions.append(Q(total_time__lte=20))
                elif time_range == '21-30':
                    time_conditions.append(Q(total_time__range=(21, 30)))
                elif time_range == '31-45':
                    time_conditions.append(Q(total_time__range=(31, 45)))
                elif time_range == '46-60':
                    time_conditions.append(Q(total_time__range=(46, 60)))
                elif time_range == '60+':
                    time_conditions.append(Q(total_time__gt=60))

            if time_conditions:
                queryset = queryset.filter(reduce(operator.or_, time_conditions))

        tags = self.request.GET.getlist('tags')
        if tags:
            queryset = queryset.filter(tags__id__in=tags).distinct()

        return queryset.order_by('-updated_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['all_tags'] = RecipeTag.objects.all().order_by('name')
        context['page_title'] = "Recipes"
        return context


class FutureRecipeListView(RecipeListView):
    def get_queryset(self):
        queryset = Recipe.objects.filter(is_future=True)

        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) |
                Q(ingredients__name__icontains=search) |
                Q(description__icontains=search)
            ).distinct()

        # Re-use most of the logic but filter for future recipes
        # Actually, since we inherit from RecipeListView, we can just call super().get_queryset()
        # but we need to override the initial filter.

        # Let's just implement the filtering here to be safe and clear.
        # This is a bit redundant but cleaner for a quick implementation.
        # (Alternatively, we could refactor RecipeListView to take an is_future param)

        time_ranges = self.request.GET.getlist('time_range')
        if time_ranges:
            time_conditions = []
            for time_range in time_ranges:
                if time_range == '0-20':
                    time_conditions.append(Q(total_time__lte=20))
                elif time_range == '21-30':
                    time_conditions.append(Q(total_time__range=(21, 30)))
                elif time_range == '31-45':
                    time_conditions.append(Q(total_time__range=(31, 45)))
                elif time_range == '46-60':
                    time_conditions.append(Q(total_time__range=(46, 60)))
                elif time_range == '60+':
                    time_conditions.append(Q(total_time__gt=60))

            if time_conditions:
                queryset = queryset.filter(reduce(operator.or_, time_conditions))

        tags = self.request.GET.getlist('tags')
        if tags:
            queryset = queryset.filter(tags__id__in=tags).distinct()

        return queryset.order_by('-updated_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = "Future Ideas"
        return context


class RecipeDetailView(DetailView):
    model = Recipe
    template_name = "recipes/recipe_detail.html"
    context_object_name = "recipe"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        recipe = self.object

        context["instructions_list"] = [line for line in recipe.instructions.splitlines() if line.strip()]

        ingredients_with_confidence = []
        for i in recipe.recipe_ingredients.all():
            is_confident = is_valid_ingredient(i.quantity, i.unit, i.ingredient)
            ingredients_with_confidence.append({
                "ingredient": i,
                "is_confident": is_confident
            })
        context["ingredients_with_confidence"] = ingredients_with_confidence

        return context


class RecipeCreateView(CreateView):
    model = Recipe
    form_class = RecipeImportForm
    template_name = "recipes/recipe_form.html"
    success_url = reverse_lazy("recipes:list_recipe")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Add Recipe"
        context["heading"] = "Add Recipe by URL"
        context["button_text"] = "Import Recipe"
        context["show_delete"] = False
        all_tags = RecipeTag.objects.values("name", "color")
        context["all_tags_json"] = json.dumps(list(all_tags), cls=DjangoJSONEncoder)
        context["initial_tags_csv"] = ""

        return context

    def form_valid(self, form):
        original_url = form.cleaned_data["original_url"]

        try:
            scraper = scrape_me(original_url)
            form.instance.title = scraper.title()
            form.instance.description = getattr(scraper, "description", lambda: "")()
            form.instance.prep_time = scraper.prep_time()
            form.instance.cook_time = scraper.cook_time()
            form.instance.total_time = scraper.total_time()
            servings_raw = scraper.yields()
            form.instance.servings = extract_servings(servings_raw)
            raw_instructions = scraper.instructions()
            form.instance.instructions = clean_instruction_line(raw_instructions)
            form.instance.image_url = getattr(scraper, "image", lambda: "")()
            form.instance.original_url = original_url

            ingredient_lines = scraper.ingredients()
        except Exception:
            self.request.session['failed_recipe_url'] = original_url
            self.request.session['preserved_form_data'] = {
                'rating': form.cleaned_data.get('rating'),
                'tags': form.cleaned_data.get('tags', []),
                'user_notes': form.cleaned_data.get('user_notes', ''),
            }
            self.request.session.save()

            messages.info(
                self.request,
                "Couldn't automatically import this recipe. Please enter it manually below."
            )

            return HttpResponseRedirect(reverse('recipes:manual_add'))

        try:
            response = super().form_valid(form)
        except ValidationError:
            logger.exception("form_valid super call failed")
            raise

        try:
            for idx, line in enumerate(ingredient_lines):
                slicer = ingredient_slicer.IngredientSlicer(line)
                parsed = slicer.to_json()
                name = parsed.get("food") or line

                ingredient, _ = Ingredient.objects.get_or_create(name=name)

                RecipeIngredient.objects.create(
                    recipe=self.object,
                    ingredient=ingredient,
                    raw_text=line,
                    quantity=parsed.get("quantity") or "",
                    unit=parsed.get("unit") or "",
                    preparation=", ".join(parsed.get("prep", [])) if parsed.get("prep") else "",
                    order=idx
                )
        except (ValueError, TypeError):
            logger.exception("Ingredient processing failed")
            raise

        try:
            raw_tags = form.cleaned_data["tags"]
            if isinstance(raw_tags, str):
                tag_names = [tag.strip() for tag in raw_tags.split(",") if tag.strip()]
            else:
                tag_names = list(raw_tags)

            tag_objs = []
            for name in tag_names:
                slug = name.lower().replace(" ", "-")
                tag_obj, created = RecipeTag.objects.get_or_create(name=name, defaults={"slug": slug})
                tag_objs.append(tag_obj)
            self.object.tags.set(tag_objs)
        except (TypeError, AttributeError):
            logger.exception("Tag processing failed")
            raise

        return response


class RecipeManualCreateView(CreateView):
    model = Recipe
    form_class = RecipeManualForm
    template_name = "recipes/recipe_manual_form.html"
    success_url = reverse_lazy("recipes:list_recipe")

    def get_context_data(self, **kwargs):

        preserved_data = self.request.session.get('preserved_form_data', {})

        context = super().get_context_data(**kwargs)
        context["title"] = "Add Recipe Manually"
        context["heading"] = "Enter Recipe Details"
        context["button_text"] = "Save Recipe"
        context["show_delete"] = False
        all_tags = RecipeTag.objects.values("name", "color")
        context["all_tags_json"] = json.dumps(list(all_tags), cls=DjangoJSONEncoder)

        # Get preserved tags from session or form initial data
        preserved_data = self.request.session.get('preserved_form_data', {})
        preserved_tags = preserved_data.get('tags', '')

        if preserved_tags:
            initial_tags = []
            for tag_name in preserved_tags:
                initial_tags.append({"name": tag_name, "color": "#6B7280"})

            context["initial_tags_json"] = json.dumps(initial_tags, cls=DjangoJSONEncoder)
        else:
            context["initial_tags_json"] = json.dumps([], cls=DjangoJSONEncoder)

        return context

    def get_initial(self):
        initial = super().get_initial()

        failed_url = self.request.session.pop('failed_recipe_url', None)
        if failed_url:
            initial['original_url'] = failed_url

        preserved_data = self.request.session.get('preserved_form_data', {})
        if preserved_data:
            initial.update({
                'rating': preserved_data.get('rating'),
                'tags': preserved_data.get('tags', ''),
                'user_notes': preserved_data.get('user_notes', ''),
            })

        return initial

    def form_valid(self, form):
        response = super().form_valid(form)

        ingredients_text = form.cleaned_data.get('ingredients_text', '')
        for idx, line in enumerate(ingredients_text.split('\n')):
            line = line.strip()
            if line:
                slicer = ingredient_slicer.IngredientSlicer(line)
                parsed = slicer.to_json()
                name = parsed.get("food") or line

                ingredient, _ = Ingredient.objects.get_or_create(name=name)
                RecipeIngredient.objects.create(
                    recipe=self.object,
                    ingredient=ingredient,
                    raw_text=line,
                    quantity=parsed.get("quantity") or "",
                    unit=parsed.get("unit") or "",
                    preparation=", ".join(parsed.get("prep", [])) if parsed.get("prep") else "",
                    order=idx
                )

        raw_tags = form.cleaned_data["tags"]
        if isinstance(raw_tags, str):
            tag_names = [tag.strip() for tag in raw_tags.split(",") if tag.strip()]
        else:
            tag_names = list(raw_tags)

        tag_objs = []
        for name in tag_names:
            slug = name.lower().replace(" ", "-")
            tag_obj, created = RecipeTag.objects.get_or_create(name=name, defaults={"slug": slug})
            tag_objs.append(tag_obj)
        self.object.tags.set(tag_objs)

        return response


class RecipeUpdateView(UpdateView):
    model = Recipe
    form_class = RecipeUpdateForm
    template_name = "recipes/recipe_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Update Recipe"
        context["heading"] = "Update Recipe"
        context["button_text"] = "Update Recipe"
        context["show_delete"] = True
        context["recipe"] = self.object
        all_tags = RecipeTag.objects.values("name", "color", "slug")
        context["all_tags_json"] = json.dumps(list(all_tags), cls=DjangoJSONEncoder)

        initial_tags = []
        for tag in self.object.tags.all():
            initial_tags.append({"name": tag.name, "color": tag.color})
        context["initial_tags_json"] = json.dumps(initial_tags, cls=DjangoJSONEncoder)
        context["initial_tags_csv"] = ", ".join(self.object.tags.values_list("name", flat=True))

        return context

    def form_valid(self, form):
        form.instance.instructions = clean_instruction_line(form.instance.instructions)

        response = super().form_valid(form)
        raw_tags = form.cleaned_data["tags"]
        if isinstance(raw_tags, str):
            tag_names = [tag.strip() for tag in raw_tags.split(",") if tag.strip()]
        else:
            tag_names = list(raw_tags)
        tag_objs = []
        for name in tag_names:
            slug = name.lower().replace(" ", "-")
            tag_obj, created = RecipeTag.objects.get_or_create(name=name, defaults={"slug": slug})
            tag_objs.append(tag_obj)
        self.object.tags.set(tag_objs)

        return response


class RecipeDeleteView(DeleteView):
    model = Recipe
    template_name = "recipes/recipe_confirm_delete.html"
    success_url = reverse_lazy("recipes:list_recipe")

# --- Meal Plan Views ---

class MealPlanView(ListView):
    template_name = "recipes/meal_plan.html"
    context_object_name = "meal_plans"

    def get_queryset(self):
        # We handle data fetching in get_context_data to organize by date
        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Calculate the start date (the most recent Sunday)
        today = now().date()
        days_to_sunday = (today.weekday() + 1) % 7
        start_date = today - datetime.timedelta(days=days_to_sunday)
        
        # Calculate 14 days of the plan
        days = []
        for i in range(14):
            current_date = start_date + datetime.timedelta(days=i)
            lunch = MealPlan.objects.filter(date=current_date, meal_type='LUNCH').first()
            dinner = MealPlan.objects.filter(date=current_date, meal_type='DINNER').first()
            
            days.append({
                'date': current_date,
                'day_name': current_date.strftime('%A'),
                'is_today': current_date == today,
                'lunch': lunch,
                'dinner': dinner,
            })
            
        context['weeks'] = [days[0:7], days[7:14]]
        context['page_title'] = "Meal Plan"
        
        # Get recipes for the sidebar picker - split by status
        context['saved_recipes'] = Recipe.objects.filter(is_future=False).order_by('-updated_at')[:3]
        context['future_recipes'] = Recipe.objects.filter(is_future=True).order_by('-updated_at')[:3]
        
        return context

@csrf_exempt
@require_POST
def update_meal_plan(request):
    """API endpoint to update a meal plan slot."""
    try:
        data = json.loads(request.body)
        date_str = data.get('date')
        meal_type = data.get('meal_type')
        recipe_id = data.get('recipe_id')
        custom_meal = data.get('custom_meal', '')
        action = data.get('action', 'update') # update or delete
        
        if not date_str or not meal_type:
            return JsonResponse({'status': 'error', 'message': 'Missing date or meal type'}, status=400)
            
        plan_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        
        if action == 'delete':
            MealPlan.objects.filter(date=plan_date, meal_type=meal_type).delete()
            return JsonResponse({'status': 'success'})
            
        recipe = None
        if recipe_id:
            recipe = Recipe.objects.get(id=recipe_id)
            
        meal_plan, created = MealPlan.objects.update_or_create(
            date=plan_date,
            meal_type=meal_type,
            defaults={
                'recipe': recipe,
                'custom_meal': custom_meal if not recipe else ''
            }
        )
        
        return JsonResponse({
            'status': 'success',
            'meal_id': meal_plan.id,
            'title': recipe.title if recipe else custom_meal
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
    except Recipe.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Recipe not found'}, status=404)
    except Exception as e:
        logger.error(f"Meal plan update error: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

def search_recipes_api(request):
    """API endpoint for recipe search in the planner sidebar."""
    query = request.GET.get('q', '')
    recipes = Recipe.objects.filter(
        Q(title__icontains=query) | Q(ingredients__name__icontains=query)
    ).distinct()[:20]
    
    data = []
    for r in recipes:
        data.append({
            'id': r.id,
            'title': r.title,
            'is_future': r.is_future,
            'image_url': r.image_url
        })
        
    return JsonResponse({'recipes': data})
class MealPlanKioskView(MealPlanView):
    template_name = "recipes/meal_plan_kiosk.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['today'] = now().date()
        return context
