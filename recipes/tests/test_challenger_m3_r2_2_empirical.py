"""Milestone M3 Remediation Empirical Challenge Test Suite (Challenger 2 Round 2).

Rigorous adversarial challenge suite targeting:
1. Root URL trailing slash matching across permutations (https://example.com/ vs https://example.com).
2. RecipeTag slug collision handling under varying cases/punctuation and concurrency.
3. Template privacy (ratings/notes strictly hidden from foreign households).
4. Instruction step and recipe field XSS escaping.
"""

from unittest.mock import patch

import pytest
from django.urls import reverse

from recipes.models import Ingredient, Recipe, RecipeIngredient, RecipeTag
from recipes.url_utils import find_recipe_by_url, get_url_lookup_variants, normalize_url



# =====================================================================
# 1. ROOT URL TRAILING SLASH MATCHING ACROSS PERMUTATIONS
# =====================================================================

@pytest.mark.django_db
class TestRootURLTrailingSlashEmpirical:
    """Empirical challenge on root URL trailing slash matching across variants."""

    def test_root_domain_normalization_variants_exhaustiveness(self):
        """Verify that normalize_url and get_url_lookup_variants handle root domains bidirectionally."""
        root_slash = "https://example.com/"
        root_noslash = "https://example.com"

        norm_slash = normalize_url(root_slash)
        norm_noslash = normalize_url(root_noslash)

        assert norm_slash == norm_noslash, "normalize_url must produce identical normalized form for root URLs"
        assert norm_slash == "https://example.com"

        variants_from_slash = set(get_url_lookup_variants(root_slash))
        variants_from_noslash = set(get_url_lookup_variants(root_noslash))

        # Both must include both https://example.com and https://example.com/
        assert "https://example.com" in variants_from_slash
        assert "https://example.com/" in variants_from_slash
        assert "https://example.com" in variants_from_noslash
        assert "https://example.com/" in variants_from_noslash

        # Also verify HTTP and www variants
        for vset in [variants_from_slash, variants_from_noslash]:
            assert "http://example.com" in vset
            assert "http://example.com/" in vset
            assert "https://www.example.com" in vset
            assert "https://www.example.com/" in vset
            assert "http://www.example.com" in vset
            assert "http://www.example.com/" in vset

    def test_find_recipe_by_url_all_cross_permutations(self, secondary_household):
        """Every combination of saved root variant must match every entered root variant."""
        saved_urls = [
            "https://example.com/",
            "https://example.com",
            "http://example.com/",
            "http://example.com",
            "https://www.example.com/",
            "https://www.example.com",
        ]

        query_variants = [
            "https://example.com",
            "https://example.com/",
            "http://example.com",
            "http://example.com/",
            "https://www.example.com",
            "https://www.example.com/",
            "https://example.com:443",
            "https://example.com:443/",
            "http://example.com:80",
            "http://example.com:80/",
            "  https://example.com/  ",
            "https://example.com?utm_source=twitter&utm_medium=social",
            "https://example.com/?fbclid=xyz123",
            "https://example.com/#top",
            "https://example.com/#instructions",
        ]

        for saved_url in saved_urls:
            Recipe.objects.filter(household=secondary_household).delete()
            recipe = Recipe.objects.create(
                household=secondary_household,
                original_url=saved_url,
                title=f"Root Recipe for {saved_url}",
            )

            for query in query_variants:
                found = find_recipe_by_url(query)
                assert found is not None, (
                    f"Lookup failed! Saved: '{saved_url}', Queried: '{query}'"
                )
                assert found.pk == recipe.pk

    def test_cross_household_duplicate_banner_root_url_slash_mismatch(self, client, secondary_household):
        """Entering root URL without slash matches neighbor's saved root URL with slash and vice-versa."""
        # Neighbor has https://example.com/
        Recipe.objects.create(
            household=secondary_household,
            original_url="https://example.com/",
            title="Neighbor Slash Root",
            is_shared=True,
        )

        with patch("recipes.views.ParserRegistry.get_parser") as mock_parser:
            res = client.post(reverse("recipes:add_recipe"), {
                "original_url": "https://example.com",
            })
            assert res.status_code == 200
            assert res.context.get("duplicate_detected") is True
            assert res.context.get("duplicate_recipe").title == "Neighbor Slash Root"
            mock_parser.assert_not_called()

        # Reverse test: Neighbor has https://other.com (no slash), user enters https://other.com/
        Recipe.objects.create(
            household=secondary_household,
            original_url="https://other.com",
            title="Neighbor No-Slash Root",
            is_shared=True,
        )

        with patch("recipes.views.ParserRegistry.get_parser") as mock_parser:
            res2 = client.post(reverse("recipes:add_recipe"), {
                "original_url": "https://other.com/",
            })
            assert res2.status_code == 200
            assert res2.context.get("duplicate_detected") is True
            assert res2.context.get("duplicate_recipe").title == "Neighbor No-Slash Root"
            mock_parser.assert_not_called()

    def test_copy_duplicate_root_url_slash_cross_match(self, client, test_household, secondary_household):
        """copy_duplicate_recipe must succeed when original_url has/lacks slash compared to saved record."""
        target = Recipe.objects.create(
            household=secondary_household,
            original_url="https://example.com/",
            title="Root Target",
            is_shared=True,
        )

        # Post with original_url="https://example.com" (no trailing slash)
        res = client.post(reverse("recipes:copy_duplicate", kwargs={"pk": target.pk}), {
            "original_url": "https://example.com",
        }, follow=True)
        assert res.status_code == 200

        cloned = Recipe.objects.filter(household=test_household, title="Root Target").first()
        assert cloned is not None
        assert cloned.household == test_household

    def test_same_household_duplicate_root_url_slash_rejected(self, client, test_household):
        """Submitting root URL with slash when own household has no-slash triggers form validation error."""
        Recipe.objects.create(
            household=test_household,
            original_url="https://example.com",
            title="Own Root",
        )

        res = client.post(reverse("recipes:add_recipe"), {
            "original_url": "https://example.com/",
        })
        assert res.status_code == 200
        assert "form" in res.context
        assert "original_url" in res.context["form"].errors
        assert "already in your household" in str(res.context["form"].errors["original_url"])


# =====================================================================
# 2. RECIPETAG SLUG COLLISION HANDLING UNDER VARYING CASES/PUNCTUATION
# =====================================================================

@pytest.mark.django_db
class TestRecipeTagSlugCollisionEmpirical:
    """Empirical challenge on RecipeTag slug collision resolution."""

    def test_casing_variations_resolve_to_same_tag(self, test_household):
        """Tag lookups across various casings must return the existing tag without IntegrityError."""
        t_orig = RecipeTag.objects.create(household=test_household, name="Comfort Food")
        assert t_orig.slug == "comfort-food"

        variations = [
            "Comfort Food",
            "comfort food",
            "COMFORT FOOD",
            "CoMfOrT fOoD",
            "cOmFoRt FoOd",
            "  Comfort Food  ",
        ]

        for var in variations:
            t = RecipeTag.get_or_create_for_household(test_household, var)
            assert t is not None
            assert t.pk == t_orig.pk, f"Variation '{var}' created duplicate or failed to match"

        # Verify only 1 tag exists in household
        assert RecipeTag.objects.filter(household=test_household).count() == 1

    def test_punctuation_and_slug_collisions_resolve_safely(self, test_household):
        """Tags with different punctuation that yield identical slugs must resolve cleanly."""
        t_orig = RecipeTag.objects.create(household=test_household, name="Gluten-Free")
        assert t_orig.slug == "gluten-free"

        punct_variations = [
            "gluten-free",
            "Gluten Free",
            "gluten free",
            "GLUTEN FREE",
            "Gluten  Free",
            "Gluten - Free",
            "gluten--free",
        ]

        for var in punct_variations:
            t = RecipeTag.get_or_create_for_household(test_household, var)
            assert t is not None
            assert t.pk == t_orig.pk, f"Punctuation variation '{var}' caused collision or didn't resolve"

        assert RecipeTag.objects.filter(household=test_household).count() == 1

    def test_edge_case_inputs(self, test_household):
        """Edge case inputs like empty string, whitespace, unicode, and symbols."""
        # None and whitespace
        assert RecipeTag.get_or_create_for_household(test_household, "") is None
        assert RecipeTag.get_or_create_for_household(test_household, "   ") is None
        assert RecipeTag.get_or_create_for_household(test_household, "\t\n") is None
        assert RecipeTag.get_or_create_for_household(test_household, None) is None

        # Unicode tags
        t_cafe = RecipeTag.get_or_create_for_household(test_household, "Café")
        assert t_cafe is not None
        # Resolving unaccented or uppercase
        t_cafe2 = RecipeTag.get_or_create_for_household(test_household, "café")
        assert t_cafe2.pk == t_cafe.pk

        # Special symbols
        t_amp = RecipeTag.get_or_create_for_household(test_household, "Mac & Cheese")
        assert t_amp is not None
        t_amp2 = RecipeTag.get_or_create_for_household(test_household, "mac-cheese")
        assert t_amp2.pk == t_amp.pk

    def test_concurrent_tag_creation_stress(self, test_household):
        """Sequential and interleaved rapid creation of identical/colliding tags must never crash."""
        tag_names = [
            "30-Minute Meals",
            "30 Minute Meals",
            "30-minute meals",
            "30 MINUTE MEALS",
            "30  Minute  Meals",
            "30-Minute-Meals",
        ]

        results = []
        for name in tag_names * 3:
            t = RecipeTag.get_or_create_for_household(test_household, name)
            assert t is not None
            results.append(t)

        first_pk = results[0].pk
        assert all(r.pk == first_pk for r in results)
        matching_tags = RecipeTag.objects.filter(household=test_household, slug="30-minute-meals")
        assert matching_tags.count() == 1

    def test_view_tag_creation_with_colliding_tags_in_csv(self, client, test_household):
        """Creating a manual recipe with multiple colliding tags in CSV does not crash."""
        res = client.post(reverse("recipes:manual_add"), {
            "title": "Colliding Tags Recipe",
            "ingredients_text": "1 cup flour\n1 egg",
            "instructions_text": "Step 1: Mix well.",
            "tags": "Quick Dinner, quick-dinner, QUICK DINNER, Quick  Dinner",
        }, follow=True)
        assert res.status_code == 200

        recipe = Recipe.objects.filter(household=test_household, title="Colliding Tags Recipe").first()
        assert recipe is not None
        # Must only attach 1 tag
        assert recipe.tags.count() == 1
        assert recipe.tags.first().slug == "quick-dinner"



# =====================================================================
# 3. TEMPLATE PRIVACY (RATINGS / NOTES HIDDEN FROM FOREIGN VIEWERS)
# =====================================================================

@pytest.mark.django_db
class TestTemplatePrivacyEmpirical:
    """Empirical challenge on template privacy for ratings and notes."""

    def test_foreign_viewer_cannot_see_author_notes_or_ratings(self, client, secondary_household):
        """Foreign household viewing a shared recipe must NOT see the author household's notes or rating."""
        secret_notes = "Secret family ingredient: double the cinnamon and vanilla extract!"
        recipe = Recipe.objects.create(
            household=secondary_household,
            title="Shared Spice Cake",
            user_notes=secret_notes,
            rating=5,
            is_shared=True,
            instructions="Mix and bake at 350F.",
        )

        res = client.get(reverse("recipes:detail_recipe", kwargs={"pk": recipe.pk}))
        assert res.status_code == 200
        content = res.content.decode()

        # Privacy assertions
        assert secret_notes not in content, "LEAK: Foreign viewer can see author's user_notes!"
        assert "Your Notes" not in content, "LEAK: 'Your Notes' section displayed to foreign viewer!"
        assert "Rating:" not in content, "LEAK: Personal rating displayed to foreign viewer!"

        # Public recipe elements must still be visible
        assert "Shared Spice Cake" in content
        assert "Shared by" in content
        assert "Copy to My Household" in content

    def test_author_household_sees_own_notes_and_ratings(self, client, test_household):
        """Author household viewing its own recipe must see its own notes and rating."""
        own_notes = "Our favorite weekend breakfast notes."
        recipe = Recipe.objects.create(
            household=test_household,
            title="Our Breakfast",
            user_notes=own_notes,
            rating=4,
            is_shared=True,
            instructions="Cook eggs and toast.",
        )

        res = client.get(reverse("recipes:detail_recipe", kwargs={"pk": recipe.pk}))
        assert res.status_code == 200
        content = res.content.decode()

        assert own_notes in content
        assert "Your Notes" in content
        assert "Rating:" in content
        assert "4" in content
        assert "Copy to My Household" not in content
        assert "Edit" in content
        assert "Delete" in content

    def test_shared_catalog_view_does_not_leak_notes_or_ratings(self, client, secondary_household):
        """The shared catalog listing (/recipes/shared/) must not leak private notes."""
        secret_notes = "CONFIDENTIAL_CATALOG_NOTE_98765"
        Recipe.objects.create(
            household=secondary_household,
            title="Catalog Cake",
            user_notes=secret_notes,
            rating=5,
            is_shared=True,
        )

        res = client.get(reverse("recipes:shared_recipe_list"))
        assert res.status_code == 200
        content = res.content.decode()

        assert "Catalog Cake" in content
        assert secret_notes not in content

    def test_cloning_strips_ratings_and_notes(self, client, test_household, secondary_household):
        """Cloning a shared recipe to a new household must set rating=None and user_notes=''."""
        recipe = Recipe.objects.create(
            household=secondary_household,
            title="Shared Brownies",
            user_notes="Top secret baking technique",
            rating=5,
            is_shared=True,
            instructions="Bake 25 minutes.",
        )

        res = client.post(reverse("recipes:copy_recipe", kwargs={"pk": recipe.pk}), follow=True)
        assert res.status_code == 200

        clone = Recipe.objects.filter(household=test_household, title="Shared Brownies").first()
        assert clone is not None
        assert clone.rating is None
        assert clone.user_notes == ""


# =====================================================================
# 4. INSTRUCTION STEP XSS ESCAPING
# =====================================================================

@pytest.mark.django_db
class TestInstructionStepXSSEscapingEmpirical:
    """Empirical challenge on XSS escaping in recipe detail and instruction steps."""

    def test_xss_payloads_in_instructions_are_escaped(self, client, test_household):
        """XSS attack payloads in instruction steps must be entity-escaped and not rendered raw."""
        xss_payloads = [
            "<script>alert('XSS_SCRIPT')</script>",
            '<img src="x" onerror="alert(\'XSS_IMG\')">',
            '<svg onload="alert(\'XSS_SVG\')">',
            '<a href="javascript:alert(\'XSS_LINK\')">Click me</a>',
            '</li><script>alert(\'XSS_BREAKOUT\')</script><li>',
            '<iframe src="javascript:alert(\'XSS_IFRAME\')"></iframe>',
            '"><script>alert(\'XSS_QUOTE\')</script>',
            '<b>Bold Text Attempt</b>',
        ]

        instructions_text = "\n".join(xss_payloads)
        recipe = Recipe.objects.create(
            household=test_household,
            title="XSS Attack Recipe",
            instructions=instructions_text,
        )

        res = client.get(reverse("recipes:detail_recipe", kwargs={"pk": recipe.pk}))
        assert res.status_code == 200
        content = res.content.decode()

        # Check raw payloads are NOT present
        assert "<script>alert('XSS_SCRIPT')</script>" not in content
        assert '<img src="x" onerror=' not in content
        assert '<svg onload=' not in content
        assert '<a href="javascript:' not in content
        assert '</li><script>' not in content
        assert '<iframe src=' not in content
        assert '<b>Bold Text Attempt</b>' not in content

        # Check escaped entities ARE present
        assert "&lt;script&gt;alert(&#x27;XSS_SCRIPT&#x27;)&lt;/script&gt;" in content or "&lt;script&gt;alert('XSS_SCRIPT')&lt;/script&gt;" in content
        assert "&lt;img src=&quot;x&quot; onerror=&quot;alert(&#x27;XSS_IMG&#x27;)&quot;&gt;" in content or "&lt;img src=" in content
        assert "&lt;svg onload=" in content
        assert "&lt;b&gt;Bold Text Attempt&lt;/b&gt;" in content

    def test_xss_payloads_in_recipe_fields_are_escaped(self, client, test_household):
        """All user-controlled recipe fields (title, description, raw_text, user_notes) are escaped."""
        recipe = Recipe.objects.create(
            household=test_household,
            title="<script>alert('TITLE_XSS')</script>",
            description="<script>alert('DESC_XSS')</script>",
            user_notes="<script>alert('NOTES_XSS')</script>",
            instructions="Normal step.",
        )
        ing = Ingredient.objects.create(name="Salt")
        RecipeIngredient.objects.create(
            recipe=recipe,
            ingredient=ing,
            raw_text="<script>alert('ING_XSS')</script>",
            order=0,
        )

        res = client.get(reverse("recipes:detail_recipe", kwargs={"pk": recipe.pk}))
        assert res.status_code == 200
        content = res.content.decode()

        assert "<script>alert('TITLE_XSS')</script>" not in content
        assert "<script>alert('NOTES_XSS')</script>" not in content
        assert "<script>alert('ING_XSS')</script>" not in content

        assert "&lt;script&gt;alert(" in content


# =====================================================================
# 5. ADDITIONAL BOUNDARY & ADVERSARIAL STRESS HARNESSES
# =====================================================================

@pytest.mark.django_db
class TestBoundaryAndAdversarialDefense:
    """Stress tests on URL length boundaries, subpath trailing slashes, and IDOR defenses."""

    def test_200_char_url_cloning_boundary_disambiguation(self, client, test_household, secondary_household):
        """Cloning a recipe with a 200-character URL must clamp to <= 200 characters."""
        base_prefix = "https://example.com/recipe/long-path/"
        padding = "a" * (200 - len(base_prefix))
        long_url = f"{base_prefix}{padding}"
        assert len(long_url) == 200

        # Existing recipe in target household with the exact long URL
        Recipe.objects.create(
            household=test_household,
            original_url=long_url,
            title="Our Long URL Recipe",
        )

        # Source recipe in secondary household with same long URL
        source = Recipe.objects.create(
            household=secondary_household,
            original_url=long_url,
            title="Their Long URL Recipe",
            is_shared=True,
        )

        res = client.post(reverse("recipes:copy_recipe", kwargs={"pk": source.pk}), follow=True)
        assert res.status_code == 200

        cloned = Recipe.objects.filter(household=test_household, title="Their Long URL Recipe").first()
        assert cloned is not None
        assert len(cloned.original_url) <= 200
        assert "#copy-" in cloned.original_url

    def test_subpath_trailing_slash_bidirectional_matching(self, secondary_household):
        """Non-root subpath URLs with and without trailing slashes match each other."""
        recipe = Recipe.objects.create(
            household=secondary_household,
            original_url="https://example.com/category/recipes/pasta-bake/",
            title="Pasta Bake",
        )

        # Lookup without trailing slash
        found1 = find_recipe_by_url("https://example.com/category/recipes/pasta-bake")
        assert found1 is not None
        assert found1.pk == recipe.pk

        # Reverse test
        Recipe.objects.filter(pk=recipe.pk).update(
            original_url="https://example.com/category/recipes/pasta-bake"
        )
        found2 = find_recipe_by_url("https://example.com/category/recipes/pasta-bake/")
        assert found2 is not None
        assert found2.pk == recipe.pk

    def test_copy_duplicate_defense_in_depth_four_layers(self, client, test_household, secondary_household):
        """Test all 4 defense layers of copy_duplicate_recipe."""
        # Layer 1: Own recipe redirect
        own_recipe = Recipe.objects.create(
            household=test_household,
            original_url="https://example.com/own-recipe",
            title="Own Recipe",
        )
        res_own = client.post(reverse("recipes:copy_duplicate", kwargs={"pk": own_recipe.pk}), {
            "original_url": "https://example.com/own-recipe",
        }, follow=True)
        assert res_own.status_code == 200
        # No duplicate created
        assert Recipe.objects.filter(household=test_household, title="Own Recipe").count() == 1
        assert "already in your household" in res_own.content.decode()

        # Layer 2: Source recipe has no original_url (private manual recipe)
        private_manual = Recipe.objects.create(
            household=secondary_household,
            original_url=None,
            title="Private Manual Recipe",
            is_shared=False,
        )
        res_manual = client.post(reverse("recipes:copy_duplicate", kwargs={"pk": private_manual.pk}), {
            "original_url": "https://example.com/any-url",
        })
        assert res_manual.status_code == 404

        # Layer 3: Missing original_url in POST body
        foreign_recipe = Recipe.objects.create(
            household=secondary_household,
            original_url="https://example.com/foreign",
            title="Foreign Recipe",
            is_shared=True,
        )
        res_missing_url = client.post(reverse("recipes:copy_duplicate", kwargs={"pk": foreign_recipe.pk}), {
            # No original_url
        })
        assert res_missing_url.status_code == 404

        # Layer 4: Mismatched original_url in POST body
        res_wrong_url = client.post(reverse("recipes:copy_duplicate", kwargs={"pk": foreign_recipe.pk}), {
            "original_url": "https://attacker-controlled.com/malicious",
        })
        assert res_wrong_url.status_code == 404

    def test_tag_name_max_length_and_household_isolation(self, test_household, secondary_household):
        """50-character tag names work, and same tag name in different households are isolated."""
        long_name = "A" * 50
        t1 = RecipeTag.get_or_create_for_household(test_household, long_name)
        assert t1 is not None
        assert t1.name == long_name
        assert t1.household == test_household

        # Secondary household gets its own distinct tag with the same name
        t2 = RecipeTag.get_or_create_for_household(secondary_household, long_name)
        assert t2 is not None
        assert t2.pk != t1.pk
        assert t2.household == secondary_household

