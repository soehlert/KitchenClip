from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify
from django.utils.html import format_html

import random

from django.urls import reverse
from django.core.validators import MinValueValidator, MaxValueValidator
from django.conf import settings


class Ingredient(models.Model):
    """Define an ingredient."""
    name = models.CharField(max_length=100, unique=True)

    def __str__(self) -> str:
        return self.name


class Recipe(models.Model):
    """Store recipe data."""
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    original_url = models.URLField(blank=True, help_text="Original recipe URL", unique=True)
    prep_time = models.PositiveIntegerField(null=True, blank=True, help_text="Prep time in minutes")
    cook_time = models.PositiveIntegerField(null=True, blank=True, help_text="Cook time in minutes")
    total_time = models.PositiveIntegerField(null=True, blank=True, help_text="Total time in minutes")
    servings = models.PositiveIntegerField(null=True, blank=True)
    rating = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    instructions = models.TextField()
    user_notes = models.TextField(blank=True, help_text="Your personal notes about this recipe")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    image_url = models.URLField(blank=True, null=True, max_length=300)
    tags = models.ManyToManyField('RecipeTag', blank=True, related_name='recipes')
    ingredients = models.ManyToManyField(
        Ingredient,
        through='RecipeIngredient',
        blank=True,
        related_name='recipes'
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return reverse('recipes:detail_recipe', kwargs={'pk': self.pk})

    @property
    def total_time_display(self) -> str | None:
        """Return formatted total time or calculate from prep + cook time."""
        if self.total_time:
            return f"{self.total_time} min"
        elif self.prep_time and self.cook_time:
            return f"{self.prep_time + self.cook_time} min"
        elif self.prep_time:
            return f"{self.prep_time} min (prep)"
        elif self.cook_time:
            return f"{self.cook_time} min (cook)"
        return None


class RecipeIngredient(models.Model):
    """Store per recipe information about an ingredient in through model."""
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name='recipe_ingredients')
    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE, related_name='ingredient_recipes')
    raw_text = models.CharField(max_length=200)
    quantity = models.CharField(max_length=50, blank=True)
    unit = models.CharField(max_length=50, blank=True)
    preparation = models.CharField(max_length=100, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']
        unique_together = ['recipe', 'ingredient', 'order']

    def __str__(self) -> str:
        return f"{self.recipe.title}: {self.raw_text}"

class RecipeTag(models.Model):
    """Define tags for categorizing recipes. """
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)
    color = models.CharField(
        max_length=7,
        help_text="HEX color code for this tag (e.g., #FF5733)",
        blank=True,
    )

    def __str__(self) -> str:
        return self.name

    @staticmethod
    def get_unique_tag_color():
        used_colors = set(RecipeTag.objects.values_list('color', flat=True))
        available_colors = [c for c in settings.TAG_COLORS if c not in used_colors]
        if available_colors:
            return random.choice(available_colors)
        else:
            return random.choice(settings.TAG_COLORS)

    def color_preview(self):
        """Display a colored square in the admin"""
        return format_html(
            '<div style="width: 20px; height: 20px; background-color: {}; border: 1px solid #ccc; border-radius: 3px;"></div>',
            self.color
        )
    color_preview.short_description = 'Color'

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1

            # Check for existing slugs and append number if needed
            while RecipeTag.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1

            self.slug = slug
        if not self.color:
            self.color = self.get_unique_tag_color()
        super().save(*args, **kwargs)
