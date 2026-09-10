from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Household,
    Ingredient,
    InviteToken,
    MealPlan,
    PasskeyCredential,
    Recipe,
    RecipeIngredient,
    RecipeTag,
    UserProfile,
)


class RecipeIngredientInline(admin.TabularInline):
    model = RecipeIngredient
    extra = 1


@admin.register(Household)
class HouseholdAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at", "updated_at")
    search_fields = ("name",)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "household", "role", "created_at")
    list_filter = ("role", "household")
    search_fields = ("user__username", "household__name")


@admin.register(InviteToken)
class InviteTokenAdmin(admin.ModelAdmin):
    list_display = (
        'token_preview',
        'user',
        'household',
        'status_badge',
        'expires_at',
        'used_at',
        'created_at',
    )
    list_filter = ('is_used', 'household')
    search_fields = ('user__username', 'token_hash')
    readonly_fields = ('token_hash', 'created_at', 'used_at')
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        # Enforce R1: CLI is the sole mechanism to generate tokens
        return False

    @admin.display(description='Token Hash')
    def token_preview(self, obj):
        return f"{obj.token_hash[:8]}...{obj.token_hash[-8:]}"

    @admin.display(description='Status')
    def status_badge(self, obj):
        if obj.is_used:
            return format_html('<span style="color: gray;">Redeemed</span>')
        elif obj.is_expired:
            return format_html('<span style="color: red;">Expired</span>')
        return format_html('<span style="color: green; font-weight: bold;">Active</span>')


@admin.register(PasskeyCredential)
class PasskeyCredentialAdmin(admin.ModelAdmin):
    list_display = (
        'display_name',
        'user',
        'credential_preview',
        'sign_count',
        'created_at',
        'last_used_at',
    )
    list_filter = ('user',)
    search_fields = ('user__username', 'name', 'credential_id', 'aaguid')
    readonly_fields = (
        'credential_id',
        'public_key',
        'sign_count',
        'aaguid',
        'created_at',
        'last_used_at',
    )
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        # Credentials must be enrolled via browser WebAuthn attestation
        return False

    @admin.display(description='Credential ID')
    def credential_preview(self, obj):
        return obj.credential_id_preview


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ("title", "household", "created_by", "is_shared", "rating")
    list_filter = ("household", "is_shared", "tags", "rating")
    search_fields = ("title", "instructions", "user_notes")
    inlines = [RecipeIngredientInline]
    filter_horizontal = ("tags",)


@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(RecipeTag)
class RecipeTagAdmin(admin.ModelAdmin):
    list_display = ("name", "household", "slug", "color_preview", "color")
    list_filter = ("household",)
    search_fields = ("name", "slug")
    readonly_fields = ("color_preview",)


@admin.register(MealPlan)
class MealPlanAdmin(admin.ModelAdmin):
    list_display = ("date", "meal_type", "recipe", "custom_meal", "household", "created_by")
    list_filter = ("meal_type", "household")
    search_fields = ("recipe__title", "custom_meal")