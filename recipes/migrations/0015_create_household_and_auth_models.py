from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("recipes", "0014_alter_recipe_is_future_alter_recipe_is_on_menu"),
    ]

    operations = [
        # 1. Create Household
        migrations.CreateModel(
            name="Household",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        # 2. Create UserProfile
        migrations.CreateModel(
            name="UserProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("admin", "Admin"), ("member", "Member")], default="member", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("household", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="members", to="recipes.household")),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="profile", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        # 3. Create InviteToken
        migrations.CreateModel(
            name="InviteToken",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token_hash", models.CharField(db_index=True, editable=False, help_text="SHA-256 hex digest of the raw invite token.", max_length=64, unique=True)),
                ("expires_at", models.DateTimeField(help_text="Timestamp after which this token cannot be redeemed.")),
                ("is_used", models.BooleanField(db_index=True, default=False, help_text="Whether this single-use token has already been redeemed.")),
                ("used_at", models.DateTimeField(blank=True, editable=False, help_text="Timestamp when this token was redeemed.", null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, help_text="Timestamp when this token was generated.")),
                ("household", models.ForeignKey(help_text="Household the user is bound to.", on_delete=django.db.models.deletion.CASCADE, related_name="invite_tokens", to="recipes.household")),
                ("user", models.ForeignKey(help_text="User provisioned or authorized by this invite.", on_delete=django.db.models.deletion.CASCADE, related_name="invite_tokens", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "Invite Token",
                "verbose_name_plural": "Invite Tokens",
                "ordering": ["-created_at"],
                "indexes": [models.Index(fields=["token_hash", "is_used"], name="recipe_inv_hash_used_idx")],
            },
        ),
        # 4. Create PasskeyCredential
        migrations.CreateModel(
            name="PasskeyCredential",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("credential_id", models.CharField(db_index=True, help_text="Base64url-encoded WebAuthn credential ID.", max_length=255, unique=True)),
                ("public_key", models.TextField(help_text="COSE public key (or PEM/base64 representation) from authenticator attestation.")),
                ("sign_count", models.PositiveIntegerField(default=0, help_text="Monotonic signature counter (uint32) for clone detection.")),
                ("name", models.CharField(blank=True, default="", help_text="User-friendly device label (e.g., 'MacBook Pro TouchID').", max_length=100)),
                ("aaguid", models.CharField(blank=True, default="", help_text="Authenticator Attestation GUID (16-byte UUID in string form).", max_length=36)),
                ("created_at", models.DateTimeField(auto_now_add=True, help_text="Timestamp when this passkey was registered.")),
                ("last_used_at", models.DateTimeField(blank=True, help_text="Timestamp of the most recent successful passkey authentication.", null=True)),
                ("user", models.ForeignKey(help_text="User account this passkey authenticates.", on_delete=django.db.models.deletion.CASCADE, related_name="passkeys", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "Passkey Credential",
                "verbose_name_plural": "Passkey Credentials",
                "ordering": ["-created_at"],
                "indexes": [models.Index(fields=["user", "created_at"], name="recipe_passkey_user_idx")],
            },
        ),
        # 5. Alter Recipe (nullable household, created_by, is_shared, unconstrain original_url)
        migrations.AddField(
            model_name="recipe",
            name="household",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="recipes", to="recipes.household"),
        ),
        migrations.AddField(
            model_name="recipe",
            name="created_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_recipes", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="recipe",
            name="is_shared",
            field=models.BooleanField(default=False, help_text="Share this recipe across households"),
        ),
        migrations.AlterField(
            model_name="recipe",
            name="original_url",
            field=models.URLField(blank=True, help_text="Original recipe URL", null=True),
        ),
        # 6. Alter MealPlan (nullable household, created_by, drop unique_together)
        migrations.AddField(
            model_name="mealplan",
            name="household",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="meal_plans", to="recipes.household"),
        ),
        migrations.AddField(
            model_name="mealplan",
            name="created_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_meal_plans", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterUniqueTogether(
            name="mealplan",
            unique_together=set(),
        ),
        # 7. Alter RecipeTag (nullable household, unconstrain name and slug)
        migrations.AddField(
            model_name="recipetag",
            name="household",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="tags", to="recipes.household"),
        ),
        migrations.AlterField(
            model_name="recipetag",
            name="name",
            field=models.CharField(max_length=50),
        ),
        migrations.AlterField(
            model_name="recipetag",
            name="slug",
            field=models.SlugField(blank=True, max_length=100),
        ),
    ]
