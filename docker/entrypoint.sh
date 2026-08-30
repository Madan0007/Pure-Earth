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

# --- Start the server FIRST so the platform's port scan (Render, etc.) sees
# an open port immediately, instead of timing out while migrate/collectstatic
# run. Runs in the background; we bring migrate/collectstatic up after it,
# then reload Gunicorn workers so they pick up the fresh static manifest.
echo "Starting server..."
rm -f /tmp/gunicorn.pid
"$@" &
SERVER_PID=$!

trap 'echo "Forwarding signal to server (pid $SERVER_PID)"; kill -TERM "$SERVER_PID" 2>/dev/null; wait "$SERVER_PID"' TERM INT

# Run migrations
echo "Running migrations..."
python manage.py migrate --noinput

# NOTE: the previous version of this script ran `python manage.py flush
# --no-input` here on every single boot. flush wipes every row in every
# table. On a platform like Render, the container restarts on every deploy
# AND after any crash -- so this was silently erasing all production data
# (every employee, every leave request, everything) each time the app
# restarted, not just on first setup. It has been removed. If you need to
# reset the database, run `python manage.py flush` manually and deliberately
# from Render's Shell tab -- never as part of routine startup.

# Create a default superuser ONLY if no superuser exists yet, and ONLY from
# environment variables -- never hardcode credentials in a script that lives
# in a public git repo. Safe to leave in: it does nothing once a superuser
# already exists, so it won't reset anyone's password on later restarts.
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

# Collect static files.
#
# --clear is deliberate: STATIC_ROOT is a named volume that outlives the image,
# and plain collectstatic leaves anything it considers unmodified in place. With
# CompressedStaticFilesStorage that includes the pre-compressed .gz/.br
# siblings, so after an upgrade WhiteNoise happily served a previous release's
# global.js.gz to every browser (which all send Accept-Encoding: gzip) while
# curl, getting the identity encoding, saw the current file — JS functions
# "not defined" and half-rendered pages that looked fine to any check that
# bypassed static serving. Wiping first keeps what we serve equal to the image.
echo "Collecting static files..."
python manage.py collectstatic --noinput --clear

# Gunicorn workers cache WhiteNoise's static manifest at boot; reload them so
# the files we just wrote are actually served instead of a stale in-memory
# manifest from before collectstatic ran.
if kill -0 "$SERVER_PID" 2>/dev/null; then
  echo "Reloading server workers to pick up fresh static files..."
  kill -HUP "$SERVER_PID"
fi

echo "Startup complete."
wait "$SERVER_PID"
