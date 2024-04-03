#!/bin/sh
# wait-for-backend.sh

set -e

until python3 -m docker.wait-for-backend; do
  >&2 echo "Backend has not started - sleeping"
  sleep 1
done

>&2 echo "Backend is up"

# Run migrate to ensure 4CAT is up to date if version file has changed
python3 -m helper-scripts.migrate.py -y --component frontend --current-version config/.current-version-frontend

# Default values for Gunicorn (if not provided by environment)
: "${worker_tmp_dir:=/dev/shm}"
: "${workers:=4}"
: "${threads:=4}"
: "${worker_class:=gthread}"
: "${log_level:=info}"

>&2 echo "Starting Gunicorn:"
exec `gunicorn --worker-tmp-dir $worker_tmp_dir --workers $workers --threads $threads --worker-class $worker_class --access-logfile /usr/src/app/logs/access_gunicorn.log --log-level $log_level --bind 0.0.0.0:5000 webtool:app`
