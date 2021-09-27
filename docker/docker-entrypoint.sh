#!/bin/sh
set -e

version() { echo "$@" | awk -F. '{ printf("%d%03d%03d%03d\n", $1,$2,$3,$4); }'; }

exit_backend() {
  echo "Exiting backend"
  python3 4cat-daemon.py stop
  exit 0
}

trap exit_backend INT TERM

# Run docker_setup to update any environment variables if they were changed
python3 docker/docker_setup.py

echo "Waiting for postgres..."

while ! nc -z db 5432; do
  sleep 0.1
done

echo "PostgreSQL started"

# Check if DB exists and creates admin is it does not
user_created=false
# This seems SUPER weird. It returns true as long as DB exists; doesn't matter if admin does.
if psql --host=db --port=5432 --user=$POSTGRES_USER --dbname=$POSTGRES_DB -tAc "SELECT 1 FROM users WHERE name='admin'"; then echo 'Seed present'; else
echo 'Generating admin user'

# Generate password for admin user
admin_password=$(openssl rand -base64 12)

# Seed DB
cd /usr/src/app && psql --host=db --port=5432 --user=$POSTGRES_USER --dbname=$POSTGRES_DB < backend/database.sql

python3 /usr/src/app/helper-scripts/create_user.py -u admin -e -p "$admin_password" -a
echo 'Your admin username:' >> docker/shared/login.txt
echo 'admin' >> docker/shared/login.txt
echo 'Your admin password:' >> docker/shared/login.txt
echo "$admin_password" >> docker/shared/login.txt
user_created=true

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

# Run migrations if current version does not equal target
# Could perhaps remove this... needs rethink
if [ "$(version "$CURRENT")" -ge "$(version "$TARGET")" ]; then
    echo "Version is up to date"
else
    echo "Running migrations"
    python3 helper-scripts/migrate.py --yes
fi

# Inform user of admin password if created
if [ $user_created = true ] ; then
  echo '4CAT account information:'
  echo 'Your admin username:'
  echo 'admin'
  echo 'Your admin password:'
  echo "$admin_password"
  echo 'This information has been saved in your Docker 4cat_backend container'
  echo 'as login.txt'
  echo ''
fi

echo "4CAT is accessible at:"
echo "http://$SERVER_NAME:$PUBLIC_PORT"
echo ''

# If backend did not close in time, PID lockfile remains; Remove lockfile
rm -f ./backend/4cat.pid

# Start 4CAT backend
python3 4cat-daemon.py start

# Hang out until SIGTERM received
while true; do
    sleep 1
done
