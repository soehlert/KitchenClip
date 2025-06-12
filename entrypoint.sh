#!/bin/bash
set -e

echo "Running migrations..."
python manage.py migrate

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting Gunicorn..."
exec gunicorn --bind 0.0.0.0:8000 --workers 3 KitchenClip.wsgi:application