"""
Default 4CAT Configuration Options

Possible options and their default values. Options are actually set in 4CAT's
Database. Additional options can be defined in Datasources or Processors as
`config` objects.
"""
from common.lib.helpers import UserInput

defaults = {
    'DATASOURCES': {
        'type': UserInput.OPTION_TEXT,
        'default' : """{
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
        }""",
        'help': 'Data Sources object defining enabled datasources and their settings',
        'tooltip': "",
    },
    # Configure how the tool is to be named in its web interface. The backend will
    # always refer to '4CAT' - the name of the software, and a 'powered by 4CAT'
    # notice may also show up in the web interface regardless of the value entered here.
    'TOOL_NAME': {
        'type': UserInput.OPTION_TEXT,
        'default' : "4CAT",
        'help': 'Configure short name for the tool in its web interface.',
        'tooltip': "The backend will always refer to '4CAT' - the name of the software, and a 'powered by 4CAT' notice may also show up in the web interface regardless of the value entered here.",
    },
    'TOOL_NAME_LONG': {
        'type': UserInput.OPTION_TEXT,
        'default' : "4CAT: Capture and Analysis Toolkit",
        'help': 'Configure long name for the tool in its web interface.',
        'tooltip': "The backend will always refer to '4CAT' - the name of the software, and a 'powered by 4CAT' notice may also show up in the web interface regardless of the value entered here.",
    },
    # The following two options should be set to ensure that every analysis step can
    # be traced to a specific version of 4CAT. This allows for reproducible
    # research. You can however leave them empty with no ill effect. The version ID
    # should be a commit hash, which will be combined with the Github URL to offer
    # links to the exact version of 4CAT code that produced an analysis result.
    # If no version file is available, the output of "git show" in PATH_ROOT will be used
    # to determine the version, if possible.
    'PATH_VERSION': {
        'type': UserInput.OPTION_TEXT,
        'default' : ".git-checked-out",
        'help': 'Path to file containing GitHub commit hash',
        'tooltip': "File containing a commit ID (everything after the first whitespace found is ignored)",
    },
    'GITHUB_URL': {
        'type': UserInput.OPTION_TEXT,
        'default' : "https://github.com/digitalmethodsinitiative/4cat",
        'help': 'URL to the github repository for this 4CAT instance',
        'tooltip': "",
    },
    # These settings control whether top-level datasets (i.e. those created via the
    # 'Create dataset' page) are deleted automatically, and if so, after how much
    # time. You can also allow users to cancel this (i.e. opt out). Note that if
    # users are allowed to opt out, data sources can still force the expiration of
    # datasets created through that data source. This cannot be overridden by the
    # user.
    'EXPIRE_DATASETS': {
        'type': UserInput.OPTION_TEXT,
        'default' : '0',
        'help': 'Top Level datasets automatically deleted after a period of time',
        'tooltip': "0 will not expire",
    },
    'EXPIRE_ALLOW_OPTOUT': {
        'type': UserInput.OPTION_TOGGLE,
        'default' : True,
        'help': 'Allow users to opt-out of automatic deletion',
        'tooltip': "Note that if users are allowed to opt out, data sources can still force the expiration of datasets created through that data source. This cannot be overridden by the user.",
    },
    # Warning report configuration
    'WARN_INTERVAL': {
        'type': UserInput.OPTION_TEXT,
        'default' : '600',
        'help': 'Every so many seconds, compile a report of logged warnings and e-mail it to admins',
        'tooltip': "",
    },
    'WARN_LEVEL': {
        'type': UserInput.OPTION_TEXT,
        'default' : 'WARNING',
        'help': 'Level of alerts (or higher) to be sent',
        'tooltip': "Only alerts above this level are mailed: DEBUG/INFO/WARNING/ERROR/CRITICAL",
    },
    'WARN_SLACK_URL': {
        'type': UserInput.OPTION_TEXT,
        'default' : None,
        'help': 'Slack callback URL to use for alerts',
        'tooltip': "WARN_LEVEL (or higher) will be sent there immediately",
    },
    # E-mail settings
    # If your SMTP server requires login, define the MAIL_USERNAME and
    # MAIL_PASSWORD variables here additionally.
    'WARN_EMAILS': {
        'type': UserInput.OPTION_TEXT,
        'default' : '',
        'help': 'E-mail addresses to send warning reports to',
        'tooltip': "Separate with commas",
    },
    'ADMIN_EMAILS': {
        'type': UserInput.OPTION_TEXT,
        'default' : '',
        'help': 'E-mail of admins, to send account requests etc to',
        'tooltip': "Separate with commas",
    },
    'MAILHOST': {
        'type': UserInput.OPTION_TEXT,
        'default' : 'localhost',
        'help': 'SMTP server to connect to for sending e-mail alerts.',
        'tooltip': "",
    },
    'MAIL_SSL': {
        'type': UserInput.OPTION_TOGGLE,
        'default' : False,
        'help': 'Use SSL to connect to e-mail server?',
        'tooltip': "",
    },
    'MAIL_USERNAME': {
        'type': UserInput.OPTION_TEXT,
        'default' : '',
        'help': 'Mail Username',
        'tooltip': "Only if your SMTP server requires login",
    },
    'MAIL_PASSWORD': {
        'type': UserInput.OPTION_TEXT,
        'default' : '',
        'help': 'Mail Password',
        'tooltip': "Only if your SMTP server requires login",
    },
    'NOREPLY_EMAIL': {
        'type': UserInput.OPTION_TEXT,
        'default' : 'noreply@localhost',
        'help': 'NoReply Email Address',
        'tooltip': "",
    },
    # Scrape settings for data sources that contain their own scrapers
    'SCRAPE_TIMEOUT': {
        'type': UserInput.OPTION_TEXT,
        'default' : '5',
        'help': 'Wait time for scraping',
        'tooltip': "How long to wait for a scrape request to finish?",
    },
    # TODO: need to understand how code is using this for input so default can be formated correctly
    # SCRAPE_PROXIES = {"http": []}
    'SCRAPE_PROXIES': {
        'type': UserInput.OPTION_TEXT,
        'default' : '',
        'help': 'List scrape proxies',
        'tooltip': "Items in this list should be formatted like 'http://111.222.33.44:1234' and seperated by commas",
    },
    # TODO: I don't know what this actually does - Dale
    # Probably just timeout specific for images
    'IMAGE_INTERVAL': {
        'type': UserInput.OPTION_TEXT,
        'default' : '3600',
        'help': 'Image Interval',
        'tooltip': "",
    },
    # Explorer settings
    # The maximum allowed amount of rows (prevents timeouts and memory errors)
    'MAX_EXPLORER_POSTS': {
        'type': UserInput.OPTION_TEXT,
        'default' : '100000',
        'help': 'Maximum Explorer Posts',
        'tooltip': "The maximum allowed amount of rows (prevents timeouts and memory errors)",
    },
    # Web tool settings
    # These are used by the FlaskConfig class in config.py
    # Flask may require a restart to update them
    # TODO: additional options are currently in config_defaults.ini due to Docker
    'FLASK_APP': {
        'type': UserInput.OPTION_TEXT,
        'default' : 'webtool/fourcat',
        'help': 'Flask App Name',
        'tooltip': "",
    },
    'SERVER_HTTPS': {
        'type': UserInput.OPTION_TOGGLE,
        'default' : False,
        'help': 'Sever HTTPS',
        'tooltip': "set to true to make 4CAT use 'https' in absolute URLs; DOES NOT CURRENTLY WORK WITH DOCKER SETUP",
    },
    'HOSTNAME_WHITELIST_NAME': {
        'type': UserInput.OPTION_TEXT,
        'default' : "Automatic login",
        'help': 'User Name for whitelisted hosts',
        'tooltip': "",
    },
    # YouTube variables to use for processors
    'YOUTUBE_API_SERVICE_NAME': {
        'type': UserInput.OPTION_TEXT,
        'default' : "youtube",
        'help': 'YouTube API Service Name',
        'tooltip': "",
    },
    'YOUTUBE_API_VERSION': {
        'type': UserInput.OPTION_TEXT,
        'default' : "v3",
        'help': 'YouTube API Version',
        'tooltip': "e.g., 'v3'",
    },
    'YOUTUBE_DEVELOPER_KEY': {
        'type': UserInput.OPTION_TEXT,
        'default' : "",
        'help': 'YouTube Developer Key',
        'tooltip': "",
    },
}
