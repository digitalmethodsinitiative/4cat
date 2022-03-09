# Add 'is_deactivated' column to user table
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "'/../..")
from common.lib.database import Database
from common.lib.logger import Logger

import common.config_manager as config
log = Logger(output=True)
db = Database(logger=log, dbname=config.get('DB_NAME'), user=config.get('DB_USER'), password=config.get('DB_PASSWORD'), host=config.get('DB_HOST'), port=config.get('DB_PORT'), appname="4cat-migrate")

print("  Checking if datasets table has a column 'is_private'...")
has_column = db.fetchone("SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'datasets' AND column_name = 'is_private'")
if has_column["num"] == 0:
    print("  ...No, adding.")
    db.execute("ALTER TABLE datasets ADD COLUMN is_private BOOLEAN DEFAULT TRUE")
    db.commit()

    # make existing datasets all non-private, as they were before
    db.execute("UPDATE datasets SET is_private = FALSE")
    db.commit()
else:
    print("  ...Yes, nothing to update.")

print("  Checking if datasets table has a column 'owner'...")
has_column = db.fetchone("SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'datasets' AND column_name = 'owner'")
if has_column["num"] == 0:
    print("  ...No, adding.")
    db.execute("ALTER TABLE datasets ADD COLUMN owner VARCHAR DEFAULT 'anonymous'")
    db.commit()

    # make existing datasets all non-private, as they were before
    db.execute("UPDATE datasets SET owner = parameters::json->>'user' WHERE parameters::json->>'user' IS NOT NULL")
    db.commit()
else:
    print("  ...Yes, nothing to update.")

print("  Checking if anonymous user exists...")
has_anon = db.fetchone("SELECT COUNT(*) AS num FROM users WHERE name = 'anonymous'")
if not has_anon["num"] > 0:
    print("  ...No, adding.")
    db.execute("INSERT INTO users (name, password) VALUES ('anonymous', '')")
    db.commit()


#DALE

#####################
# Processor Options #
#####################

# download_images.py
image_downloader.MAX_NUMBER_IMAGES
image_downloader_telegram.MAX_NUMBER_IMAGES
MAX_NUMBER_IMAGES = 1000

tumblr-search.TUMBLR_CONSUMER_KEY
# Tumblr API keys to use for data capturing
TUMBLR_CONSUMER_KEY = ""
TUMBLR_CONSUMER_SECRET_KEY = ""
TUMBLR_API_KEY = ""
TUMBLR_API_SECRET_KEY = ""

get-reddit-votes.REDDIT_API_CLIENTID
# Reddit API keys
REDDIT_API_CLIENTID = ""
REDDIT_API_SECRET = ""

tcat-auto-upload.TCAT_SERVER
# tcat_auto_upload.py
TCAT_SERVER = ''
TCAT_TOKEN = ''
TCAT_USERNAME = ''
TCAT_PASSWORD = ''

pix-plot.PIXPLOT_SERVER
# pix-plot.py
# If you host a version of https://github.com/digitalmethodsinitiative/dmi_pix_plot, you can use a processor to publish
# downloaded images into a PixPlot there
PIXPLOT_SERVER = ""



print("  Done!")
