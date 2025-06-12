from django import forms
from recipes.models import Recipe

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
        print("Clean Rating")
        return int(value) if value else None

    def clean_tags(self):
        print("clean_tags")
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

    def clean_rating(self):
        value = self.cleaned_data['rating']
        return int(value) if value else None

    def clean_tags(self):
        tags = self.cleaned_data.get("tags", "")
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        return tag_list
