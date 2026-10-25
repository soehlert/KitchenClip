import base64
import io

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from recipes.image_utils import process_uploaded_recipe_image
from recipes.models import Household, Recipe, UserProfile
from recipes.services import RecipeCloningService


def _make_image_bytes(
    width: int = 800,
    height: int = 600,
    mode: str = "RGB",
    color: tuple = (200, 100, 50),
    fmt: str = "JPEG",
    exif_orientation: int | None = None,
) -> bytes:
    """Create an in-memory image byte buffer for testing."""
    img = Image.new(mode, (width, height), color=color)
    buf = io.BytesIO()
    if exif_orientation is not None:
        exif = img.getexif()
        exif[0x0112] = exif_orientation  # 0x0112 is EXIF Orientation tag
        img.save(buf, format=fmt, exif=exif.tobytes())
    else:
        img.save(buf, format=fmt)
    return buf.getvalue()


def _decode_data_uri_image(data_uri: str) -> Image.Image:
    """Decode a data:image/webp;base64,... URI back into a PIL Image."""
    assert data_uri.startswith("data:image/webp;base64,")
    b64_part = data_uri.split(",", 1)[1]
    raw = base64.b64decode(b64_part)
    return Image.open(io.BytesIO(raw))


def test_process_uploaded_image_resizes_and_compresses():
    """Verify oversized images are resized to max_dimension and encoded as WebP."""
    raw_jpeg = _make_image_bytes(width=2400, height=1800, fmt="JPEG")
    uploaded = SimpleUploadedFile("photo.jpg", raw_jpeg, content_type="image/jpeg")

    data_uri = process_uploaded_recipe_image(uploaded, max_dimension=1200)
    decoded = _decode_data_uri_image(data_uri)

    assert decoded.format == "WEBP"
    assert decoded.size == (1200, 900)


def test_process_uploaded_image_respects_exif_orientation():
    """Verify phone portrait photos with EXIF orientation=6 (90 CW) are auto-rotated."""
    raw_jpeg = _make_image_bytes(width=1000, height=600, fmt="JPEG", exif_orientation=6)
    uploaded = SimpleUploadedFile("portrait.jpg", raw_jpeg, content_type="image/jpeg")

    data_uri = process_uploaded_recipe_image(uploaded, max_dimension=1200)
    decoded = _decode_data_uri_image(data_uri)

    # Width and height should swap after applying EXIF orientation 6
    assert decoded.size == (600, 1000)


def test_process_uploaded_image_flattens_rgba_png():
    """Verify transparent PNGs are flattened onto a white RGB background."""
    raw_png = _make_image_bytes(width=400, height=300, mode="RGBA", color=(255, 0, 0, 128), fmt="PNG")
    uploaded = SimpleUploadedFile("transparent.png", raw_png, content_type="image/png")

    data_uri = process_uploaded_recipe_image(uploaded)
    decoded = _decode_data_uri_image(data_uri)

    assert decoded.format == "WEBP"
    assert decoded.mode == "RGB"
    assert decoded.size == (400, 300)


def test_process_uploaded_image_rejects_invalid_bytes():
    """Verify non-image uploads raise ValidationError."""
    bad_file = SimpleUploadedFile("not_an_image.jpg", b"not image bytes", content_type="image/jpeg")
    with pytest.raises(ValidationError, match="Upload a valid image file"):
        process_uploaded_recipe_image(bad_file)


@pytest.mark.django_db
def test_scratch_create_with_uploaded_photo(client):
    """Verify creating a recipe from scratch with an uploaded photo stores and renders it."""
    url = reverse("recipes:scratch_add")
    photo_bytes = _make_image_bytes(width=640, height=480, fmt="JPEG")
    photo_file = SimpleUploadedFile("my_dish.jpg", photo_bytes, content_type="image/jpeg")

    data = {
        "title": "Homemade Focaccia",
        "description": "Crispy olive oil bread.",
        "image_file": photo_file,
        "ingredient_quantity": ["4"],
        "ingredient_unit": ["cups"],
        "ingredient_food": ["bread flour"],
        "instruction_step": ["Mix dough and bake at 450F."],
    }
    response = client.post(url, data)
    assert response.status_code == 302

    recipe = Recipe.objects.get(title="Homemade Focaccia")
    assert recipe.uploaded_image.startswith("data:image/webp;base64,")
    assert recipe.display_image_url == recipe.uploaded_image

    detail_response = client.get(recipe.get_absolute_url())
    assert detail_response.status_code == 200
    assert recipe.uploaded_image in detail_response.content.decode()


@pytest.mark.django_db
def test_scratch_create_rejects_invalid_photo(client):
    """Verify invalid image file on scratch create returns form validation error."""
    url = reverse("recipes:scratch_add")
    bad_file = SimpleUploadedFile("fake.jpg", b"plain text content", content_type="image/jpeg")

    data = {
        "title": "Bad Photo Recipe",
        "image_file": bad_file,
        "ingredient_quantity": ["1"],
        "ingredient_unit": ["cup"],
        "ingredient_food": ["water"],
        "instruction_step": ["Boil water."],
    }
    response = client.post(url, data)
    assert response.status_code == 200
    assert "image_file" in response.context["form"].errors


@pytest.mark.django_db
def test_recipe_edit_upload_and_clear_photo(client):
    """Verify editing a recipe can upload a photo and later clear it."""
    recipe = Recipe.objects.create(
        title="Editable Dish",
        instructions="Step 1.",
        image_url="https://example.com/fallback.jpg",
    )
    edit_url = reverse("recipes:edit_recipe", args=[recipe.pk])

    photo_bytes = _make_image_bytes(width=500, height=500, fmt="PNG")
    photo_file = SimpleUploadedFile("updated.png", photo_bytes, content_type="image/png")

    response = client.post(
        edit_url,
        {
            "title": "Editable Dish",
            "instructions": "Step 1.",
            "ingredients_text": "1 cup rice",
            "image_url": "https://example.com/fallback.jpg",
            "image_file": photo_file,
        },
    )
    assert response.status_code == 302

    recipe.refresh_from_db()
    assert recipe.uploaded_image.startswith("data:image/webp;base64,")
    # Uploaded photo takes priority over external image_url
    assert recipe.display_image_url == recipe.uploaded_image

    # Now clear the uploaded image and verify fallback to image_url
    clear_response = client.post(
        edit_url,
        {
            "title": "Editable Dish",
            "instructions": "Step 1.",
            "ingredients_text": "1 cup rice",
            "image_url": "https://example.com/fallback.jpg",
            "clear_uploaded_image": "on",
        },
    )
    assert clear_response.status_code == 302

    recipe.refresh_from_db()
    assert recipe.uploaded_image == ""
    assert recipe.display_image_url == "https://example.com/fallback.jpg"


@pytest.mark.django_db
def test_clone_recipe_preserves_uploaded_image(test_household):
    """Verify cloning a shared recipe copies its uploaded_image to the target household."""
    other_household = Household.objects.create(name="Target Household")
    target_user = User.objects.create_user(username="target_chef")
    UserProfile.objects.create(user=target_user, household=other_household)

    source_recipe = Recipe.objects.create(
        household=test_household,
        title="Shared Sourdough",
        instructions="Bake it.",
        uploaded_image="data:image/webp;base64,UklGRiIAAABXRUJQVlA4IBYAAAAwAQCdASoBAAEAAUAmJYgCdAEO/gHOAAA=",
        is_shared=True,
    )

    cloned = RecipeCloningService.clone_recipe(
        source_recipe=source_recipe,
        target_household=other_household,
        target_user=target_user,
    )
    assert cloned.uploaded_image == source_recipe.uploaded_image
    assert cloned.display_image_url == source_recipe.uploaded_image


@pytest.mark.django_db
def test_dev_auto_login_when_debug_enabled(settings):
    """Verify unauthenticated requests auto-login when DEBUG=True."""
    from django.test import Client

    settings.DEBUG = True
    anon_client = Client()
    response = anon_client.get(reverse("recipes:list_recipe"))
    assert response.status_code == 200
    assert response.wsgi_request.user.is_authenticated
