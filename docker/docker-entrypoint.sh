#!/bin/sh
set -e

exit_backend() {
  echo "Exiting backend"
  python3 4cat-daemon.py stop
  exit 0
}

trap exit_backend INT TERM

# Run docker_setup to update any environment variables if they were changed
python3 docker/docker_setup.py

echo "Waiting for postgres..."

while ! nc -z db 5432; do
  sleep 0.1
done

echo "PostgreSQL started"

# Check if DB exists and creates admin is it does not
user_created=false
# Check for "jobs" table
if [[ `psql --host=db --port=5432 --user=$POSTGRES_USER --dbname=$POSTGRES_DB -tAc "SELECT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'jobs')"` = 't' ]]; then
  # Table already exists
  echo "Database already created"
else
  echo 'Creating database'
  # Seed DB
  cd /usr/src/app && psql --host=db --port=5432 --user=$POSTGRES_USER --dbname=$POSTGRES_DB < backend/database.sql

  echo 'Generating admin user'
  # Generate password for admin user
  admin_password=$(openssl rand -base64 12)
  # Run python script to create new user
  python3 /usr/src/app/helper-scripts/create_user.py -u admin -e -p "$admin_password" -a
  echo 'Your admin username:' >> docker/shared/login.txt
  echo 'admin' >> docker/shared/login.txt
  echo 'Your admin password:' >> docker/shared/login.txt
  echo "$admin_password" >> docker/shared/login.txt
  user_created=true
  # Make admin an actual admin user
  psql --host=db --port=5432 --user=$POSTGRES_USER --dbname=$POSTGRES_DB -tAc "UPDATE users SET is_admin='t' WHERE name='admin'";
fi

echo 'Starting app'
cd /usr/src/app

# Inform user of admin password if created
if [ $user_created = true ] ; then
  echo '4CAT account information:'
  echo 'Your admin username:'
  echo 'admin'
  echo 'Your admin password:'
  echo "$admin_password"
  echo 'This information has been saved in your Docker 4cat_backend container'
  echo 'as login.txt'
  echo ''
fi

echo "4CAT is accessible at:"
echo "http://$SERVER_NAME:$PUBLIC_PORT"
echo ''

# If backend did not close in time, PID lockfile remains; Remove lockfile
rm -f ./backend/4cat.pid

# Start 4CAT backend
python3 4cat-daemon.py start

# Hang out until SIGTERM received
while true; do
    sleep 1
done
