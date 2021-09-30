""" 4CAT configuration """
import os
import yaml
import configparser

with open('config.yml') as file:
    config_data = yaml.load(file, Loader=yaml.FullLoader)

DOCKER_CONFIG_FILE = 'docker/shared/docker_config.ini'

# Data source configuration
DATASOURCES = config_data.get('DATASOURCES')

# Configure how the tool is to be named in its web interface. The backend will
# always refer to '4CAT' - the name of the software, and a 'powered by 4CAT'
# notice may also show up in the web interface regardless of the value entered here.
TOOL_NAME = config_data.get('TOOL_NAME')
TOOL_NAME_LONG = config_data.get('TOOL_NAME_LONG')

# Postgres login details
DB_HOST = config_data.get('DB_HOST')
DB_PORT = config_data.get('DB_PORT')
DB_USER = config_data.get('DB_USER')
DB_NAME = config_data.get('DB_NAME')
DB_PASSWORD = config_data.get('DB_PASSWORD')

# Path to folders where logs/images/data may be saved.
# Paths are relative to the folder this config file is in.
PATH_ROOT = os.path.abspath(os.path.dirname(__file__))  # better don't change this
PATH_LOGS = config_data.get('PATH_LOGS')  # store logs here - empty means the 4CAT root folder
PATH_IMAGES = config_data.get('PATH_IMAGES')  # if left empty or pointing to a non-existent folder, no images will be saved
PATH_DATA = config_data.get('PATH_DATA')  # search results will be stored here as CSV files
PATH_LOCKFILE = config_data.get('PATH_LOCKFILE')  # the daemon lockfile will be saved in this folder. Probably no need to change!
PATH_SESSIONS = config_data.get('PATH_SESSIONS') # folder where API session data is stored (e.g., Telegram)

# The following two options should be set to ensure that every analysis step can
# be traced to a specific version of 4CAT. This allows for reproducible
# research. You can however leave them empty with no ill effect. The version ID
# should be a commit hash, which will be combined with the Github URL to offer
# links to the exact version of 4CAT code that produced an analysis result.
# If no version file is available, the output of "git show" in PATH_ROOT will be used
# to determine the version, if possible.
PATH_VERSION = config_data.get('PATH_VERSION')  # file containing a commit ID (everything after the first whitespace found is ignored)
GITHUB_URL = config_data.get('GITHUB_URL')  # URL to the github repository for this 4CAT instance

# 4CAT has an API (available from localhost) that can be used for monitoring
# and will listen for requests on the following port. "0" disables the API.
API_HOST = config_data.get('API_HOST')
API_PORT = config_data.get('API_PORT')

# 4CAT can anonymise author names in results and does so using a hashed version
# of the author name + a salt. The salt should be defined here. This should be
# a random string; in Python you can generate one with e.g. bcrypt.gensalt()
# You need to set this before running 4CAT. 4CAT will refuse to run if this is
# left at its default value.
ANONYMISATION_SALT = config_data.get('ANONYMISATION_SALT')

# Warning report configuration
WARN_INTERVAL = config_data.get('WARN_INTERVAL')  # every so many seconds, compile a report of logged warnings and e-mail it to admins
WARN_LEVEL = config_data.get('WARN_LEVEL')  # only alerts above this level are mailed: DEBUG/INFO/WARNING/ERROR/CRITICAL
WARN_SLACK_URL = config_data.get('WARN_SLACK_URL')  # A Slack callback URL may be entered here; any warnings equal to or above
				     # WARN_LEVEL will be sent there immediately

# E-mail settings
# If your SMTP server requires login, define the MAIL_USERNAME and
# MAIL_PASSWORD variables here additionally.
WARN_EMAILS = config_data.get('WARN_EMAILS')  # e-mail addresses to send warning reports to
ADMIN_EMAILS = config_data.get('ADMIN_EMAILS')  # e-mail of admins, to send account requests etc to
MAILHOST = config_data.get('MAILHOST') # SMTP server to connect to for sending e-mail alerts.
MAIL_SSL = config_data.get('MAIL_SSL')  # use SSL to connect to e-mail server?
MAIL_USERNAME = config_data.get('MAIL_USERNAME')
MAIL_PASSWORD = config_data.get('MAIL_PASSWORD')
NOREPLY_EMAIL = config_data.get('NOREPLY_EMAIL')


# Scrape settings for data sources that contain their own scrapers
SCRAPE_TIMEOUT = config_data.get('SCRAPE_TIMEOUT')  # how long to wait for a scrape request to finish?
SCRAPE_PROXIES = config_data.get('SCRAPE_PROXIES')  # Items in this list should be formatted like "http://111.222.33.44:1234"
IMAGE_INTERVAL = config_data.get('IMAGE_INTERVAL')

# YouTube variables to use for processors
YOUTUBE_API_SERVICE_NAME = config_data.get('YOUTUBE_API_SERVICE_NAME')
YOUTUBE_API_VERSION = config_data.get('YOUTUBE_API_VERSION')
YOUTUBE_DEVELOPER_KEY = config_data.get('YOUTUBE_DEVELOPER_KEY')

# Tumblr API keys to use for data capturing
TUMBLR_CONSUMER_KEY = config_data.get('TUMBLR_CONSUMER_KEY')
TUMBLR_CONSUMER_SECRET_KEY = config_data.get('TUMBLR_CONSUMER_SECRET_KEY')
TUMBLR_API_KEY = config_data.get('TUMBLR_API_KEY')
TUMBLR_API_SECRET_KEY = config_data.get('TUMBLR_API_SECRET_KEY')

# Reddit API keys
REDDIT_API_CLIENTID = config_data.get('REDDIT_API_CLIENTID')
REDDIT_API_SECRET = config_data.get('REDDIT_API_SECRET')

# PixPlot Server
# If you host a version of https://github.com/digitalmethodsinitiative/dmi_pix_plot, you can use a processor to publish
# downloaded images into a PixPlot there
PIXPLOT_SERVER = config_data.get('PIXPLOT_SERVER')

# Web tool settings
class FlaskConfig:
    FLASK_APP = config_data.get('FLASK_APP')
    SECRET_KEY = config_data.get('SECRET_KEY')
    SERVER_NAME = config_data.get('SERVER_NAME') # if using a port other than 80, change to localhost:specific_port
    SERVER_HTTPS = config_data.get('SERVER_HTTPS')  # set to true to make 4CAT use "https" in absolute URLs
    HOSTNAME_WHITELIST = config_data.get('HOSTNAME_WHITELIST')  # only these may access the web tool; "*" or an empty list matches everything
    HOSTNAME_WHITELIST_API = config_data.get('HOSTNAME_WHITELIST_API')  # hostnames matching these are exempt from rate limiting
    HOSTNAME_WHITELIST_NAME = config_data.get('HOSTNAME_WHITELIST_NAME')


##########
# DOCKER #
##########
# Docker setup requires matching configuration for the following values

# These values will overwrite anything set previously in this config and
# originate from the .env file or the docker_config.ini file

if os.path.exists(DOCKER_CONFIG_FILE):
  config = configparser.ConfigParser()
  config.read(DOCKER_CONFIG_FILE)
  if config['DOCKER'].getboolean('use_docker_config'):
      # can be your server url or ip
      your_server = config['SERVER'].get('server_name', 'localhost')

      DB_HOST = config['DATABASE'].get('db_host')
      DB_PORT = config['DATABASE'].getint('db_port')
      DB_USER = config['DATABASE'].get('db_user')
      DB_NAME = config['DATABASE'].get('db_name')
      DB_PASSWORD = config['DATABASE'].get('db_password')

      API_HOST = config['API'].get('api_host')
      API_PORT = config['API'].getint('api_port')

      PATH_ROOT = os.path.abspath(os.path.dirname(__file__))  # better don't change this
      PATH_LOGS = config['PATHS'].get('path_logs', "")
      PATH_IMAGES = config['PATHS'].get('path_images', "")
      PATH_DATA = config['PATHS'].get('path_data', "")
      PATH_LOCKFILE = config['PATHS'].get('path_lockfile', "")
      PATH_SESSIONS = config['PATHS'].get('path_sessions', "")

      ANONYMISATION_SALT = config['GENERATE'].get('anonymisation_salt')

      class FlaskConfig:
          FLASK_APP = 'webtool/fourcat'
          SECRET_KEY = config['GENERATE'].get('secret_key')
          if config['SERVER'].getint('public_port') == 80:
              SERVER_NAME = your_server
          else:
              SERVER_NAME = f"{your_server}:{config['SERVER'].get('public_port')}"
          SERVER_HTTPS = False  # set to true to make 4CAT use "https" in absolute URLs; DOES NOT CURRENTLY WORK WITH DOCKER SETUP
          HOSTNAME_WHITELIST = ["localhost", your_server]  # only these may access the web tool; "*" or an empty list matches everything
          HOSTNAME_WHITELIST_API = ["localhost", your_server]  # hostnames matching these are exempt from rate limiting
          HOSTNAME_WHITELIST_NAME = "Automatic login"
