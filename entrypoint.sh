#!/bin/bash
set -e

# If arguments are passed, assume we want to run that specific command (like Celery)
if [ $# -gt 0 ]; then
    echo "Running custom command: $@"
    exec "$@"
fi

echo "Running migrations..."
python3 manage.py migrate

echo "Collecting static files..."
python3 manage.py collectstatic --noinput

echo "Starting Gunicorn..."
exec gunicorn --bind 0.0.0.0:8000 --workers 3 KitchenClip.wsgi:application