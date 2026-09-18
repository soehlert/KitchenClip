import logging
import re

import ingredient_slicer
from django import forms

from .ingredient_processor import process_ingredients
from .models import Ingredient, Recipe, RecipeIngredient

logger = logging.getLogger(__name__)

INSTRUCTION_MARKER_REGEX = re.compile(
    r'^(?:(?:Step\s*\d*[:.)\-]+)|(?:\(?\d+[.)\]:-]+)|(?:[•◦▪▫*–—\-]+))\s*$',
    re.IGNORECASE,
)

RATING_CHOICES = [(i, str(i)) for i in range(1, 6)]

class RecipeImportForm(forms.ModelForm):
    original_url = forms.URLField(
        label="Recipe URL",
        required=True,
        assume_scheme='https',
        widget=forms.URLInput(attrs={
            "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]"
        })
    )
    rating = forms.ChoiceField(
        choices=[('', '—')] + RATING_CHOICES,
        required=False,
        label="Rating",
        widget=forms.Select(attrs={
            "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]"
        })
    )
    tags = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]",
            "placeholder": "e.g. quick, weeknight, dessert, appetizer",
            "autocomplete": "off",
            "id": "id_tags",
        })
    )

    class Meta:
        model = Recipe
        fields = ["original_url", "user_notes", "rating", "is_future"]
        widgets = {
            "user_notes": forms.Textarea(attrs={
                "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]",
                "rows": 3,
            }),
            "is_future": forms.CheckboxInput(attrs={
                "class": "w-4 h-4 text-[#194769] border-[#5B8E7D] rounded focus:ring-[#194769]"
            }),
        }

    def clean_rating(self):
        value = self.cleaned_data['rating']
        return int(value) if value else None

    def clean_tags(self):
        tags = self.cleaned_data.get("tags", "")
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        return tag_list

    def __init__(self, *args, **kwargs):
        self.is_readonly = kwargs.pop('is_readonly', False)
        super().__init__(*args, **kwargs)
        if self.is_readonly and 'is_future' in self.fields:
            del self.fields['is_future']


class RecipeUpdateForm(forms.ModelForm):
    rating = forms.ChoiceField(
        choices=[('', '—')] + RATING_CHOICES,
        required=False,
        label="Rating",
        widget=forms.Select(attrs={
            "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]"
        })
    )
    tags = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]",
            "placeholder": "e.g. quick, weeknight, dessert, appetizer",
            "autocomplete": "off",
            "id": "id_tags",
        })
    )
    ingredients_text = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]",
            "rows": 8,
            "placeholder": "Enter each ingredient on a new line:\n1 cup flour\n2 eggs\n1/2 cup sugar"
        }),
        label="Ingredients",
        help_text="Enter each ingredient on a separate line"
    )

    class Meta:
        model = Recipe
        fields = [
            "title", "description", "original_url",
            "prep_time", "cook_time", "total_time", "servings",
            "rating", "instructions", "user_notes",
            "image_url", "is_future"
        ]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]"
            }),
            "description": forms.Textarea(attrs={
                "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]",
                "rows": 3,
            }),
            "original_url": forms.URLInput(attrs={
                "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]"
            }),
            "prep_time": forms.NumberInput(attrs={
                "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]"
            }),
            "cook_time": forms.NumberInput(attrs={
                "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]"
            }),
            "total_time": forms.NumberInput(attrs={
                "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]"
            }),
            "servings": forms.NumberInput(attrs={
                "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]"
            }),
            "instructions": forms.Textarea(attrs={
                "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]",
                "rows": 6,
            }),
            "user_notes": forms.Textarea(attrs={
                "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]",
                "rows": 3,
            }),
            "image_url": forms.URLInput(attrs={
                "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]"
            }),
            "is_future": forms.CheckboxInput(attrs={
                "class": "w-4 h-4 text-[#194769] border-[#5B8E7D] rounded focus:ring-[#194769]"
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tags_value = self.initial.get('tags')
        if tags_value is None and self.instance.pk:
            tags_value = list(self.instance.tags.values_list('name', flat=True))
        if tags_value in ([], None):
            self.initial['tags'] = ''
        elif isinstance(tags_value, list):
            self.initial['tags'] = ', '.join(tags_value)

        if self.instance.pk:
            existing_ingredients = self.instance.recipe_ingredients.order_by('order')
            ingredients_list = [ing.raw_text for ing in existing_ingredients]
            self.initial['ingredients_text'] = '\n'.join(ingredients_list)

    def save(self, commit=True):
        recipe = super().save(commit=commit)

        if commit and 'ingredients_text' in self.cleaned_data:
            recipe.recipe_ingredients.all().delete()

            ingredients_text = self.cleaned_data.get('ingredients_text', '')
            try:
                # Parse all lines
                parsed_list = []
                for line in ingredients_text.split('\n'):
                    line = line.strip()
                    if line:
                        slicer = ingredient_slicer.IngredientSlicer(line)
                        parsed_list.append(slicer.to_json())
                
                # Consolidate and format
                processed = process_ingredients(parsed_list)

                for idx, item in enumerate(processed):
                    name = item["food"]
                    ingredient, _ = Ingredient.objects.get_or_create(name=name)
                    
                    RecipeIngredient.objects.create(
                        recipe=recipe,
                        ingredient=ingredient,
                        raw_text=f"{item['display_quantity']} {item['unit']} {name}".strip(),
                        quantity=item["display_quantity"],
                        unit=item["unit"],
                        order=idx
                    )
            except Exception as e:
                logger.warning(f"Failed to process ingredients during update: {e}")

        return recipe

    def clean_original_url(self):
        url = self.cleaned_data.get('original_url')
        return url if url else None

    def clean_rating(self):
        value = self.cleaned_data['rating']
        return int(value) if value else None

    def clean_tags(self):
        tags = self.cleaned_data.get("tags", "")
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        return tag_list


class RecipeScratchForm(forms.ModelForm):
    title = forms.CharField(
        max_length=200,
        required=True,
        label="Title",
        widget=forms.TextInput(attrs={
            "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]",
            "placeholder": "Recipe Title"
        })
    )
    description = forms.CharField(
        required=False,
        label="Description",
        widget=forms.Textarea(attrs={
            "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]",
            "rows": 2,
            "placeholder": "Brief description or overview (optional)"
        })
    )
    user_notes = forms.CharField(
        required=False,
        label="Notes",
        widget=forms.Textarea(attrs={
            "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]",
            "rows": 2,
            "placeholder": "Personal notes, substitutions, or tips (optional)"
        })
    )
    prep_time = forms.IntegerField(
        required=False,
        min_value=0,
        label="Prep Time (mins)",
        widget=forms.NumberInput(attrs={
            "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]",
            "min": "0",
            "placeholder": "e.g. 15"
        })
    )
    cook_time = forms.IntegerField(
        required=False,
        min_value=0,
        label="Cook Time (mins)",
        widget=forms.NumberInput(attrs={
            "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]",
            "min": "0",
            "placeholder": "e.g. 30"
        })
    )
    total_time = forms.IntegerField(
        required=False,
        min_value=0,
        label="Total Time (mins)",
        widget=forms.NumberInput(attrs={
            "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]",
            "min": "0",
            "placeholder": "e.g. 45"
        })
    )
    servings = forms.IntegerField(
        required=False,
        min_value=1,
        label="Servings",
        widget=forms.NumberInput(attrs={
            "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]",
            "min": "1",
            "placeholder": "e.g. 4"
        })
    )
    rating = forms.ChoiceField(
        choices=[('', '—')] + RATING_CHOICES,
        required=False,
        label="Rating",
        widget=forms.Select(attrs={
            "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]"
        })
    )
    tags = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]",
            "placeholder": "e.g. quick, weeknight, dessert, appetizer",
            "autocomplete": "off",
            "id": "id_tags",
        })
    )
    image_url = forms.URLField(
        max_length=300,
        required=False,
        label="Image URL",
        assume_scheme='https',
        widget=forms.URLInput(attrs={
            "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]",
            "placeholder": "https://example.com/recipe-image.jpg"
        })
    )
    original_url = forms.URLField(
        max_length=200,
        required=False,
        label="Original URL (optional)",
        assume_scheme='https',
        widget=forms.URLInput(attrs={
            "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]",
            "placeholder": "https://example.com/recipe (optional)"
        })
    )
    is_future = forms.BooleanField(
        required=False,
        label="Future",
        help_text="Save to try in the future",
        widget=forms.CheckboxInput(attrs={
            "class": "w-4 h-4 text-[#194769] border-[#5B8E7D] rounded focus:ring-[#194769]"
        })
    )
    ingredients_text = forms.CharField(required=False, widget=forms.HiddenInput())
    instructions_text = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = Recipe
        fields = [
            "title", "description", "original_url", "rating", "image_url",
            "prep_time", "cook_time", "total_time", "servings", "user_notes", "is_future"
        ]

    def __init__(self, *args, **kwargs):
        self.is_readonly = kwargs.pop('is_readonly', False)
        super().__init__(*args, **kwargs)
        if self.is_readonly and 'is_future' in self.fields:
            del self.fields['is_future']

    def save(self, commit=True):
        recipe = super().save(commit=False)
        valid_steps = self.cleaned_data.get('valid_steps', [])
        recipe.instructions = "\n".join(valid_steps)
        if commit:
            recipe.save()
        return recipe

    def clean_original_url(self):
        url = self.cleaned_data.get('original_url')
        return url if url else None

    def clean_rating(self):
        value = self.cleaned_data.get('rating')
        return int(value) if value else None

    def clean_tags(self):
        tags = self.cleaned_data.get("tags", "")
        if isinstance(tags, str):
            raw_list = [t.strip() for t in tags.split(",") if t.strip()]
        elif isinstance(tags, list):
            raw_list = [str(t).strip() for t in tags if str(t).strip()]
        else:
            raw_list = []

        seen = set()
        deduped = []
        for t in raw_list:
            if len(t) > 50:
                raise forms.ValidationError(f"Tag '{t[:20]}...' exceeds maximum length of 50 characters.")
            t_lower = t.lower()
            if t_lower not in seen:
                seen.add(t_lower)
                deduped.append(t)
        return deduped

    def _get_list(self, key):
        """Safely retrieve a list of values from either QueryDict or standard Python dict."""
        if not self.data:
            return []
        if hasattr(self.data, 'getlist'):
            return self.data.getlist(key)
        val = self.data.get(key, [])
        if isinstance(val, list):
            return val
        if val is None or val == '':
            return []
        return [val]

    def clean(self):
        cleaned_data = super().clean()

        # Check structured ingredient rows
        quantities = self._get_list('ingredient_quantity')
        units = self._get_list('ingredient_unit')
        foods = self._get_list('ingredient_food') or self._get_list('ingredient_name')

        max_len = max(len(quantities), len(units), len(foods)) if (quantities or units or foods) else 0

        valid_ingredients = []
        has_incomplete_row = False
        has_length_error = False

        for i in range(max_len):
            food_val = foods[i] if i < len(foods) else ""
            qty_val = quantities[i] if i < len(quantities) else ""
            unit_val = units[i] if i < len(units) else ""

            food_clean = str(food_val).strip() if food_val else ""
            qty_clean = str(qty_val).strip() if qty_val else ""
            unit_clean = str(unit_val).strip() if unit_val else ""

            # Check if user entered quantity/unit but omitted food name
            if not food_clean and (qty_clean or unit_clean):
                has_incomplete_row = True

            if food_clean:
                if len(food_clean) > 100:
                    self.add_error(None, f"Ingredient name '{food_clean[:20]}...' exceeds maximum length of 100 characters.")
                    has_length_error = True
                if len(qty_clean) > 50:
                    self.add_error(None, f"Quantity '{qty_clean[:20]}...' exceeds maximum length of 50 characters.")
                    has_length_error = True
                if len(unit_clean) > 50:
                    self.add_error(None, f"Unit '{unit_clean[:20]}...' exceeds maximum length of 50 characters.")
                    has_length_error = True

                valid_ingredients.append({
                    "quantity": qty_clean,
                    "unit": unit_clean,
                    "food": food_clean,
                })

        if has_incomplete_row:
            self.add_error(None, "An ingredient row has a quantity or unit specified, but the ingredient name is missing.")

        # Fallback to ingredients_text if no structured rows were provided
        ingredients_text = cleaned_data.get('ingredients_text', '').strip()
        if not valid_ingredients and ingredients_text:
            for line in ingredients_text.splitlines():
                line = line.strip()
                if line:
                    valid_ingredients.append({"raw_text": line})

        if not valid_ingredients and not has_incomplete_row and not has_length_error:
            self.add_error(None, "At least one ingredient is required.")

        cleaned_data['valid_ingredients'] = valid_ingredients

        # Check instruction steps
        steps = self._get_list('instruction_step')
        valid_steps = []
        for s in steps:
            s_clean = str(s).strip() if s is not None else ""
            if s_clean:
                from recipes.utils import clean_instruction_line
                for sub_line in s_clean.splitlines():
                    sub_clean = sub_line.strip()
                    if sub_clean and not INSTRUCTION_MARKER_REGEX.match(sub_clean):
                        cleaned_step = clean_instruction_line(sub_clean).strip()
                        if cleaned_step:
                            valid_steps.append(cleaned_step)
                        elif sub_clean:
                            valid_steps.append(sub_clean)

        # Fallback to instructions_text if no steps were provided
        instructions_text = cleaned_data.get('instructions_text', '').strip()
        if not valid_steps and instructions_text:
            from recipes.utils import clean_instruction_line
            for s in instructions_text.splitlines():
                s_clean = s.strip()
                if s_clean and not INSTRUCTION_MARKER_REGEX.match(s_clean):
                    cleaned_step = clean_instruction_line(s_clean).strip()
                    if cleaned_step:
                        valid_steps.append(cleaned_step)
                    elif s_clean:
                        valid_steps.append(s_clean)

        if not valid_steps:
            self.add_error(None, "At least one instruction step is required.")

        cleaned_data['valid_steps'] = valid_steps

        return cleaned_data