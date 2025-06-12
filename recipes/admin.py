from django.contrib import admin
from .models import Recipe, Ingredient, RecipeIngredient, RecipeTag

class RecipeIngredientInline(admin.TabularInline):
    model = RecipeIngredient
    extra = 1

@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ("title", "rating")
    list_filter = ("tags", "rating")
    search_fields = ("title", "instructions", "user_notes")
    inlines = [RecipeIngredientInline]
    filter_horizontal = ("tags",)

@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)

@admin.register(RecipeTag)
class RecipeTagAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "color_preview", "color")
    search_fields = ("name", "slug")
    readonly_fields = ("color_preview",)