""" 4CAT configuration """
import os

# Data source configuration
DATASOURCES = {
	"reddit": {
		"boards": ["europe", "politics"]
	},
	"tumblr": {
		"expire-datasets": 255600 # Delete all data after three days - required by the Tumblr API
	},
	"instagram": {},
	"telegram": {},
	"custom": {}
}

# Configure how the tool is to be named in its web interface. The backend will
# always refer to '4CAT' - the name of the software, and a 'powered by 4CAT'
# notice may also show up in the web interface regardless of the value entered here.
TOOL_NAME = "4CAT"
TOOL_NAME_LONG = "4CAT: Capture and Analysis Toolkit"

# Postgres login details
DB_HOST = "db"
DB_PORT = 5432
DB_USER = "fourcat"
DB_NAME = "fourcat"
DB_PASSWORD = "supers3cr3t"

# Path to folders where logs/images/data may be saved.
# Paths are relative to the folder this config file is in.
PATH_ROOT = os.path.abspath(os.path.dirname(__file__))  # better don't change this
PATH_LOGS = ""  # store logs here - empty means the 4CAT root folder
PATH_IMAGES = ""  # if left empty or pointing to a non-existent folder, no images will be saved
PATH_DATA = ""  # search results will be stored here as CSV files
PATH_LOCKFILE = "backend"  # the daemon lockfile will be saved in this folder. Probably no need to change!

# The following two options should be set to ensure that every analysis step can
# be traced to a specific version of 4CAT. This allows for reproducible
# research. You can however leave them empty with no ill effect. The version ID
# should be a commit hash, which will be combined with the Github URL to offer
# links to the exact version of 4CAT code that produced an analysis result.
PATH_VERSION = ""  # file containing a commit ID (everything after the first whitespace found is ignored)
GITHUB_URL = "https://github.com/guidoajansen/4cat"  # URL to the github repository for this 4CAT instance

# 4CAT has an API (available from localhost) that can be used for monitoring
# and will listen for requests on the following port. "0" disables the API.
API_PORT = 4444

# 4CAT can anonymise author names in results and does so using a hashed version
# of the author name + a salt. The salt should be defined here. This should be
# a random string; in Python you can generate one with e.g. bcrypt.gensalt()
# You need to set this before running 4CAT. 4CAT will refuse to run if this is
# left at its default value.
ANONYMISATION_SALT = "4g^j%_4!edrme8nge&s5=^v2t)2&vfw)0!##y8f)qjk3oimj)@"

# Warning report configuration
WARN_INTERVAL = 600  # every so many seconds, compile a report of logged warnings and e-mail it to admins
WARN_LEVEL = "WARNING"  # only alerts above this level are mailed: DEBUG/INFO/WARNING/ERROR/CRITICAL
WARN_SLACK_URL = ""  # A Slack callback URL may be entered here; any warnings equal to or above
				     # WARN_LEVEL will be sent there immediately

# E-mail settings
WARN_EMAILS = []  # e-mail addresses to send warning reports to
ADMIN_EMAILS = ["g.a.jansen@uva.nl"]  # e-mail of admins, to send account requests etc to
MAILHOST = "localhost"  # SMTP server to connect to for sending e-mail alerts

# Scrape settings for data sources that contain their own scrapers
SCRAPE_TIMEOUT = 5  # how long to wait for a scrape request to finish?
SCRAPE_PROXIES = {"http": []}  # Items in this list should be formatted like "http://111.222.33.44:1234"
IMAGE_INTERVAL = 3600

# YouTube variables to use for processors
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"
YOUTUBE_DEVELOPER_KEY = ""

# Tumblr API keys to use for data capturing
TUMBLR_CONSUMER_KEY = ""
TUMBLR_CONSUMER_SECRET_KEY = ""
TUMBLR_API_KEY = ""
TUMBLR_API_SECRET_KEY = ""

# Reddit API keys
REDDIT_API_CLIENTID = ""
REDDIT_API_SECRET = ""

# Web tool settings
class FlaskConfig:
	FLASK_APP = 'webtool/fourcat'
	SECRET_KEY = "4g^j%_4!edrme8nge&s5=^v2t)2&vfw)0!##y8f)qjk3oimj)@"
	SERVER_NAME = 'localhost:5000'
	SERVER_HTTPS = False  # set to true to make 4CAT use "https" in absolute URLs
	HOSTNAME_WHITELIST = ["localhost"]  # only these may access the web tool; "*" or an empty list matches everything
	HOSTNAME_WHITELIST_API = ["localhost"]  # hostnames matching these are exempt from rate limiting
	HOSTNAME_WHITELIST_NAME = "Automatic login"
