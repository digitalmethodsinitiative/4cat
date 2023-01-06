"""
Default 4CAT Configuration Options

Possible options and their default values. Options are actually set in 4CAT"s
Database. Additional options can be defined in Datasources or Processors as
`config` objects.
"""
from common.lib.helpers import UserInput
import json

config_definition = {
    "4cat.datasources": {
        "type": UserInput.OPTION_TEXT_JSON,
        "default": json.dumps(["bitchute", "custom", "douban", "customimport", "reddit", "telegram", "twitterv2"]),
        "help": "Data Sources",
        "tooltip": "A list of enabled data sources that people can choose from when creating a dataset page. It is "
                   "recommended to manage this via the 'Data sources' button in the Control Panel."
    },
    # Configure how the tool is to be named in its web interface. The backend will
    # always refer to "4CAT" - the name of the software, and a "powered by 4CAT"
    # notice may also show up in the web interface regardless of the value entered here.
    "4cat.name": {
        "type": UserInput.OPTION_TEXT,
        "default": "4CAT",
        "help": "Short tool name",
        "tooltip": "Configure short name for the tool in its web interface. The backend will always refer to '4CAT' - the name of the software, and a 'powered by 4CAT' notice may also show up in the web interface regardless of the value entered here.",
    },
    "4cat.name_long": {
        "type": UserInput.OPTION_TEXT,
        "default": "4CAT: Capture and Analysis Toolkit",
        "help": "Full tool name",
        "tooltip": "The backend will always refer to '4CAT' - the name of the software, and a 'powered by 4CAT' notice may also show up in the web interface regardless of the value entered here.",
    },
    # The following two options should be set to ensure that every analysis step can
    # be traced to a specific version of 4CAT. This allows for reproducible
    # research. You can however leave them empty with no ill effect. The version ID
    # should be a commit hash, which will be combined with the Github URL to offer
    # links to the exact version of 4CAT code that produced an analysis result.
    # If no version file is available, the output of "git show" in PATH_ROOT will be used
    # to determine the version, if possible.
    "path.versionfile": {
        "type": UserInput.OPTION_TEXT,
        "default": ".git-checked-out",
        "help": "Version file",
        "tooltip": "Path to file containing GitHub commit hash. File containing a commit ID (everything after the first whitespace found is ignored)",
    },
    "4cat.github_url": {
        "type": UserInput.OPTION_TEXT,
        "default": "https://github.com/digitalmethodsinitiative/4cat",
        "help": "Repository URL",
        "tooltip": "URL to the github repository for this 4CAT instance",
    },
    # These settings control whether top-level datasets (i.e. those created via the
    # "Create dataset" page) are deleted automatically, and if so, after how much
    # time. You can also allow users to cancel this (i.e. opt out). Note that if
    # users are allowed to opt out, data sources can still force the expiration of
    # datasets created through that data source. This cannot be overridden by the
    # user.
    "expire.timeout": {
        "type": UserInput.OPTION_TEXT,
        "default": "0",
        "coerce_type": int,
        "help": "Expiration timeout",
        "tooltip": "Top Level datasets automatically deleted after a period of time. 0 will not expire",
    },
    "expire.allow_optout": {
        "type": UserInput.OPTION_TOGGLE,
        "default": True,
        "help": "Allow opt-out",
        "tooltip": "Allow users to opt-out of automatic deletion. Note that if users are allowed to opt out, data "
                   "sources can still force the expiration of datasets created through that data source. This cannot "
                   "be overridden by the user.",
    },
    "expire.datasources": {
        "type": UserInput.OPTION_TEXT_JSON,
        "default": "{}",
        "help": "Data source-specific expiration",
        "tooltip": "Allows setting expiration settings per datasource. This always overrides the above settings. It is "
                   "recommended to manage this via the 'Data sources' button in the Control Panel."
    },
    "logging.slack.level": {
        "type": UserInput.OPTION_CHOICE,
        "default": "WARNING",
        "options": {"DEBUG": "Debug", "INFO": "Info", "WARNING": "Warning", "ERROR": "Error", "CRITICAL": "Critical"},
        "help": "Slack alert level",
        "tooltip": "Level of alerts (or higher) to be sent to Slack. Only alerts above this level are sent to the Slack webhook",
    },
    "logging.slack.webhook": {
        "type": UserInput.OPTION_TEXT,
        "default": "",
        "help": "Slack webhook URL",
        "tooltip": "Slack callback URL to use for alerts",
    },
    "mail.admin_email": {
        "type": UserInput.OPTION_TEXT,
        "default": "",
        "help": "Admin e-mail",
        "tooltip": "E-mail of admin, to send account requests etc to",
    },
    "mail.server": {
        "type": UserInput.OPTION_TEXT,
        "default": "localhost",
        "help": "SMTP server",
        "tooltip": "SMTP server to connect to for sending e-mail alerts.",
    },
    "mail.port": {
        "type": UserInput.OPTION_TEXT,
        "default": "0",
        "coerce_type": int,
        "help": "SMTP port",
        "tooltip": 'SMTP port to connect to for sending e-mail alerts. "0" defaults to "465" for SMTP_SSL or OS default for SMTP.',
    },
    "mail.ssl": {
        "type": UserInput.OPTION_CHOICE,
        "default": "ssl",
        "options": {"ssl": "SSL", "tls": "TLS", "none": "None"},
        "help": "SMTP over SSL, TLS, or None",
        "tooltip": "Security to use to connect to e-mail server",
    },
    "mail.username": {
        "type": UserInput.OPTION_TEXT,
        "default": "",
        "help": "SMTP Username",
        "tooltip": "Only if your SMTP server requires login",
    },
    "mail.password": {
        "type": UserInput.OPTION_TEXT,
        "default": "",
        "help": "SMTP Password",
        "tooltip": "Only if your SMTP server requires login",
    },
    "mail.noreply": {
        "type": UserInput.OPTION_TEXT,
        "default": "noreply@localhost",
        "help": "NoReply e-mail"
    },
    # Scrape settings for data sources that contain their own scrapers
    "SCRAPE_TIMEOUT": {
        "type": UserInput.OPTION_TEXT,
        "default": "5",
        "help": "Wait time for scraping",
        "coerce_type": int,
        "tooltip": "How long to wait for a scrape request to finish?",
    },
    # TODO: need to understand how code is using this for input so default can be formated correctly
    # SCRAPE_PROXIES = {"http": []}
    "SCRAPE_PROXIES": {
        "type": UserInput.OPTION_TEXT_JSON,
        "default": "",
        "help": "List scrape proxies",
        "tooltip": "Items in this list should be formatted like 'http://111.222.33.44:1234' and seperated by commas",
    },
    # TODO: I don"t know what this actually does - Dale
    # Probably just timeout specific for images
    "IMAGE_INTERVAL": {
        "type": UserInput.OPTION_TEXT,
        "default": "3600",
        "help": "Image Interval",
        "coerce_type": int,
        "tooltip": "",
    },
    # Explorer settings
    # The maximum allowed amount of rows (prevents timeouts and memory errors)
    "explorer.max_posts": {
        "type": UserInput.OPTION_TEXT,
        "default": "100000",
        "help": "Amount of posts",
        "coerce_type": int,
        "tooltip": "Amount of posts to show in Explorer. The maximum allowed amount of rows (prevents timeouts and "
                   "memory errors)",
    },
    "explorer.posts_per_page": {
        "type": UserInput.OPTION_TEXT,
        "default": 50,
        "help": "Posts per page",
        "coerce_type": int,
        "tooltip": "Posts to display per page",
    },
    # Web tool settings
    # These are used by the FlaskConfig class in config.py
    # Flask may require a restart to update them
    "flask.flask_app": {
        "type": UserInput.OPTION_TEXT,
        "default": "webtool/fourcat",
        "help": "Flask App Name",
        "tooltip": "",
    },
    "flask.server_name": {
        "type": UserInput.OPTION_TEXT,
        "default": "localhost",
        "help": "Host name",
        "tooltip": "e.g., my4CAT.com, localhost, 127.0.0.1. Default is localhost; when running 4CAT in Docker this "
                   "setting is ignored as any domain/port binding should be handled outside of the Docker container"
                   "; the Docker container itself will serve on any domain name on the port configured in the .env "
                   "file."
    },
    "flask.autologin.hostnames": {
        "type": UserInput.OPTION_TEXT_JSON,
        "default": '["localhost"]',
        "help": "White-listed hostnames",
        "tooltip": "A list of host names or IP addresses to automatically log in. Docker should include localhost and Server Name",
    },
    "flask.autologin.api": {
        "type": UserInput.OPTION_TEXT_JSON,
        "default": '["localhost"]',
        "help": "White-list for API",
        "tooltip": "A list of host names or IP addresses to allow access to API endpoints with no rate limiting. Docker should include localhost and Server Name",
    },
    "flask.https": {
        "type": UserInput.OPTION_TOGGLE,
        "default": False,
        "help": "Use HTTPS",
        "tooltip": "Enable to make 4CAT use 'https' in absolute URLs; DOES NOT CURRENTLY WORK WITH DOCKER SETUP",
    },
    "flask.autologin.name": {
        "type": UserInput.OPTION_TEXT,
        "default": "Automatic login",
        "help": "Auto-login name",
        "tooltip": "Username for whitelisted hosts (automatically logged in users see this name for themselves)",
    },
    "flask.secret_key": {
        "type": UserInput.OPTION_TEXT,
        "default": "",
        "help": "Secret key",
        "tooltip": "Secret key for Flask, used for session cookies",
    },
    # YouTube variables to use for processors
    "api.youtube.name": {
        "type": UserInput.OPTION_TEXT,
        "default": "youtube",
        "help": "YouTube API Service",
        "tooltip": "YouTube API 'service name', e.g. youtube, googleapis, etc.",
    },
    "api.youtube.version": {
        "type": UserInput.OPTION_TEXT,
        "default": "v3",
        "help": "YouTube API Version",
        "tooltip": "e.g., ''v3'",
    },
    "api.youtube.key": {
        "type": UserInput.OPTION_TEXT,
        "default": "",
        "help": "YouTube API Key",
        "tooltip": "The developer key from your API console",
    },
}

categories = {
    "4cat": "4CAT Tool settings",
    "api": "API credentials",
    "flask": "Flask settings",
    "explorer": "Data Explorer settings",
    "expire": "Dataset expiration settings",
    "mail": "Mail settings & credentials",
    "logging": "Logging settings",
    "path": "File paths",
    "image_downloader": "Image Download Settings",
    "video_downloader": "Video Download Settings",
    'text_from_images': 'OCR: Extract text from images (https://github.com/digitalmethodsinitiative/ocr_server)',
}
