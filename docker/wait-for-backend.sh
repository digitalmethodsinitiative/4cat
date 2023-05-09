#!/bin/sh
# wait-for-backend.sh

set -e

# Ensure config.ini is created (backend will create on first run)
while [ ! -e "${FOURCAT_DATA}/config/config.ini" ] ; do
  sleep 0.1
done

# Use 4CAT internal API to check for 4CAT backend
until python3 -m docker.wait-for-backend; do
  >&2 echo "Backend has not started - sleeping"
  sleep 1
done

>&2 echo "Backend is up"
exec "$@"
