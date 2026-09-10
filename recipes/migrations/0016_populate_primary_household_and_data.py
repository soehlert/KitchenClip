from django.db import migrations


def populate_primary_household_and_data(apps, schema_editor):
    Household = apps.get_model("recipes", "Household")
    UserProfile = apps.get_model("recipes", "UserProfile")
    Recipe = apps.get_model("recipes", "Recipe")
    MealPlan = apps.get_model("recipes", "MealPlan")
    RecipeTag = apps.get_model("recipes", "RecipeTag")
    User = apps.get_model("auth", "User")

    # 1. Resolve or create primary admin user
    primary_user = (
        User.objects.filter(is_superuser=True).first()
        or User.objects.filter(is_staff=True).first()
        or User.objects.filter(username__icontains="sam.oehlert@gmail.com").first()
        or User.objects.filter(email__icontains="sam.oehlert@gmail.com").first()
        or User.objects.exclude(username="").first()
        or User.objects.first()
    )

    if not primary_user:
        primary_user = User.objects.create(
            username="admin",
            email="admin@example.com",
            is_staff=True,
            is_superuser=True
        )

    # 2. Get or create Primary Household
    primary_household, _ = Household.objects.get_or_create(
        name="Primary Household"
    )

    # 3. Create UserProfile for all existing users
    for user in User.objects.all():
        if not UserProfile.objects.filter(user=user).exists():
            is_primary = (user.pk == primary_user.pk)
            UserProfile.objects.create(
                user=user,
                household=primary_household,
                role="admin" if (is_primary or user.is_staff or user.is_superuser) else "member"
            )

    # 4. Attribute all unassigned Recipe rows
    Recipe.objects.filter(household__isnull=True).update(
        household=primary_household,
        created_by=primary_user
    )

    # 5. Attribute all unassigned MealPlan rows
    MealPlan.objects.filter(household__isnull=True).update(
        household=primary_household,
        created_by=primary_user
    )

    # 6. Attribute all unassigned RecipeTag rows
    RecipeTag.objects.filter(household__isnull=True).update(
        household=primary_household
    )


def reverse_primary_household_and_data(apps, schema_editor):
    Household = apps.get_model("recipes", "Household")
    UserProfile = apps.get_model("recipes", "UserProfile")
    Recipe = apps.get_model("recipes", "Recipe")
    MealPlan = apps.get_model("recipes", "MealPlan")
    RecipeTag = apps.get_model("recipes", "RecipeTag")

    primary_household = Household.objects.filter(name="Primary Household").first()
    if primary_household:
        Recipe.objects.filter(household=primary_household).update(household=None, created_by=None)
        MealPlan.objects.filter(household=primary_household).update(household=None, created_by=None)
        RecipeTag.objects.filter(household=primary_household).update(household=None)
        UserProfile.objects.filter(household=primary_household).delete()
        primary_household.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("recipes", "0015_create_household_and_auth_models"),
    ]

    operations = [
        migrations.RunPython(
            populate_primary_household_and_data,
            reverse_code=reverse_primary_household_and_data
        ),
    ]
