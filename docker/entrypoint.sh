#!/bin/bash
set -e
echo "Starting Horilla HR..."
DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"
# Wait for PostgreSQL to be ready (with timeout)
echo "Waiting for PostgreSQL at ${DB_HOST}:${DB_PORT}..."
MAX_TRIES=30
COUNT=0
while ! nc -z "$DB_HOST" "$DB_PORT"; do
  COUNT=$((COUNT + 1))
  if [ "$COUNT" -ge "$MAX_TRIES" ]; then
    echo "ERROR: PostgreSQL not available at ${DB_HOST}:${DB_PORT} after $MAX_TRIES attempts"
    exit 1
  fi
  sleep 1
done
echo "PostgreSQL is ready!"
# Handle Secret Key setup
SECRET_KEY_FILE="/app/media/.generated_secret_key"
case "${SECRET_KEY:-}" in
  ""|"django-insecure-default-key"|"dev-secret-key-change-in-production"|"django-insecure-j8op9)1q8\$1&0^s&p*_0%d#pr@w9qj@1o=3#@d=a(^@9@zd@%j"|change-me*|django-insecure-*)
    if [ -f "$SECRET_KEY_FILE" ]; then
      SECRET_KEY="$(cat "$SECRET_KEY_FILE")"
      echo "Using previously generated SECRET_KEY from $SECRET_KEY_FILE"
    else
      SECRET_KEY="$(python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())')"
      mkdir -p "$(dirname "$SECRET_KEY_FILE")"
      printf '%s' "$SECRET_KEY" > "$SECRET_KEY_FILE"
      chmod 600 "$SECRET_KEY_FILE"
      echo "Generated a new random SECRET_KEY and saved it to $SECRET_KEY_FILE"
    fi
    export SECRET_KEY
    ;;
esac

# 1. Run migrations FIRST so database tables exist
python manage.py migrate --noinput

# NOTE: this used to run `python manage.py flush --no-input` here, wiping
# every row in every table on EVERY container start (every deploy, every
# crash-restart). Removed -- it was silently erasing all production data
# repeatedly. If you ever need to reset the database on purpose, run
# `python manage.py flush` manually and deliberately from Render's Shell tab,
# never as part of routine startup.

# 2. Auto-create a default superuser ONLY if one doesn't already exist, and
# ONLY from environment variables. The previous version hardcoded a username
# and plaintext password directly in this script, which lives in a public
# git repo -- effectively publishing a valid admin credential to anyone who
# finds the repo. Set DJANGO_SUPERUSER_USERNAME / DJANGO_SUPERUSER_PASSWORD
# (and optionally DJANGO_SUPERUSER_EMAIL) on Render instead. This block does
# nothing once any superuser exists, so it's safe to leave in on every boot.
if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
  python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(is_superuser=True).exists():
    User.objects.create_superuser(
        '${DJANGO_SUPERUSER_USERNAME}',
        '${DJANGO_SUPERUSER_EMAIL:-admin@example.com}',
        '${DJANGO_SUPERUSER_PASSWORD}',
    )
    print('Superuser created successfully!')
else:
    print('A superuser already exists; skipping creation.')
" || true
else
  echo "DJANGO_SUPERUSER_USERNAME/PASSWORD not set; skipping superuser auto-creation."
fi

# 3. Collect static files
python manage.py collectstatic --noinput --clear

echo "Starting server..."
exec gunicorn horilla.wsgi:application --bind 0.0.0.0:${PORT:-8000}
