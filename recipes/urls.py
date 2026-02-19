from django.urls import path
from recipes import views

app_name = "recipes"

urlpatterns = [
    # Recipe URLs
    path("", views.RecipeListView.as_view(), name="list_recipe"),
    path("future_recipes/", views.FutureRecipeListView.as_view(), name="future_recipes"),
    path("add/", views.RecipeCreateView.as_view(), name="add_recipe"),
    path('add/manual/', views.RecipeManualCreateView.as_view(), name='manual_add'),
    path("<int:pk>/", views.RecipeDetailView.as_view(), name="detail_recipe"),
    path("<int:pk>/move_to_recipes/", views.move_to_recipes, name="move_to_recipes"),
    path("<int:pk>/edit/", views.RecipeUpdateView.as_view(), name="edit_recipe"),
    path("<int:pk>/delete/", views.RecipeDeleteView.as_view(), name="delete_recipe"),

    path("tags/autocomplete/", views.tag_autocomplete, name="tag_autocomplete"),

    # Meal Plan URLs
    path("meal-plan/", views.MealPlanView.as_view(), name="meal_plan"),
    path("api/meal-plan/update/", views.update_meal_plan, name="update_meal_plan"),
    path("api/recipes/search/", views.search_recipes_api, name="search_recipes_api"),
]
