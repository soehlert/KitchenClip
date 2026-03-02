# KitchenClip Testing Strategy

This document outlines the testing strategy, tools, and execution steps for the KitchenClip application.

## Overview
We employ a combination of unit tests, integration tests, and end-to-end (E2E) tests to ensure both backend and frontend reliability. All tests are designed to execute completely locally without reaching out to external networks, utilizing tools like `unittest.mock` to stub network calls and Playwright for headless browser automation.

---

## 1. Environment Configuration: `DJANGO_ALLOW_ASYNC_UNSAFE`
When running the E2E tests, you will see the flag `DJANGO_ALLOW_ASYNC_UNSAFE=true` used in the docker command. 
**Why is this needed?**
Pytest-Playwright uses an asynchronous event loop to drive the headless browser. However, Django's ORM operations (like creating test data or making assertions on the database inside your test functions) are synchronous. Django explicitly raises a `SynchronousOnlyOperation` error if you try to query the database from an async context to prevent unexpected behavior.
By setting `DJANGO_ALLOW_ASYNC_UNSAFE=true`, we tell Django to bypass this strict check for our test suite, allowing our synchronous DB assertions to run alongside Playwright's async browser interactions within the same test function.

---

## 2. Backend Testing
Backend testing uses `pytest` and `pytest-django`, with configuration defined entirely within `pyproject.toml`.

### Executing Backend Tests
Run the entire backend test suite:
```bash
docker compose exec web uv run pytest recipes/tests/
```

Run a specific test file:
```bash
docker compose exec web uv run pytest recipes/tests/test_views.py
```

Run one specific test function:
```bash
docker compose exec web uv run pytest recipes/tests/test_views.py::test_recipe_manual_create
```

### Individual Backend Tests

#### `test_models.py`
These tests verify that our database models function correctly at a fundamental level.
*   **`test_recipe_creation`**: Ensures a basic recipe can be saved to the database.
*   **`test_total_time_display` (multiple)**: Verifies the `total_time_display` property logic (e.g., falling back to `prep_time` + `cook_time` vs explicitly using `total_time`).
*   **`test_meal_plan_creation`**: Verifies `MealPlan` objects successfully link to a `Recipe` via Foreign Keys.
*   **`test_auto_generated_ingredient_slug`**: Ensures `Ingredient` models auto-generate slugs when saved.

#### `test_services.py`
These tests focus on the Celery async workflows and business logic, heavily utilizing `@patch` from `unittest.mock` to avoid network requests.
*   **`test_check_and_send_upcoming_meals_dummy_mode`**: Sets `ENABLE_COOKING_NOTIFICATIONS=False` and verifies that the system correctly calculates whether it is currently inside the 30-minute "advance notice" buffer window (meaning `localtime()` has passed `meal_time` minus `total_recipe_time` minus `30 minutes`) without actually dialing the webhook.
*   **`test_check_and_send_upcoming_meals_live_mode`**: Sets `ENABLE_COOKING_NOTIFICATIONS=True` and mocks `httpx.AsyncClient().post`. It fast-forwards time using `mock_localtime` to force the notification threshold to pass, verifying that `httpx.post` is indeed called and checking the mock's arguments to ensure the JSON payload precisely matches the expected message text.

#### `test_views.py`
These tests use Django's Test Client to simulate HTTP GET/POST requests.
*   **`test_recipe_list_view`**: Asserts the main index `/recipes/` returns a 200 HTTP status.
*   **`test_recipe_manual_create`**: Submits a POST payload to `/add/manual/` and verifies the new recipe sits in the database afterwards.
*   **`test_recipe_edit`**: Submits a POST payload to `/<id>/edit/` to verify modifying an existing recipe.
*   **`test_meal_plan_api_update`**: Hits the JSON API endpoint used by the "Apply All" frontend javascript and asserts it properly updates database slots.
---

## 3. Frontend E2E Testing
Frontend testing utilizes `pytest-playwright` running against a local Django test server via the `live_server` fixture.

> **Important:** E2E tests must run inside the `test` Docker stage (defined in `docker-compose.test.yml`), **not** the production `web` container. The production container does not have Playwright or Chromium installed.

### What is the `page` fixture?
In Playwright, `page` represents a single tab in a browser. It is incredibly powerful and provides the core API to interact with the DOM—such as navigating (`page.goto()`), filling out inputs (`page.fill()`), clicking buttons (`page.click()`), and extracting text or states. Pytest automatically injects this fully-configured browser context into your function whenever you request it as an argument.

### Executing Frontend Tests
Run the entire E2E test suite:
```bash
docker compose -f docker-compose.test.yml run --rm test
```

Run a specific E2E test file:
```bash
docker compose -f docker-compose.test.yml run --rm test pytest tests/e2e/test_meal_plan_ui.py --browser chromium -v
```

Run one specific E2E test function:
```bash
docker compose -f docker-compose.test.yml run --rm test pytest tests/e2e/test_meal_plan_ui.py::test_meal_plan_page_load --browser chromium -v
```

### Individual E2E Tests

#### `test_recipe_crud_ui.py`
*   **`test_manual_recipe_add_and_view`**: Tests the complete UI flow for creating a recipe. It navigates to `/add/manual/`, fills out the form inputs using `page.fill()`, clicks submit, waits for the redirect, and uses `expect(page.locator("text=..."))` to verify the recipe appears in the list view.
*   **`test_recipe_view_edit_delete`**: Tests the full modification lifecycle. It navigates to a specific recipe's detail page, asserts all content is visible, clicks the `Edit` navigation button, fills out a new `title` payload, saves, asserts the redirect and DB update, then hits the `Delete` button, confirms deletion in the template modal, and verifies the recipe disappears from the index list entirely.

#### `test_meal_plan_ui.py`
*   **`test_meal_plan_page_load`**: Creates a dummy recipe, navigates to the meal planner, and asserts that the Sidebar and Global Time flatpickr inputs successfully initialize and attach to the hidden inputs.
*   **`test_recipes_list_page`**: Ensures the sidebar component properly loads and renders existing recipes within its draggable list.
*   **`test_meal_plan_drag_and_drop`**: Verifies dynamic Playwright event interactions. Evaluates vanilla Javascript to dispatch native HTML5 `DragEvent` actions (populating the `DataTransfer` payload and manually triggering `bubbles: true` for `dragstart`, `dragenter`, `dragover`, and `drop`) directly onto the UI `.meal-slot`. Finally acts on the Promise return from the fetch API to assert the underlying SQLite `MealPlan` record is updated correctly.
