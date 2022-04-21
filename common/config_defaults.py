"""
Default 4CAT Configuration Options

Possible options and their default values. Options are actually set in 4CAT"s
Database. Additional options can be defined in Datasources or Processors as
`config` objects.
"""
from common.lib.helpers import UserInput

defaults = {
    "DATASOURCES": {
        "type": UserInput.OPTION_TEXT,
        "default": {
            "bitchute": {},
            "custom": {},
            "douban": {},
            "customimport": {},
            "parler": {},
            "reddit": {
                "boards": "*",
            },
            "telegram": {},
            "twitterv2": {"id_lookup": False}
        },
        "help": "Data Sources object defining enabled datasources and their settings",
        "tooltip": "",
    },
    # Configure how the tool is to be named in its web interface. The backend will
    # always refer to "4CAT" - the name of the software, and a "powered by 4CAT"
    # notice may also show up in the web interface regardless of the value entered here.
    "4cat.name": {
        "type": UserInput.OPTION_TEXT,
        "default": "4CAT",
        "help": "Configure short name for the tool in its web interface.",
        "tooltip": "The backend will always refer to '4CAT' - the name of the software, and a 'powered by 4CAT' notice may also show up in the web interface regardless of the value entered here.",
    },
    "4cat.name_long": {
        "type": UserInput.OPTION_TEXT,
        "default": "4CAT: Capture and Analysis Toolkit",
        "help": "Configure long name for the tool in its web interface.",
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
        "help": "Path to file containing GitHub commit hash",
        "tooltip": "File containing a commit ID (everything after the first whitespace found is ignored)",
    },
    "4cat.github_url": {
        "type": UserInput.OPTION_TEXT,
        "default": "https://github.com/digitalmethodsinitiative/4cat",
        "help": "URL to the github repository for this 4CAT instance",
        "tooltip": "",
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
        "help": "Top Level datasets automatically deleted after a period of time",
        "tooltip": "0 will not expire",
    },
    "expire.allow_optout": {
        "type": UserInput.OPTION_TOGGLE,
        "default": True,
        "help": "Allow users to opt-out of automatic deletion",
        "tooltip": "Note that if users are allowed to opt out, data sources can still force the expiration of datasets created through that data source. This cannot be overridden by the user.",
    },
    "logging.slack.level": {
        "type": UserInput.OPTION_CHOICE,
        "default": "WARNING",
        "options": {"DEBUG": "Debug", "INFO": "Info", "WARNING": "Warning", "ERROR": "Error", "CRITICAL": "Critical"},
        "help": "Level of alerts (or higher) to be sent to Slack",
        "tooltip": "Only alerts above this level are sent to the Slack webhook",
    },
    "logging.slack.webhook": {
        "type": UserInput.OPTION_TEXT,
        "default": "",
        "help": "Slack callback URL to use for alerts",
    },
    "mail.admin_email": {
        "type": UserInput.OPTION_TEXT,
        "default": "",
        "help": "E-mail of admin, to send account requests etc to",
    },
    "mail.server": {
        "type": UserInput.OPTION_TEXT,
        "default": "localhost",
        "help": "SMTP server to connect to for sending e-mail alerts.",
        "tooltip": "",
    },
    "mail.ssl": {
        "type": UserInput.OPTION_TOGGLE,
        "default": False,
        "help": "Use SSL to connect to e-mail server?",
        "tooltip": "",
    },
    "mail.username": {
        "type": UserInput.OPTION_TEXT,
        "default": "",
        "help": "Mail Username",
        "tooltip": "Only if your SMTP server requires login",
    },
    "mail.password": {
        "type": UserInput.OPTION_TEXT,
        "default": "",
        "help": "Mail Password",
        "tooltip": "Only if your SMTP server requires login",
    },
    "mail.noreply": {
        "type": UserInput.OPTION_TEXT,
        "default": "noreply@localhost",
        "help": "NoReply Email Address",
        "tooltip": "",
    },
    # Scrape settings for data sources that contain their own scrapers
    "SCRAPE_TIMEOUT": {
        "type": UserInput.OPTION_TEXT,
        "default": "5",
        "help": "Wait time for scraping",
        "tooltip": "How long to wait for a scrape request to finish?",
    },
    # TODO: need to understand how code is using this for input so default can be formated correctly
    # SCRAPE_PROXIES = {"http": []}
    "SCRAPE_PROXIES": {
        "type": UserInput.OPTION_TEXT,
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
        "tooltip": "",
    },
    # Explorer settings
    # The maximum allowed amount of rows (prevents timeouts and memory errors)
    "explorer.max_posts": {
        "type": UserInput.OPTION_TEXT,
        "default": "100000",
        "help": "Maximum Explorer Posts",
        "tooltip": "The maximum allowed amount of rows (prevents timeouts and memory errors)",
    },
    # Web tool settings
    # These are used by the FlaskConfig class in config.py
    # Flask may require a restart to update them
    "FLASK_APP": {
        "type": UserInput.OPTION_TEXT,
        "default": "webtool/fourcat",
        "help": "Flask App Name",
        "tooltip": "",
    },
    "SERVER_NAME": {
        "type": UserInput.OPTION_TEXT,
        "default": "localhost",
        "help": "Server Name (e.g., my4CAT.com, localhost, 127.0.0.1)",
        "tooltip": "Default is localhost; For Docker PUBLIC_PORT is set in your .env file",
    },
    "HOSTNAME_WHITELIST": {
        "type": UserInput.OPTION_TEXT,
        "default": "['localhost']",
        "help": "Hostname Whitelist",
        "tooltip": "Docker should include localhost and Server Name",
    },
    "HOSTNAME_WHITELIST_API": {
        "type": UserInput.OPTION_TEXT,
        "default": "['localhost']",
        "help": "Hostname Whitelist for API",
        "tooltip": "Docker should include localhost and Server Name",
    },
    "SERVER_HTTPS": {
        "type": UserInput.OPTION_TOGGLE,
        "default": False,
        "help": "Sever HTTPS",
        "tooltip": "set to true to make 4CAT use 'https' in absolute URLs; DOES NOT CURRENTLY WORK WITH DOCKER SETUP",
    },
    "HOSTNAME_WHITELIST_NAME": {
        "type": UserInput.OPTION_TEXT,
        "default": "Automatic login",
        "help": "User Name for whitelisted hosts",
        "tooltip": "",
    },
    # YouTube variables to use for processors
    "api.youtube.name": {
        "type": UserInput.OPTION_TEXT,
        "default": "youtube",
        "help": "YouTube API Service Name",
        "tooltip": "",
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
        "help": "YouTube Developer Key",
        "tooltip": "",
    },
}
