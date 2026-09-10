# KitchenClip Test Infrastructure & E2E Testing Framework

## 1. Overview & Architecture

KitchenClip employs a comprehensive, dual-tier test architecture designed to validate both backend services and frontend browser experiences across single and multi-household environments:

1. **Unit & Integration Testing**: `pytest` + `pytest-django` executing in the local virtual environment or within the Docker `web` service.
2. **End-to-End (E2E) Multi-Household & UI Testing**: Located under `tests/e2e/`, providing exhaustive 4-tier matrix coverage and headless browser automation via `pytest-playwright` and Chromium against a live Django test server (`live_server`).

### Key Architectural Safeguards
- **`DJANGO_ALLOW_ASYNC_UNSAFE=true`**: Required when running Playwright E2E tests alongside Django ORM operations. Pytest-Playwright runs an asynchronous event loop; setting this flag instructs Django's ORM to permit synchronous database queries within the test process.
- **Dedicated Docker Test Runner**: E2E browser tests are packaged within `docker-compose.test.yml` (the `test` service target), which includes Playwright, Chromium headless, and system libraries for deterministic execution across any host platform.
- **Environment Adaptability**: In restricted sandboxed environments (such as macOS seatbelt sandboxes where child-process socket creation is blocked), the E2E framework automatically detects socket constraints via session probe and cleanly skips browser-level socket tests while executing all comprehensive HTTP client E2E flows hermetically.
- **Hermetic & Zero External Dependencies**: All tests run 100% locally with zero internet access. External HTTP requests for recipe scraping or notification webhooks are stubbed using `unittest.mock.patch` and mock parser registries.

---

## 2. WebAuthn Passkey Testing Architecture via Chrome DevTools Protocol (CDP)

Because WebAuthn requires platform or roaming biometric authenticators (TouchID, FaceID, Windows Hello, YubiKey), browser-driven Playwright tests simulate authenticators using Chrome DevTools Protocol (CDP) virtual authenticators.

```python
def setup_virtual_authenticator(page: Page):
    """Initialize a WebAuthn virtual authenticator via Chrome DevTools Protocol."""
    cdp = page.context.new_cdp_session(page)
    cdp.send("WebAuthn.enable")
    authenticator = cdp.send(
        "WebAuthn.addVirtualAuthenticator",
        {
            "options": {
                "protocol": "ctap2",
                "transport": "internal",
                "hasResidentKey": True,
                "hasUserVerification": True,
                "isUserVerified": True,
                "automaticPresenceSimulation": True,
            }
        },
    )
    return cdp, authenticator["authenticatorId"]
```

For environments or devices without biometric capabilities, KitchenClip provides a direct session fallback sign-in (`/auth/invite/<token>/redeem/`) which establishes a 1-year persistent session (`SESSION_COOKIE_AGE = 31536000`) and consumes the single-use token atomically.

---

## 3. Command Invocations

### A. Running Tests via Docker (Standard CI/Container Workflow)

Run full backend test suite:
```bash
docker compose exec web uv run pytest recipes/tests/ -v
```

Run full E2E test suite:
```bash
docker compose -f docker-compose.test.yml run --rm test
```

Run specific E2E test file:
```bash
docker compose -f docker-compose.test.yml run --rm test pytest tests/e2e/test_multi_household_e2e.py -v
```

Run specific E2E test function:
```bash
docker compose -f docker-compose.test.yml run --rm test pytest tests/e2e/test_multi_household_e2e.py::TestTier1R1AuthAndPasskeys::test_t1_r1_01_cli_invite_landing_page -v
```

### B. Running Tests Locally (Host System)

Backend unit and integration tests:
```bash
uv run pytest recipes/tests/ -v
```

Full E2E test suite (requires `playwright install chromium`):
```bash
DJANGO_ALLOW_ASYNC_UNSAFE=true uv run pytest tests/e2e/ -v
```

Code quality and Django health checks:
```bash
uv run ruff check .
uv run python manage.py check
```

---

## 4. Test Fixtures & Reusable Helpers

Defined in `tests/e2e/conftest.py`:

| Fixture | Scope | Description |
|---|---|---|
| `e2e_household` | function | Primary test household instance (`"E2E Primary Household"`). |
| `e2e_user` | function | Primary household admin user (`e2e_primary@example.com`). |
| `e2e_household_spouse` | function | Primary household member user (`e2e_spouse@example.com`) sharing primary household. |
| `e2e_secondary_household` | function | Secondary test household instance (`"E2E Secondary Household"`). |
| `e2e_secondary_user` | function | Secondary household admin user (`e2e_secondary@example.com`). |
| `create_cli_invite` | function | Management command runner for `create_invite`, returning the raw 32-byte URL-safe token. |
| `e2e_client` | function | Django `Client` pre-authenticated as `e2e_user`. |
| `e2e_spouse_client` | function | Isolated Django `Client` pre-authenticated as `e2e_household_spouse`. |
| `e2e_secondary_client` | function | Isolated Django `Client` pre-authenticated as `e2e_secondary_user`. |
| `session_injector` | function | Helper function to inject session cookies into Playwright browser context. |
| `e2e_autologin` | autouse | Automatically authenticates Playwright `page` contexts with a 1-year session. |
| `browser` | session | Safe Playwright browser launcher with environment capability detection and single-process flags. |

---

## 5. 4-Tier E2E Testing Matrix Summary

The multi-household E2E suite (`tests/e2e/test_multi_household_e2e.py`) implements 52 exhaustive test cases structured across four rigorous tiers:

### Tier 1: Core Feature Coverage
- **R1 (Authentication & Passkeys)**: CLI invite landing page rendering, direct session fallback sign-in, attack surface elimination (zero public registration, zero passwords), multi-device independent enrollment for same user, WebAuthn registration gating behind valid token.
- **R2 (Household Scoping & Isolation)**: Same-household spouse recipe list synchronization, same-household meal plan synchronization, cross-household recipe isolation, cross-household meal plan isolation, scoped `original_url` independent ownership.
- **R3 (Cross-Household Sharing)**: Toggling `is_shared=True` publishes to shared catalog, unauthenticated catalog access redirects to login, privacy-preserving shared detail view (author notes and ratings hidden), 1-click "Copy to My Household" deep cloning of recipe and ingredients, independent mutation of cloned copies.
- **R4 (Duplicate URL Detection)**: Cross-household duplicate scraping alert banner, banner UI controls (`#btn-copy-existing`, `#btn-force-scrape`), banner "Copy to My Household" with custom form metadata, banner "Scrape Fresh Anyway" bypass, same-household duplicate form rejection.

### Tier 2: Boundary & Corner Cases
- **R1 Boundaries**: Expired token returns 400 with "Invite Link Expired", double-redemption replay defense returns 400 with "Invite Link Already Redeemed", malformed/non-existent token returns 404, idempotent crawler GET requests (tokens remain unconsumed), open redirect sanitization on redeem.
- **R2 Boundaries**: Direct GET on foreign private recipe returns 404, direct GET/POST edit on foreign recipe returns 404, direct POST delete on foreign recipe returns 404, cross-household meal plan API injection rejected, tag isolation across households.
- **R3 Boundaries**: Copying own household recipe redirects with info message, copy foreign private recipe returns 404, deep clone URL collision disambiguation (`#copy-<hex>`), ingredient ordering and fractional measurements preserved with exact fidelity, immediate revocation of shared status upon unchecking `is_shared`.
- **R4 Boundaries**: URL normalization variations (`http` vs `https`, `www.`, trailing slash, tracking query parameters), anti-IDOR URL mismatch on copy-duplicate (404), anti-IDOR on recipe without URL (404), custom user notes/rating from form preserved on duplicate copy, shared link visibility conditional on source recipe share status.

### Tier 3: Cross-Feature Pairwise Combinations
- **T3-PAIR-01 (R1 + R2)**: CLI provisioning of multiple users into separate households -> redeem -> verify isolated data spaces.
- **T3-PAIR-02 (R1 + R3)**: Direct authenticated session discovering and cloning shared recipe across households.
- **T3-PAIR-03 (R1 + R4)**: Authenticated user triggers duplicate detection banner and clones record with custom notes.
- **T3-PAIR-04 (R2 + R3)**: Deleting source recipe in author household leaves target household's cloned copy completely intact.
- **T3-PAIR-05 (R2 + R4)**: Both households own identical URL via force-scrape -> independent household uniqueness constraints hold without collision.
- **T3-PAIR-06 (R3 + R4)**: Duplicate banner links to shared recipe -> user navigates and clones via shared detail view.

### Tier 4: Real-World Application Workflows
- **T4-SCENARIO-01 (Culinary Collaboration Lifecycle)**: Complete two-household onboarding, sharing, cloning, mutation, and meal planning between Chef Gordon (Gourmet Household) and Baker Paul (Bakers Household).
- **T4-SCENARIO-02 (Multi-Device Onboarding)**: Single user onboards MacBook and iPhone via two separate CLI invites; verifies instant bi-directional synchronization of recipes and weekly meal plans.
- **T4-SCENARIO-03 (Recipe Forking & Resharing Chain)**: 3-Household chain where Household A shares v1, Household B clones, mutates to vegetarian, and re-shares as v2, and Household C browses and clones v2.
- **T4-SCENARIO-04 (Adversarial Security Hardening)**: Attacker in Household Evil attempts IDOR enumeration across detail, edit, delete, copy, and duplicate endpoints for private recipes of Household Victim; all attempts return 404 with zero data leaked.

---

## 6. Coverage Mapping to Original Acceptance Criteria

| Acceptance Criterion | Covered By Tests | Verification Mode |
|---|---|---|
| CLI invite generates signed single-use URL | `test_auth.py:TestCLIInviteCommand`, `test_t1_r1_01` | Unit + E2E |
| Web UI has zero registration/password/admin forms | `test_auth.py:TestAttackSurfaceHardening`, `test_t1_r1_03` | Unit + E2E |
| WebAuthn registration gated strictly behind token | `test_auth.py:TestWebAuthnRegistration`, `test_t1_r1_05` | Unit + E2E |
| Multi-device enrollment without cloud sync | `test_auth.py:test_cli_create_invite_existing_user`, `test_t1_r1_04`, `test_t4_scenario_02` | Unit + E2E |
| 1-year persistent session | `test_auth.py:test_invite_redeem_post_success`, `test_t1_r1_02` | Unit + E2E |
| Safe zero-data-loss database migration | `0015/0016/0017`, `test_models.py:test_household_and_user_profile` | Migration + Unit |
| Spouses in same household share recipes & meal plan | `test_scoping.py:test_same_household_multi_user_access`, `test_t1_r2_01`, `test_t1_r2_02` | Unit + E2E |
| Cross-household private recipes/plans isolated (404) | `test_scoping.py:test_cross_household_isolation`, `test_t1_r2_03`, `test_t2_r2_01` | Unit + E2E |
| Browse shared recipes catalog | `test_sharing.py:TestCrossHouseholdSharingVisibility`, `test_t1_r3_01` | Unit + E2E |
| 1-click "Copy to My Household" deep clone | `test_sharing.py:TestRecipeDeepCloning`, `test_t1_r3_04`, `test_t2_r3_03` | Unit + E2E |
| Duplicate external URL scraping detection banner | `test_duplicate_alerts.py`, `test_t1_r4_01`, `test_t1_r4_02` | Unit + E2E |
| Banner "Copy to My Household" & "Scrape Fresh Anyway" | `test_duplicate_alerts.py:test_duplicate_action_*`, `test_t1_r4_03`, `test_t1_r4_04` | Unit + E2E |
