from django.shortcuts import render
from django.db import IntegrityError
from django.urls import reverse_lazy, reverse
from django.db.models import Q
from django.contrib import messages
from django.http import JsonResponse, HttpResponseRedirect
from urllib.parse import urlencode
from django.core.serializers.json import DjangoJSONEncoder

from recipe_scrapers import scrape_me
import ingredient_slicer
import json
from django.views.generic import (
    ListView, DetailView, CreateView, UpdateView, DeleteView
)
from django.core.exceptions import ValidationError

from recipes.models import Recipe, Ingredient, RecipeIngredient, RecipeTag
from recipes.forms import RecipeImportForm, RecipeUpdateForm, RecipeManualForm
from recipes.utils import clean_instruction_line, extract_servings, is_valid_ingredient

import logging
logger = logging.getLogger(__name__)

def tag_autocomplete(request):
    q = request.GET.get("q", "")
    tags = RecipeTag.objects.filter(name__icontains=q).values("name", "color")
    return JsonResponse(list(tags), safe=False)

class RecipeListView(ListView):
    model = Recipe
    template_name = "recipes/recipe_list.html"
    context_object_name = "recipes"
    paginate_by = 20

    def get_queryset(self):
        queryset = Recipe.objects.all()

        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) |
                Q(ingredients__name__icontains=search) |
                Q(description__icontains=search)
            ).distinct()

        tags = self.request.GET.getlist('tags')
        if tags:
            queryset = queryset.filter(tags__id__in=tags).distinct()

        return queryset.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['all_tags'] = RecipeTag.objects.all().order_by('name')
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
                'tags': form.cleaned_data.get('tags', ''),
                'user_notes': form.cleaned_data.get('user_notes', ''),
            }

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
        context = super().get_context_data(**kwargs)
        context["title"] = "Add Recipe Manually"
        context["heading"] = "Enter Recipe Details"
        context["button_text"] = "Save Recipe"
        context["show_delete"] = False
        all_tags = RecipeTag.objects.values("name", "color")
        context["all_tags_json"] = json.dumps(list(all_tags), cls=DjangoJSONEncoder)
        context["initial_tags_json"] = json.dumps([], cls=DjangoJSONEncoder)

        return context

    def get_initial(self):
        initial = super().get_initial()

        failed_url = self.request.session.pop('failed_recipe_url', None)
        if failed_url:
            initial['original_url'] = failed_url

        preserved_data = self.request.session.pop('preserved_form_data', {})
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