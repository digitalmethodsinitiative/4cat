#!/bin/sh
# wait-for-backend.sh

set -e

until python3 -m docker.wait-for-backend; do
  >&2 echo "Backend has not started - sleeping"
  sleep 1
done

>&2 echo "Backend is up"
sleep 2
exec "$@"
