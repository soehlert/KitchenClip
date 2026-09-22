import datetime
import json
import logging
import operator
from functools import reduce

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.generic import (CreateView, DeleteView, DetailView, ListView,
                                  UpdateView)

from .forms import (RecipeImportForm, RecipeScratchForm,
                    RecipeUpdateForm)
from .ingredient_processor import parse_ingredient_line, process_ingredients
from .mixins import AdminRequiredMixin, require_admin
from .models import Ingredient, MealPlan, Recipe, RecipeIngredient, RecipeTag
from .parsers.registry import ParserRegistry
from .utils import clean_instruction_line, is_valid_ingredient

logger = logging.getLogger(__name__)

def tag_autocomplete(request):
    q = request.GET.get("q", "")
    tags = RecipeTag.objects.filter(name__icontains=q).values("name", "color")
    return JsonResponse(list(tags), safe=False)

@require_admin
@require_POST
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
        search = self.request.GET.get('search')
        if search:
            queryset = Recipe.objects.filter(
                Q(title__icontains=search) |
                Q(ingredients__name__icontains=search) |
                Q(description__icontains=search)
            ).distinct()
        else:
            queryset = Recipe.objects.filter(is_future=False)

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
        context['page_title'] = "Saved for Later"
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
            is_confident = is_valid_ingredient(i.quantity, i.unit, i.ingredient, raw_text=i.raw_text)
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

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['is_readonly'] = getattr(self.request, 'is_readonly', False)
        return kwargs

    def form_valid(self, form):
        original_url = form.cleaned_data["original_url"]

        try:
            parser = ParserRegistry.get_parser(original_url)
            form.instance.title = parser.title
            form.instance.description = parser.description
            form.instance.prep_time = parser.prep_time
            form.instance.cook_time = parser.cook_time
            form.instance.total_time = parser.total_time
            form.instance.servings = parser.servings
            form.instance.instructions = parser.instructions
            form.instance.image_url = parser.image_url
            form.instance.original_url = original_url

            if getattr(self.request, 'is_readonly', False):
                form.instance.is_future = True
                form.instance.is_on_menu = False

            ingredient_lines = parser.ingredients
        except Exception:
            logger.exception(f"RecipeCreateView: Parsing failed for {original_url}")
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

            return HttpResponseRedirect(reverse('recipes:scratch_add'))

        try:
            response = super().form_valid(form)
        except ValidationError:
            logger.exception("form_valid super call failed")
            raise

        try:
            # Parse all lines first
            parsed_list = []
            for line in ingredient_lines:
                parsed_item = parse_ingredient_line(line)
                parsed_list.append(parsed_item)
            
            # Process (consolidate, format, normalize)
            processed_ingredients = process_ingredients(parsed_list)

            for idx, item in enumerate(processed_ingredients):
                name = item["food"]
                ingredient, _ = Ingredient.objects.get_or_create(name=name)
                
                RecipeIngredient.objects.create(
                    recipe=self.object,
                    ingredient=ingredient,
                    raw_text=f"{item['display_quantity']} {item['unit']} {name}".strip(),
                    quantity=item["display_quantity"],
                    unit=item["unit"],
                    order=idx
                )
        except Exception:
            logger.exception("Failed to process ingredients")
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


class RecipeScratchCreateView(CreateView):
    model = Recipe
    form_class = RecipeScratchForm
    template_name = "recipes/recipe_scratch_form.html"

    def get_success_url(self):
        return self.object.get_absolute_url()

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['is_readonly'] = getattr(self.request, 'is_readonly', False)
        return kwargs

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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Create Recipe from Scratch"
        context["heading"] = "Create Recipe from Scratch"
        context["button_text"] = "Create Recipe"
        context["show_delete"] = False

        all_tags = list(RecipeTag.objects.values("name", "color"))
        context["all_tags_json"] = json.dumps(all_tags, cls=DjangoJSONEncoder)
        tag_color_map = {t["name"].lower(): t["color"] for t in all_tags}

        preserved_data = self.request.session.get('preserved_form_data', {})
        # Preserve tags on validation failure (POST) or from session redirect
        raw_tags = ""
        if self.request.method == "POST":
            raw_tags = self.request.POST.get('tags', '')
        elif preserved_data:
            p_tags = preserved_data.get('tags', '')
            if isinstance(p_tags, list):
                raw_tags = ", ".join(p_tags)
            elif isinstance(p_tags, str):
                raw_tags = p_tags

        if raw_tags:
            tag_names = [t.strip() for t in raw_tags.split(",") if t.strip()]
            initial_tags = [
                {"name": t, "color": tag_color_map.get(t.lower(), "#6B7280")}
                for t in tag_names
            ]
            context["initial_tags_json"] = json.dumps(initial_tags, cls=DjangoJSONEncoder)
            context["initial_tags_csv"] = ", ".join(tag_names)
        else:
            context["initial_tags_json"] = json.dumps([], cls=DjangoJSONEncoder)
            context["initial_tags_csv"] = ""

        # Handle dynamic rows in context
        if self.request.method == "POST":
            quantities = self.request.POST.getlist('ingredient_quantity')
            units = self.request.POST.getlist('ingredient_unit')
            foods = self.request.POST.getlist('ingredient_food') or self.request.POST.getlist('ingredient_name')
            max_len = max(len(quantities), len(units), len(foods))
            ingredient_rows = []
            for i in range(max_len):
                ingredient_rows.append({
                    'quantity': quantities[i] if i < len(quantities) else '',
                    'unit': units[i] if i < len(units) else '',
                    'food': foods[i] if i < len(foods) else '',
                })
            context["ingredient_rows"] = ingredient_rows if ingredient_rows else [{'quantity': '', 'unit': '', 'food': ''}]

            steps = self.request.POST.getlist('instruction_step')
            context["instruction_steps"] = steps if steps else ['']
        else:
            context["ingredient_rows"] = [
                {'quantity': '', 'unit': '', 'food': ''},
                {'quantity': '', 'unit': '', 'food': ''},
                {'quantity': '', 'unit': '', 'food': ''},
            ]
            context["instruction_steps"] = ['', '']

        form = context.get('form')
        if form and form.errors:
            for err in form.non_field_errors():
                err_str = str(err)
                if "ingredient" in err_str.lower():
                    context["ingredient_error"] = err_str
                if "instruction" in err_str.lower():
                    context["instruction_error"] = err_str

        # On GET, once preserved session data has been consumed for initial display, clear it
        if self.request.method == "GET":
            self.request.session.pop('failed_recipe_url', None)
            self.request.session.pop('preserved_form_data', None)

        return context

    def form_valid(self, form):
        with transaction.atomic():
            valid_steps = form.cleaned_data.get('valid_steps', [])
            form.instance.instructions = "\n".join(valid_steps)

            if getattr(self.request, 'is_readonly', False):
                form.instance.is_future = True
                form.instance.is_on_menu = False

            response = super().form_valid(form)

            valid_ingredients = form.cleaned_data.get('valid_ingredients', [])
            order_idx = 0
            for item in valid_ingredients:
                if "food" in item:
                    food_name = item["food"]
                    qty = item.get("quantity", "")
                    unit = item.get("unit", "")
                    raw_text = " ".join(filter(None, [qty, unit, food_name]))
                    ingredient, _ = Ingredient.objects.get_or_create(name=food_name[:100])
                    RecipeIngredient.objects.create(
                        recipe=self.object,
                        ingredient=ingredient,
                        raw_text=raw_text[:200],
                        quantity=qty[:50],
                        unit=unit[:50],
                        order=order_idx
                    )
                    order_idx += 1
                elif "raw_text" in item:
                    parsed_item = parse_ingredient_line(item["raw_text"])
                    processed = process_ingredients([parsed_item])
                    for p in processed:
                        p_name = p["food"]
                        ingredient, _ = Ingredient.objects.get_or_create(name=p_name[:100])
                        p_qty = p.get('display_quantity', '')
                        p_unit = p.get('unit', '')
                        raw_text = " ".join(filter(None, [p_qty, p_unit, p_name]))
                        RecipeIngredient.objects.create(
                            recipe=self.object,
                            ingredient=ingredient,
                            raw_text=raw_text[:200],
                            quantity=p_qty[:50],
                            unit=p_unit[:50],
                            order=order_idx
                        )
                        order_idx += 1

            raw_tags = form.cleaned_data.get("tags", [])
            if isinstance(raw_tags, str):
                tag_names = [tag.strip() for tag in raw_tags.split(",") if tag.strip()]
            else:
                tag_names = list(raw_tags)

            tag_objs = []
            for name in tag_names:
                tag_name = name[:50]
                existing_tag = RecipeTag.objects.filter(name__iexact=tag_name).first()
                if existing_tag:
                    tag_obj = existing_tag
                else:
                    tag_obj, _ = RecipeTag.objects.get_or_create(name=tag_name)
                tag_objs.append(tag_obj)
            self.object.tags.set(tag_objs)

            self.request.session.pop('failed_recipe_url', None)
            self.request.session.pop('preserved_form_data', None)

            messages.success(self.request, f'Recipe "{self.object.title}" created successfully!')
            return response


class RecipeUpdateView(AdminRequiredMixin, UpdateView):
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


class RecipeDeleteView(AdminRequiredMixin, DeleteView):
    model = Recipe
    template_name = "recipes/recipe_confirm_delete.html"
    success_url = reverse_lazy("recipes:list_recipe")

# --- Meal Plan Views ---

class MealPlanView(AdminRequiredMixin, ListView):
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
        context.update(get_sidebar_context(request=self.request))
        
        return context

def get_sidebar_context(request, saved_page=1, future_page=1):
    """Helper to get paginated sidebar recipes."""
    
    saved_qs = Recipe.objects.filter(is_future=False, is_on_menu=True).order_by('-updated_at')
    future_qs = Recipe.objects.filter(is_future=True, is_on_menu=True).order_by('-updated_at')
    
    saved_paginator = Paginator(saved_qs, 7)
    future_paginator = Paginator(future_qs, 7)
    
    saved_recipes = saved_paginator.get_page(saved_page)
    future_recipes = future_paginator.get_page(future_page)
    
    return {
        'saved_recipes': saved_recipes,
        'future_recipes': future_recipes,
        'saved_has_next': saved_recipes.has_next(),
        'saved_has_prev': saved_recipes.has_previous(),
        'saved_page_num': saved_recipes.number,
        'future_has_next': future_recipes.has_next(),
        'future_has_prev': future_recipes.has_previous(),
        'future_page_num': future_recipes.number,
    }

@csrf_exempt
@require_POST
@require_admin
def toggle_menu_status(request):
    """API endpoint to add/remove a recipe from the menu sidebar."""
    try:
        data = json.loads(request.body)
        recipe_id = data.get('recipe_id')
        if not recipe_id:
            return JsonResponse({'status': 'error', 'message': 'Missing recipe_id'}, status=400)
            
        recipe = get_object_or_404(Recipe, id=recipe_id)
        recipe.is_on_menu = not recipe.is_on_menu
        recipe.save()
        
        return JsonResponse({
            'status': 'success',
            'is_on_menu': recipe.is_on_menu,
            'title': recipe.title
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

def sidebar_pagination_api(request):
    """API endpoint to get paginated sidebar sections."""
    saved_page = request.GET.get('saved_page', 1)
    future_page = request.GET.get('future_page', 1)
    
    context = get_sidebar_context(request, saved_page, future_page)
    
    
    saved_html = render_to_string('recipes/partials/_sidebar_section.html', {
        'recipes': context['saved_recipes'],
        'has_next': context['saved_has_next'],
        'has_prev': context['saved_has_prev'],
        'page_num': context['saved_page_num'],
        'type': 'saved'
    }, request=request)
    
    future_html = render_to_string('recipes/partials/_sidebar_section.html', {
        'recipes': context['future_recipes'],
        'has_next': context['future_has_next'],
        'has_prev': context['future_has_prev'],
        'page_num': context['future_page_num'],
        'type': 'future'
    }, request=request)
    
    return JsonResponse({
        'saved_html': saved_html,
        'future_html': future_html
    })

@csrf_exempt
@require_POST
@require_admin
def update_meal_plan(request):
    """API endpoint to update a meal plan slot."""
    try:
        data = json.loads(request.body)
        date_str = data.get('date')
        meal_type = data.get('meal_type')
        recipe_id = data.get('recipe_id')
        custom_meal = data.get('custom_meal', '')
        action = data.get('action', 'update') # update or delete
        ready_at = data.get('ready_at')
        
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
                'custom_meal': custom_meal if not recipe else '',
                'ready_at': ready_at if ready_at else None
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
            'is_on_menu': r.is_on_menu,
            'image_url': r.image_url
        })
        
    return JsonResponse({'recipes': data})


@csrf_exempt
@require_POST
def parse_ingredients_api(request):
    """API endpoint to parse ingredient text into structured items."""
    try:
        if request.content_type == 'application/json':
            payload = json.loads(request.body.decode('utf-8'))
            text = payload.get('text', '')
            lines = payload.get('lines', [])
            if not lines and text:
                lines = text.splitlines()
        else:
            text = request.POST.get('text', '')
            lines = request.POST.getlist('lines')
            if not lines and text:
                lines = text.splitlines()

        clean_lines = [line.strip() for line in lines if line and line.strip()]
        if not clean_lines:
            return JsonResponse({'ingredients': []})

        parsed_items = [parse_ingredient_line(line) for line in clean_lines]
        processed = process_ingredients(parsed_items)

        results = []
        for p in processed:
            results.append({
                'food': p.get('food', ''),
                'unit': p.get('unit', ''),
                'quantity': p.get('display_quantity', ''),
                'prep': p.get('prep', ''),
            })

        return JsonResponse({'ingredients': results})
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.exception("Failed to parse ingredients via API")
        return JsonResponse({'error': str(e)}, status=500)

class MealPlanKioskView(MealPlanView):
    template_name = "recipes/meal_plan_kiosk.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['today'] = now().date()
        return context
