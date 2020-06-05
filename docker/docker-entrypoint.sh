#!/bin/sh
set -e

if ! test -f "/usr/src/app/.tcat_created"; then

#generate password for admin user
admin_password=$(openssl rand -base64 12)

echo 'your admin password:'
echo $admin_password

#seed db
cd /usr/src/app && psql --host=db --port=5432 --user=test --dbname=4cat < backend/database.sql


python3 /usr/src/app/helper-scripts/create_user.py -u admin@admin.com -p $admin_password
echo $admin_password > /usr/src/app/.tcat_created

fi



#seed db
#set pg password for seeding
export PGPASSWORD=test

cd /usr/src/app && gunicorn --bind 0.0.0.0:5000 webtool:app
