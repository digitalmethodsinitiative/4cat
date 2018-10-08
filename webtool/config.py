FLASK_APP = 'fourcat'
FLASK_DEBUG = True
DEBUG = True
SERVER_NAME='localhost:5000'
PATH_LOGS = '4cat-backend.log'

# Duplicate from backend/config.py - how to resolve this?
# Postgres login details
DB_HOST = "localhost"
DB_PORT = 5432
DB_USER = "fourcat"
DB_NAME = "fourcat"
DB_PASSWORD = "mosselm4n"

# Path to log file (may be rotated) and folder where images may be saved
PATH_LOGS = "4cat-backend.log"
PATH_IMAGES = "/images"

# What to scrape?
BOARDS = ["tg", "v"]