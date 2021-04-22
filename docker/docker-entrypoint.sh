#!/bin/sh
set -e

version() { echo "$@" | awk -F. '{ printf("%d%03d%03d%03d\n", $1,$2,$3,$4); }'; }

echo "Waiting for postgres..."

while ! nc -z db 5432; do
  sleep 0.1
done

echo "PostgreSQL started"

#seed db
if psql --host=db --port=5432 --user=fourcat --dbname=fourcat -tAc "SELECT 1 FROM users WHERE name='admin@admin.com'"; then echo 'Seed present'; else
echo 'Generating admin user'

#generate password for admin user
admin_password=$(openssl rand -base64 12)

echo 'Your admin password:'
echo "$admin_password"

#seed db
cd /usr/src/app && psql --host=db --port=5432 --user=fourcat --dbname=fourcat < backend/database.sql

python3 /usr/src/app/helper-scripts/create_user.py -u admin@admin.com -p "$admin_password"
echo "$admin_password" > /usr/src/app/.tcat_created

fi

echo 'Starting app'
cd /usr/src/app

# Check for Migrations
CURRENT="1.9"
CURRENT_FILE=".current-version"

if test -f "$CURRENT_FILE"; then
    CURRENT=$(head -n 1 $CURRENT_FILE)
fi

TARGET="1.9"
TARGET_FILE="VERSION"

if test -f "$TARGET_FILE"; then
    TARGET=$(head -n 1 $TARGET_FILE)
fi

if [ "$(version "$CURRENT")" -ge "$(version "$TARGET")" ]; then
    echo "Version is up to date"
else
    echo "Running migrations"
    python3 helper-scripts/migrate.py --yes
fi

python3 4cat-daemon.py start

gunicorn --reload --bind 0.0.0.0:5000 webtool:app






