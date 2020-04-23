#!/bin/sh
set -e

#set pg password for seeding
export PGPASSWORD=test

#seed db
cd /usr/src/app && psql --host=db --port=5432 --user=test --dbname=4cat < backend/database.sql

#generate password for admin user
admin_password=$(openssl rand -base64 12)

echo 'your admin password:'
echo $admin_password

python3 /usr/src/app/helper-scripts/create_user.py -u admin@admin.com -p $admin_password


# flask db upgrade
gunicorn --bind 0.0.0.0:5000 webtool:app
