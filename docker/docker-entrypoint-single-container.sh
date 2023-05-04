#!/bin/sh
set -e

exit_backend() {
  echo "Exiting backend..."
  python3 4cat-daemon.py stop
  echo "Exiting frontend..."
  python3 -c "from common.lib.helpers import get_parent_gunicorn_pid;import os;import signal;os.kill(get_parent_gunicorn_pid(), signal.SIGTERM)"

  echo "Exiting database..."
  POSTGRES_PID="$(head -1 "${PGDATA}/postmaster.pid")"
  if ps -p "$POSTGRES_PID" > /dev/null ; then
    if ! kill -INT "${POSTGRES_PID}" > /dev/null 2>&1; then
      echo "Unable to properly shutdown database (Could not send SIGTERM to process ${POSTGRES_PID})" >&2
    else
      echo "Database shutdown"
    fi
  else
    echo "Unable to properly shutdown database (Database not found running)"
  fi

  echo "Shutdown complete; Bye!"
  exit 0
}

trap exit_backend INT TERM

echo "Waiting for postgres..."
# Start postgresql
if [ ! -e "${FOURCAT_DATA}/logs" ] ; then mkdir "${FOURCAT_DATA}/logs" ; else : ; fi
# This is the entrypoint borrowed from Postgres's Docker image
/usr/local/bin/docker-entrypoint.sh postgres -D "${PGDATA}" > "${FOURCAT_DATA}/logs/postgresql.log" 2>&1 &

if ! [ -s "${PGDATA}/PG_VERSION" ]; then
  # First run; Postgres's docker-entrypoint.sh should be creating the database cluster
  echo "Database initializing (this may take a couple of minutes)..."
fi
# Wait for postgres server to start
while ! [ "$(pg_isready --host="$POSTGRES_HOST" --username="$POSTGRES_USER" --port=5432)" = "${POSTGRES_HOST}:5432 - accepting connections" ] ; do
  sleep 0.1
done
# Ensure the database has been created (first run will start the server and create the database)
while ! [ "$(psql --quiet --host="$POSTGRES_HOST" --port=5432 --user="$POSTGRES_USER" -XtAc "SELECT 1 FROM pg_database WHERE datname='${POSTGRES_DB}'")" ] ; do
  sleep 0.1
done
echo "PostgreSQL started"

# Create tables in 4CAT Database if it does not already exist
if [ "$(psql --quiet --host="$POSTGRES_HOST" --port=5432 --user="$POSTGRES_USER" --dbname="$POSTGRES_DB" -tAc "SELECT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'jobs')")" = 't' ]; then
  # Table already exists
  echo "Database already created"
else
  echo "Populating Database"
  # No database exists, build and seed
  psql --host="$POSTGRES_HOST" --port=5432 --user="$POSTGRES_USER" --dbname="$POSTGRES_DB" < backend/database.sql
  # Create .current-version file on new 4CAT instance
  if [ ! -e data/config ] ; then mkdir data/config ; else : ; fi && cp VERSION data/config/.current-version
fi

# If backend did not gracefully shutdown, PID lockfile remains; Remove lockfile
rm -f ./backend/4cat.pid

# Run migrate prior to setup (old builds pre 1.26 may not have config_manager)
python3 helper-scripts/migrate.py -y

# Run docker_setup to update any environment variables if they were changed
python3 -m docker.docker_setup

# Add a setting to identify this as a single Docker container
# Technically only need to do this once, but has to be done after docker_setup.py
python3 -c "import common.config_manager as config;config.set_or_create_setting('SINGLE_DOCKER', True, raw=False)"

# Start 4CAT backend
python3 4cat-daemon.py start

# Start 4CAT frontend
gunicorn --worker-tmp-dir /dev/shm --workers 2 --threads 4 --worker-class gthread --access-logfile "${FOURCAT_DATA}/logs/access_gunicorn.log" --log-level info --daemon --bind 0.0.0.0:80 webtool:app

# Tail logs and wait for SIGTERM
exec tail -f -n 3 "${FOURCAT_DATA}/logs/backend_4cat.log" & wait $!
