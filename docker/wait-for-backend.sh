#!/bin/sh
# wait-for-backend.sh

set -e

until python3 docker/wait-for-backend.py; do
  >&2 echo "Backend has not started - sleeping"
  sleep 1
done

>&2 echo "Backend is up"
exec "$@"
