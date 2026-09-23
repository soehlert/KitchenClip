# KitchenClip

KitchenClip is a personal recipe manager and meal planning application designed to help you organize recipes and plan your weekly meals.

## Features

- **Recipe Import**: Paste a recipe URL to automatically extract the title, ingredients, instructions, prep times, and photos.
- **Create from Scratch**: Build custom recipes directly from scratch with dynamic ingredient and instruction row management.
- **Meal Planning Calendar**: A visual drag-and-drop interface for planning your weekly meals.
- **Custom Meals**: Add manual entries (e.g., "Leftovers" or "Eating Out") directly to the calendar.
- **Recipe Library**: A searchable database of all your saved recipes.
- **Saved for Later**: A dedicated space to save recipes you want to try later without adding them to your main library right away.
- **Recipe Details**: Click any planned meal or recipe card to view its ingredients and instructions in a popup modal.
- **Kiosk Mode**: A read-only, high-contrast dashboard (`/meal-plan/kiosk/`) ideal for wall-mounted displays in the kitchen.

## Running the Application

KitchenClip is containerized using Docker. 

### Option 1: Docker Compose
To run the application with its persistent storage:

```bash
docker compose up -d
```
The application will be accessible at `http://localhost:8888`.

### Option 2: Raw Docker Command
To run the pre-built image directly, ensure you mount the appropriate volumes so your data persists:

```bash
docker run -d \
  --name kitchenclip \
  -p 8888:8000 \
  -e DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1 \
  -e DEBUG=1 \
  -v $(pwd)/recipes:/app/recipes \
  -v $(pwd)/KitchenClip:/app/KitchenClip \
  -v $(pwd)/templates:/app/templates \
  -v $(pwd)/data/db.sqlite3:/app/data/db.sqlite3 \
  ghcr.io/soehlert/kitchenclip:latest
```

## Multi-Household & Authentication

KitchenClip supports multi-household tenancy with zero-friction, passwordless authentication using single-use CLI Magic Links and WebAuthn Passkeys (TouchID / FaceID):

* **Household Isolation**: Each household has its own private recipe library and weekly meal plan.
* **Co-Habitants / Multi-User**: Multiple users (e.g., spouses/partners) can belong to the same household with independent devices and passkeys while sharing the same recipe collection and meal calendar.
* **Cross-Household Sharing**: Recipes can be marked as shared for other households to browse and 1-click clone into their own collections.

### CLI Invitation Commands

Generate single-use enrollment links via Docker Compose:

1. **Create an Initial User & New Household**:
   ```bash
   docker compose exec web uv run python manage.py create_invite --username alice --household "Baker Family" --base-url http://localhost:8888
   ```

2. **Add a Second User to an Existing Household**:
   ```bash
   docker compose exec web uv run python manage.py create_invite --username bob --household "Baker Family" --base-url http://localhost:8888
   ```

3. **Authorize an Additional Device for an Existing User**:
   ```bash
   docker compose exec web uv run python manage.py create_invite --username alice --base-url http://localhost:8888
   ```

4. **Create a Second Household**:
   ```bash
   docker compose exec web uv run python manage.py create_invite --username charlie --household "Smith Family" --base-url http://localhost:8888
   ```

### Testing Multi-Household Tenancy Locally (No Cloudflare)

To test isolation and sharing between two distinct households on localhost:

1. **Launch Containers**: Ensure `CLOUDFLARE_ENABLED=0` in `.env` or `docker-compose.override.yml`, then start containers:
   ```bash
   docker compose up -d
   ```
2. **Generate Two Household Invites**:
   ```bash
   docker compose exec web uv run python manage.py create_invite --username alice --household "Baker Family" --base-url http://localhost:8888
   docker compose exec web uv run python manage.py create_invite --username charlie --household "Smith Family" --base-url http://localhost:8888
   ```
3. **Log in as Household 1**:
   - Open Alice's invite URL in your regular browser tab.
   - Click **Register Passkey & Sign In** (or click **Sign In on this Browser (Session Only)**).
   - Create a recipe from scratch or import one.
4. **Log in as Household 2**:
   - Open Charlie's invite URL in a **Private / Incognito window** (or a separate browser like Safari) so sessions do not conflict.
   - Complete enrollment. Notice that Charlie's recipe list and meal plan are completely isolated and empty.
5. **Test Cross-Household Sharing**:
   - In Alice's browser, edit a recipe and check **Share with other households**.
   - In Charlie's browser, click **Shared Recipes** in the top navigation. Alice's recipe appears! Click **Copy to My Recipes** to clone a copy into Charlie's collection.
6. **Add a Second User to an Existing Household**:
   - Run the command to invite Bob to `"Baker Family"`.
   - Open Bob's link in another private session. Bob will see the "Baker Family" badge in the navigation and have full access to Alice's recipes and shared meal plan!


## Environment Variables

The following environment variables can be configured:

- `DJANGO_ALLOWED_HOSTS`: A comma-separated list of valid hostnames or IP addresses. Default: `localhost,127.0.0.1`
- `DEBUG`: Set to `1` to enable Django debug mode.
- `PYTHONWARNINGS`: Suppress specific Python warnings if needed.
