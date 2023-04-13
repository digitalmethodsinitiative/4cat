#!/bin/sh
set -e

exit_backend() {
  echo "Exiting backend"
  python3 4cat-daemon.py stop
  echo "Exiting frontend"
  python3 -c "from common.lib.helpers import get_parent_gunicorn_pid;import os;import signal;os.kill(get_parent_gunicorn_pid(), signal.SIGTERM)"
  echo "Shutdown complete; Bye!"
  exit 0
}

trap exit_backend INT TERM

# Check postgresql password setup
if [ -e ~/.pgpass ]
then
  :
else
  echo "$POSTGRES_HOST:5432:$POSTGRES_DB:$POSTGRES_USER:$POSTGRES_PASSWORD" > ~/.pgpass
  chmod 600 ~/.pgpass
  export PGPASSFILE=~/.pgpass
  echo ".pgpass created"
fi

# Start postgresql
service postgresql start
echo "Waiting for postgres..."
while ! nc -z "$POSTGRES_HOST" 5432; do
  sleep 0.1
done
echo "PostgreSQL started"

# Create Database if it does not already exist
if [ "$(psql --quiet --host="$POSTGRES_HOST" --port=5432 --user="$POSTGRES_USER" --dbname="$POSTGRES_DB" -tAc "SELECT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'jobs')")" = 't' ]; then
  # Table already exists
  echo "Database already created"
else
  echo "Creating Database"
  # No database exists, build and seed
  cd /4cat && sudo -u postgres psql -c "CREATE USER $POSTGRES_USER WITH ENCRYPTED PASSWORD '$POSTGRES_PASSWORD' CREATEDB;"
  sudo -u postgres psql -c "CREATE database $POSTGRES_DB;"
  sudo -u postgres psql -c " GRANT ALL PRIVILEGES ON DATABASE $POSTGRES_DB to $POSTGRES_USER;"
  psql --host="$POSTGRES_HOST" --port=5432 --user="$POSTGRES_USER" --dbname="$POSTGRES_DB" < backend/database.sql
  # Create .current-version file
  if [ ! -e data/config ] ; then mkdir data/config ; else : ; fi && cp VERSION data/config/.current-version
fi

# If backend did not gracefully shutdown, PID lockfile remains; Remove lockfile
rm -f ./backend/4cat.pid

# Run migrate prior to setup (old builds pre 1.26 may not have config_manager)
python3 helper-scripts/migrate.py -y

# Run docker_setup to update any environment variables if they were changed
python3 docker/docker_setup.py

# Add a setting to identify this as a single Docker container
# Technically only need to do this once, but has to be done after docker_setup.py
python3 -c "import common.config_manager as config;config.set_or_create_setting('SINGLE_DOCKER', True, raw=False)"

# Start 4CAT backend
python3 4cat-daemon.py start

# Start 4CAT frontend
gunicorn --worker-tmp-dir /dev/shm --workers 2 --threads 4 --worker-class gthread --access-logfile /4cat/data/logs/access_gunicorn.log --log-level info --daemon --bind 0.0.0.0:80 webtool:app

# Tail logs and wait for SIGTERM
exec tail -f -n 3 data/logs/backend_4cat.log & wait $!
