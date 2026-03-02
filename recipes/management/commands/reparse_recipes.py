import json
import logging
import re
from django.core.management.base import BaseCommand
from django.db import transaction
from recipes.models import Recipe, Ingredient, RecipeIngredient
from recipes.parsers.registry import ParserRegistry
from recipes.ingredient_processor import process_ingredients, format_time_h_m
import ingredient_slicer

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Re-parse ingredients and metadata for existing recipes.'

    def add_arguments(self, parser):
        parser.add_argument('--recipe-id', type=int, help='ID of the recipe to re-parse')
        parser.add_argument('--all', action='store_true', help='Re-parse all recipes')
        parser.add_argument('--dry-run', action='store_true', help='Show changes without saving')

    def handle(self, *args, **options):
        recipe_id = options.get('recipe_id')
        reparse_all = options.get('all')
        dry_run = options.get('dry_run')

        if not recipe_id and not reparse_all:
            self.stderr.write(self.style.ERROR('Please specify --recipe-id or --all'))
            return

        if recipe_id:
            recipes = Recipe.objects.filter(id=recipe_id)
        else:
            recipes = Recipe.objects.all()

        total = recipes.count()
        self.stdout.write(f"Processing {total} recipes")

        for recipe in recipes:
            self.stdout.write(f"Processing recipe: {recipe.title} (ID: {recipe.id})")
            try:
                self.reparse_recipe(recipe, dry_run)
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Error processing recipe {recipe.id}: {e}"))
                logger.exception(f"Failed to re-parse recipe {recipe.id}")

    def reparse_recipe(self, recipe, dry_run):
        ingredient_lines = []
        metadata = {}

        if recipe.original_url:
            self.stdout.write(f"Fetching from URL: {recipe.original_url}")
            try:
                parser = ParserRegistry.get_parser(recipe.original_url)
                ingredient_lines = parser.ingredients
                metadata = {
                    'title': parser.title,
                    'description': parser.description,
                    'prep_time': parser.prep_time,
                    'cook_time': parser.cook_time,
                    'total_time': parser.total_time,
                    'servings': parser.servings,
                    'instructions': parser.instructions,
                    'image_url': parser.image_url,
                }
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Failed to parse URL, falling back to existing ingredients: {e}"))
                # Fallback to existing ingredients if URL parsing fails
                ingredient_lines = list(recipe.recipe_ingredients.values_list('raw_text', flat=True))
        else:
            self.stdout.write("No URL found, re-processing existing ingredients.")
            ingredient_lines = list(recipe.recipe_ingredients.values_list('raw_text', flat=True))

        if not ingredient_lines:
            self.stdout.write(self.style.WARNING("No ingredients found to process."))
            return

        # Parse all lines
        parsed_list = []
        for line in ingredient_lines:
            if not line.strip():
                continue
            slicer = ingredient_slicer.IngredientSlicer(line)
            parsed_item = slicer.to_json()

            # Clean "unit" out of food name if it's there (often from ingredient-slicer)
            food = (parsed_item.get("food") or "").strip()
            if food:
                food = re.sub(r'\bunit\b', '', food, flags=re.IGNORECASE).strip()
                parsed_item["food"] = food
            
            # If food becomes empty after cleaning, skip this item
            if not parsed_item.get("food"):
                continue

            parsed_list.append(parsed_item)

        # Process (consolidate, format, normalize)
        processed_ingredients = process_ingredients(parsed_list)

        if dry_run:
            self.stdout.write("[Dry Run] Proposed changes:")
            if metadata:
                self.stdout.write("- Metadata:")
                for key, val in metadata.items():
                    old_val = getattr(recipe, key, None)
                    display_old = old_val
                    display_new = val
                    if key in ['prep_time', 'cook_time', 'total_time']:
                        display_old = format_time_h_m(old_val) if old_val else "None"
                        display_new = format_time_h_m(val) if val else "None"
                    
                    is_changed = old_val != val
                    status = "(Changed)" if is_changed else "(Unchanged)"
                    self.stdout.write(f"* {key}: {display_old} -> {display_new} {status}")
            
            self.stdout.write("- Ingredients:")
            for item in processed_ingredients:
                parts = [str(item['display_quantity']), str(item['unit']), item['food']]
                self.stdout.write(f"* {' '.join(p for p in parts if p).strip()}")
            return

        # Apply changes
        with transaction.atomic():
            # Update metadata if available
            if metadata:
                for key, val in metadata.items():
                    if val is not None:
                        setattr(recipe, key, val)
                recipe.save()

            # Replace ingredients
            recipe.recipe_ingredients.all().delete()
            
            for idx, item in enumerate(processed_ingredients):
                name = item["food"]
                ingredient, _ = Ingredient.objects.get_or_create(name=name)
                
                parts = [str(item['display_quantity']), str(item['unit']), name]
                raw_text = " ".join(p for p in parts if p).strip()
                
                RecipeIngredient.objects.create(
                    recipe=recipe,
                    ingredient=ingredient,
                    raw_text=raw_text,
                    quantity=item["display_quantity"],
                    unit=item["unit"],
                    order=idx
                )
            
            self.stdout.write(self.style.SUCCESS(f"Successfully updated recipe {recipe.id}"))
