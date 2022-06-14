#!/bin/sh
# wait-for-backend.sh

set -e

FILE=/usr/src/app/config/config.ini

until test -f "$FILE"; do
  >&2 echo "Backend has not started - sleeping"
  sleep 1
done

>&2 echo "Backend is up"
exec "$@"
