#!/usr/bin/env sh
set -e
cd "$(dirname "$0")/.."

echo "Running database migrations..."
python manage.py migrate --noinput

echo "Ensuring admin user and demo data..."
python manage.py setup_portal

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting gunicorn on port ${PORT:-8000}..."
exec gunicorn mandeles_portal.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers 2 \
  --timeout 120
