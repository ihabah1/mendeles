release: python manage.py migrate --noinput && python manage.py setup_portal
web: python manage.py collectstatic --noinput && gunicorn mandeles_portal.wsgi:application --bind 0.0.0.0:$PORT --workers 2
