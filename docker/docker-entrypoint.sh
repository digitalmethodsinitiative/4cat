#!/bin/sh
set -e

export PGPASSWORD=test

cd /usr/src/app && psql --host=db --port=5432 --user=test --dbname=4cat < backend/database.sql
# flask db upgrade
gunicorn --bind 0.0.0.0:5000 webtool:app
