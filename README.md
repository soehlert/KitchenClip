# KitchenClip

KitchenClip is a personal recipe manager and meal planning application designed to help you organize recipes and plan your weekly meals.

## Features

- **Recipe Import**: Paste a recipe URL to automatically extract the title, ingredients, instructions, prep times, and photos.
- **Meal Planning Calendar**: A visual drag-and-drop interface for planning your weekly meals.
- **Custom Meals**: Add manual entries (e.g., "Leftovers" or "Eating Out") directly to the calendar.
- **Recipe Library**: A searchable database of all your saved recipes.
- **Future Ideas**: A dedicated space to save recipes you want to try later without adding them to your main library right away.
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

* **Household Isolation**: Each household has its own private recipe library and weekly meal plan. Spouses share the same household space with independent personal device passkeys.
* **Cross-Household Sharing**: Recipes can be marked as shared for other households to view and 1-click clone into their own collections.
* **Inviting Users / Enrolling Devices (CLI)**:
  To invite a user or pair a new device for an existing user, run the management command via Docker:
  ```bash
  docker compose exec web uv run python manage.py create_invite --username sam --household "Oehlert Home"
  ```
  Open the printed single-use link in your browser to log in and register your device's biometric Passkey.

## Environment Variables

The following environment variables can be configured:

- `DJANGO_ALLOWED_HOSTS`: A comma-separated list of valid hostnames or IP addresses. Default: `localhost,127.0.0.1`
- `DEBUG`: Set to `1` to enable Django debug mode.
- `PYTHONWARNINGS`: Suppress specific Python warnings if needed.
