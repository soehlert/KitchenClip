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
  -v $(pwd)/db.sqlite3:/app/data/db.sqlite3 \
  ghcr.io/soehlert/kitchenclip:latest
```

## Environment Variables

The following environment variables can be configured:

- `DJANGO_ALLOWED_HOSTS`: A comma-separated list of valid hostnames or IP addresses. Default: `localhost,127.0.0.1`
- `DEBUG`: Set to `1` to enable Django debug mode.
- `PYTHONWARNINGS`: Suppress specific Python warnings if needed.
