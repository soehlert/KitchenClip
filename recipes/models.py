import hashlib
import random
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import IntegrityError, models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.text import slugify

from .ingredient_processor import format_time_h_m


class Ingredient(models.Model):
    """Define an ingredient."""
    name = models.CharField(max_length=100, unique=True)

    def __str__(self) -> str:
        return self.name


class Household(models.Model):
    """Tenant grouping entity for recipes and meal plans."""
    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self) -> str:
        return self.name


class UserProfile(models.Model):
    """Maps Django User to a Household with role permissions."""
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('member', 'Member'),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile'
    )
    household = models.ForeignKey(
        Household,
        on_delete=models.CASCADE,
        related_name='members'
    )
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='member'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.user.username} ({self.household.name})"


class InviteToken(models.Model):
    """Cryptographically secure, single-use CLI invite token stored as SHA-256 hash.
    
    Used strictly for CLI-gated provisioning and device enrollment (R1).
    The raw 32-byte URL-safe token is never persisted to the database.
    """
    token_hash = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        editable=False,
        help_text="SHA-256 hex digest of the raw invite token.",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='invite_tokens',
        help_text="User provisioned or authorized by this invite.",
    )
    household = models.ForeignKey(
        Household,
        on_delete=models.CASCADE,
        related_name='invite_tokens',
        help_text="Household the user is bound to.",
    )
    expires_at = models.DateTimeField(
        help_text="Timestamp after which this token cannot be redeemed.",
    )
    is_used = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether this single-use token has already been redeemed.",
    )
    used_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        help_text="Timestamp when this token was redeemed.",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when this token was generated.",
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Invite Token'
        verbose_name_plural = 'Invite Tokens'
        indexes = [
            models.Index(fields=['token_hash', 'is_used'], name='recipe_inv_hash_used_idx'),
        ]

    def __str__(self) -> str:
        status = "used" if self.is_used else ("expired" if self.is_expired else "active")
        return f"InviteToken for {self.user.username} ({status})"

    @staticmethod
    def hash_token(raw_token: str) -> str:
        """Compute SHA-256 hexadecimal digest of raw token string."""
        return hashlib.sha256(raw_token.strip().encode('utf-8')).hexdigest()

    @property
    def is_expired(self) -> bool:
        """Check whether the token has exceeded its expiration timestamp."""
        return timezone.now() >= self.expires_at

    @property
    def is_valid(self) -> bool:
        """Check whether token is active, unredeemed, and not expired."""
        return not self.is_used and not self.is_expired

    def mark_as_used(self, commit: bool = True) -> None:
        """Mark token as redeemed with current timestamp."""
        self.is_used = True
        self.used_at = timezone.now()
        if commit:
            self.save(update_fields=['is_used', 'used_at'])

    @classmethod
    def create_token(
        cls,
        user,
        household,
        expires_hours: int = 48,
    ) -> tuple['InviteToken', str]:
        """Factory creating a high-entropy invite token.
        
        Returns:
            tuple: (InviteToken instance, raw_token_string)
        """
        raw_token = secrets.token_urlsafe(32)
        token_hash = cls.hash_token(raw_token)
        expires_at = timezone.now() + timedelta(hours=expires_hours)
        invite = cls.objects.create(
            token_hash=token_hash,
            user=user,
            household=household,
            expires_at=expires_at,
        )
        return invite, raw_token


class PasskeyCredential(models.Model):
    """WebAuthn public key credential registered to a user account.
    
    Complies with W3C WebAuthn Level 3 specifications:
    - Stores base64url-encoded credentialId (unique, indexed).
    - Stores COSE public key in TextField.
    - Maintains monotonic sign_count for cloned authenticator detection.
    - Records AAGUID for authenticator model identification.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='passkeys',
        help_text="User account this passkey authenticates.",
    )
    credential_id = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Base64url-encoded WebAuthn credential ID.",
    )
    public_key = models.TextField(
        help_text="COSE public key (or PEM/base64 representation) from authenticator attestation.",
    )
    sign_count = models.PositiveIntegerField(
        default=0,
        help_text="Monotonic signature counter (uint32) for clone detection.",
    )
    name = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text="User-friendly device label (e.g., 'MacBook Pro TouchID').",
    )
    aaguid = models.CharField(
        max_length=36,
        blank=True,
        default='',
        help_text="Authenticator Attestation GUID (16-byte UUID in string form).",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when this passkey was registered.",
    )
    last_used_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of the most recent successful passkey authentication.",
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Passkey Credential'
        verbose_name_plural = 'Passkey Credentials'
        indexes = [
            models.Index(fields=['user', 'created_at'], name='recipe_passkey_user_idx'),
        ]

    def __str__(self) -> str:
        return f"Passkey({self.display_name}) for {self.user.username}"

    @property
    def display_name(self) -> str:
        """Return friendly label or fallback date label."""
        if self.name:
            return self.name
        created_date = self.created_at.strftime("%b %d, %Y") if self.created_at else "recent"
        return f"Passkey ({created_date})"

    @property
    def credential_id_preview(self) -> str:
        """Truncated credential ID for admin display."""
        if len(self.credential_id) > 20:
            return f"{self.credential_id[:8]}...{self.credential_id[-8:]}"
        return self.credential_id

    def update_sign_count(self, new_count: int, commit: bool = True) -> None:
        """Verify signature counter and update last_used_at timestamp.
        
        W3C WebAuthn Level 3 Section 6.1.2 compliance:
        - If stored_sign_count > 0 and new_count <= stored_sign_count, raise ValueError.
        - If new_count == 0 and stored_sign_count == 0 (synced passkey), accept.
        """
        if self.sign_count > 0 and new_count <= self.sign_count:
            raise ValueError(
                f"Authenticator sign count rollback detected: {new_count} <= {self.sign_count}. "
                "Possible cloned authenticator."
            )
        self.sign_count = new_count
        self.last_used_at = timezone.now()
        if commit:
            self.save(update_fields=['sign_count', 'last_used_at'])


class Recipe(models.Model):
    """Store recipe data."""
    household = models.ForeignKey(
        Household,
        on_delete=models.CASCADE,
        related_name='recipes'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_recipes'
    )
    is_shared = models.BooleanField(
        default=False,
        help_text="Share this recipe across households"
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    original_url = models.URLField(blank=True, null=True, help_text="Original recipe URL")
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
    is_future = models.BooleanField(default=False, help_text="Save to try in the future")
    is_on_menu = models.BooleanField(default=False, help_text="Add to weekly menu")

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['household', 'original_url'],
                condition=models.Q(original_url__isnull=False) & ~models.Q(original_url=''),
                name='unique_recipe_original_url_per_household'
            )
        ]

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return reverse('recipes:detail_recipe', kwargs={'pk': self.pk})

    @property
    def prep_time_display(self) -> str | None:
        """Return formatted prep time (HH:MM if > 60m)."""
        return format_time_h_m(self.prep_time) if self.prep_time else None

    @property
    def cook_time_display(self) -> str | None:
        """Return formatted cook time (HH:MM if > 60m)."""
        return format_time_h_m(self.cook_time) if self.cook_time else None

    @property
    def total_time_display(self) -> str | None:
        """Return formatted total time (HH:MM if > 60m) or calculate from components."""
        
        minutes = self.total_time
        if not minutes and self.prep_time and self.cook_time:
            minutes = self.prep_time + self.cook_time
        elif not minutes:
            minutes = self.prep_time or self.cook_time
            
        return format_time_h_m(minutes) if minutes else None


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
    household = models.ForeignKey(
        Household,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='tags'
    )
    name = models.CharField(max_length=50)
    slug = models.SlugField(max_length=100, blank=True)
    color = models.CharField(
        max_length=7,
        help_text="HEX color code for this tag (e.g., #FF5733)",
        blank=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['household', 'name'],
                name='unique_household_tag_name'
            ),
            models.UniqueConstraint(
                fields=['household', 'slug'],
                name='unique_household_tag_slug'
            ),
        ]

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

    @classmethod
    def get_or_create_for_household(cls, household, name, slug=None, color=None):
        """Retrieve or create a tag scoped to a household, resolving name and slug collisions."""
        if not name:
            return None

        clean_name = str(name).strip()
        if not clean_name:
            return None

        target_slug = slug or slugify(clean_name) or clean_name.lower()

        # 1. Search for existing tag in household by exact name, case-insensitive name, or slug
        existing = cls.objects.filter(household=household).filter(
            models.Q(name=clean_name) | models.Q(name__iexact=clean_name) | models.Q(slug=target_slug)
        ).first()

        if existing:
            return existing

        # 2. Not found: create new tag
        tag_color = color or cls.get_unique_tag_color()
        try:
            with transaction.atomic():
                return cls.objects.create(
                    household=household,
                    name=clean_name,
                    slug=target_slug,
                    color=tag_color,
                )
        except IntegrityError:
            existing = cls.objects.filter(household=household).filter(
                models.Q(name=clean_name) | models.Q(name__iexact=clean_name) | models.Q(slug=target_slug)
            ).first()
            if existing:
                return existing
            raise

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
            while RecipeTag.objects.filter(household=self.household, slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1

            self.slug = slug
        if not self.color:
            self.color = self.get_unique_tag_color()
        super().save(*args, **kwargs)

class MealPlan(models.Model):
    """Store meal plan data for specific dates and meal types."""
    MEAL_TYPE_CHOICES = [
        ('LUNCH', 'Lunch'),
        ('DINNER', 'Dinner'),
    ]

    household = models.ForeignKey(
        Household,
        on_delete=models.CASCADE,
        related_name='meal_plans'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_meal_plans'
    )
    date = models.DateField()
    meal_type = models.CharField(max_length=10, choices=MEAL_TYPE_CHOICES)
    recipe = models.ForeignKey(Recipe, on_delete=models.SET_NULL, null=True, blank=True, related_name='meal_plans')
    custom_meal = models.CharField(max_length=200, blank=True, help_text="Manual entry if no recipe is selected")
    ready_at = models.TimeField(null=True, blank=True)
    notification_sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['date', 'meal_type']
        unique_together = ['household', 'date', 'meal_type']

    def __str__(self) -> str:
        meal_name = self.recipe.title if self.recipe else self.custom_meal
        return f"{self.date} {self.meal_type}: {meal_name}"
