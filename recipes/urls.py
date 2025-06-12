from django.urls import path
from recipes import views

app_name = "recipes"

urlpatterns = [
    # Recipe URLs
    path("", views.RecipeListView.as_view(), name="list_recipe"),
    path("add/", views.RecipeCreateView.as_view(), name="add_recipe"),
    path("<int:pk>/", views.RecipeDetailView.as_view(), name="detail_recipe"),
    path("<int:pk>/edit/", views.RecipeUpdateView.as_view(), name="edit_recipe"),
    path("<int:pk>/delete/", views.RecipeDeleteView.as_view(), name="delete_recipe"),

    path("tags/autocomplete/", views.tag_autocomplete, name="tag_autocomplete"),

]
