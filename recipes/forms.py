from django import forms
from recipes.models import Recipe, Ingredient, RecipeIngredient
from recipes.utils import remove_instruction_headers, clean_instruction_line

import logging
logger = logging.getLogger(__name__)

RATING_CHOICES = [(i, str(i)) for i in range(1, 6)]

class RecipeImportForm(forms.ModelForm):
    original_url = forms.URLField(
        label="Recipe URL",
        required=True,
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
        fields = ["original_url", "user_notes", "rating"]
        widgets = {
            "user_notes": forms.Textarea(attrs={
                "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]",
                "rows": 3,
            }),
        }

    def clean_rating(self):
        value = self.cleaned_data['rating']
        return int(value) if value else None

    def clean_tags(self):
        tags = self.cleaned_data.get("tags", "")
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        return tag_list


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
            "image_url"
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
            existing_ingredients = self.instance.recipeingredient_set.order_by('order')
            ingredients_list = [ing.raw_text for ing in existing_ingredients]
            self.initial['ingredients_text'] = '\n'.join(ingredients_list)

    def save(self, commit=True):
        recipe = super().save(commit=commit)

        if commit and 'ingredients_text' in self.cleaned_data:
            recipe.recipe_ingredients.all().delete()

            ingredients_text = self.cleaned_data.get('ingredients_text', '')
            for idx, line in enumerate(ingredients_text.split('\n')):
                line = line.strip()
                if line:
                    try:
                        slicer = ingredient_slicer.IngredientSlicer(line)
                        parsed = slicer.to_json()
                        name = parsed.get("food") or line

                        ingredient, _ = Ingredient.objects.get_or_create(name=name)
                        RecipeIngredient.objects.create(
                            recipe=recipe,
                            ingredient=ingredient,
                            raw_text=line,
                            quantity=parsed.get("quantity") or "",
                            unit=parsed.get("unit") or "",
                            preparation=", ".join(parsed.get("prep", [])) if parsed.get("prep") else "",
                            order=idx
                        )
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Failed to parse ingredient: {line}, error: {e}")

                        # Create a basic ingredient entry if parsing fails
                        ingredient, _ = Ingredient.objects.get_or_create(name=line)
                        RecipeIngredient.objects.create(
                            recipe=recipe,
                            ingredient=ingredient,
                            raw_text=line,
                            quantity="",
                            unit="",
                            preparation="",
                            order=idx
                        )

        return recipe

    def clean_rating(self):
        value = self.cleaned_data['rating']
        return int(value) if value else None

    def clean_tags(self):
        tags = self.cleaned_data.get("tags", "")
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        return tag_list


class RecipeManualForm(forms.ModelForm):
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
        widget=forms.Textarea(attrs={
            "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]",
            "rows": 8,
            "placeholder": "Enter each ingredient on a new line:\n1 cup flour\n2 eggs\n1/2 cup sugar"
        }),
        label="Ingredients",
        help_text="Enter each ingredient on a separate line"
    )
    instructions_text = forms.CharField(
        widget=forms.Textarea(attrs={
            "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]",
            "rows": 10,
            "placeholder": "Enter cooking instructions"
        }),
        label="Instructions"
    )
    image_url = forms.URLField(
        required=False,
        label="Image URL",
        widget=forms.URLInput(attrs={
            "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]",
            "placeholder": "https://example.com/recipe-image.jpg"
        })
    )

    class Meta:
        model = Recipe
        fields = ["title", "original_url", "user_notes", "rating", "image_url"]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]"
            }),
            "original_url": forms.URLInput(attrs={
                "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]",
                "readonly": True
            }),
            "user_notes": forms.Textarea(attrs={
                "class": "w-full px-3 py-2 border border-[#5B8E7D] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#194769] text-[#194769]",
                "rows": 3,
            }),
            "instructions": forms.HiddenInput(),  # Hide the model field since we use instructions_text
            "image_url": forms.HiddenInput(),  # Hide the model field since we use image_url custom field
        }

    def clean_rating(self):
        value = self.cleaned_data['rating']
        return int(value) if value else None

    def clean_tags(self):
        tags = self.cleaned_data.get("tags", "")
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        return tag_list

    def save(self, commit=True):
        recipe = super().save(commit=False)
        raw_instructions = self.cleaned_data.get('instructions_text', '')
        recipe.instructions = remove_instruction_headers(raw_instructions)

        recipe.image_url = self.cleaned_data.get('image_url', '')

        if commit:
            recipe.save()
        return recipe