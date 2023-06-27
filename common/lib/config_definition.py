"""
Default 4CAT Configuration Options

Possible options and their default values. Options are actually set in 4CAT"s
Database. Additional options can be defined in Data sources or Processors as
`config` objects.
"""
from common.lib.user_input import UserInput
import json

config_definition = {
    "4cat.datasources": {
        "type": UserInput.OPTION_TEXT_JSON,
        "default": ["bitchute", "custom", "douban", "customimport", "telegram", "instagram", "tiktok", "twitter",
                    "imgur", "parler", "douyin", "linkedin", "ninegag"],
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
        "tooltip": "Configure short name for the tool in its web interface. The backend will always refer to '4CAT' - "
                   "the name of the software, and a 'powered by 4CAT' notice may also show up in the web interface "
                   "regardless of the value entered here."
    },
    "4cat.name_long": {
        "type": UserInput.OPTION_TEXT,
        "default": "4CAT: Capture and Analysis Toolkit",
        "help": "Full tool name",
        "tooltip": "Used in e.g. the interface header. The backend will always refer to '4CAT' - the name of the "
                   "software, and a 'powered by 4CAT' notice may also show up in the web interface regardless of the "
                   "value entered here."
    },
    "4cat.crash_message": {
        "type": UserInput.OPTION_TEXT_LARGE,
        "default": "This processor has crashed; the crash has been logged. 4CAT will try again when it is restarted. "
                   "Contact your server administrator if this error persists. You can also report issues via 4CAT's "
                   "[GitHub repository](https://github.com/digitalmethodsinitiative/4cat/issues).",
        "help": "Crash message",
        "tooltip": "This message is shown to users in the interface when a processor crashes while processing their "
                   "dataset. It can contain Markdown markup."
    },
    # privileges
    "privileges.can_create_dataset": {
        "type": UserInput.OPTION_TOGGLE,
        "default": True,
        "help": "Can create dataset",
        "tooltip": "Controls whether users can view and use the 'Create dataset' page. Does NOT control whether "
                   "users can run processors (which also create datasets); this is a separate setting."
    },
    "privileges.can_run_processors": {
        "type": UserInput.OPTION_TOGGLE,
        "default": True,
        "help": "Can run processors",
        "tooltip": "Controls whether processors can be run. There may be processor-specific settings or dependencies "
                   "that override this."
    },
    "privileges.can_view_all_datasets": {
        "type": UserInput.OPTION_TOGGLE,
        "default": False,
        "help": "Can view global dataset index",
        "tooltip": "Controls whether users can see the global datasets overview, i.e. not just for their own user but "
                   "for all other users as well."
    },
    "privileges.can_view_private_datasets": {
        "type": UserInput.OPTION_TOGGLE,
        "default": False,
        "help": "Can view global dataset index",
        "tooltip": "Controls whether users can see the datasets made private by their owners."
    },
    "privileges.can_create_api_token": {
        "type": UserInput.OPTION_TOGGLE,
        "default": True,
        "help": "Can create API token",
        "tooltip": "Controls whether users can create a token for authentication with 4CAT's Web API."
    },
    "privileges.can_rerun_dataset": {
        "type": UserInput.OPTION_TOGGLE,
        "default": True,
        "help": "Can re-run processors",
        "tooltip": "Controls whether users can re-run datasets they own, i.e. run the parent processor again with the "
                   "same parameters, replacing the original dataset."
    },
    "privileges.can_use_explorer": {
        "type": UserInput.OPTION_TOGGLE,
        "default": True,
        "help": "Can use explorer",
        "tooltip": "Controls whether users can use the Explorer feature to navigate datasets."
    },
    "privileges.admin.can_manage_users": {
        "type": UserInput.OPTION_TOGGLE,
        "default": False,
        "help": "Can manage users",
        "tooltip": "Controls whether users can add, edit and delete other users via the Control Panel"
    },
    "privileges.admin.can_manage_notifications": {
        "type": UserInput.OPTION_TOGGLE,
        "default": False,
        "help": "Can manage users",
        "tooltip": "Controls whether users can add, edit and delete notifications via the Control Panel"
    },
    "privileges.admin.can_manage_settings": {
        "type": UserInput.OPTION_TOGGLE,
        "default": False,
        "help": "Can manage settings",
        "tooltip": "Controls whether users can manipulate 4CAT settings via the Control Panel"
    },
    "privileges.admin.can_manage_datasources": {
        "type": UserInput.OPTION_TOGGLE,
        "default": False,
        "help": "Can manage data sources",
        "tooltip": "Controls whether users can manipulate data source availability via the Control Panel"
    },
    "privileges.admin.can_restart": {
        "type": UserInput.OPTION_TOGGLE,
        "default": False,
        "help": "Can restart/upgrade",
        "tooltip": "Controls whether users can restart and upgrade 4CAT via the Control Panel"
    },
    "privileges.admin.can_manage_tags": {
        "type": UserInput.OPTION_TOGGLE,
        "default": False,
        "help": "Can manage user tags",
        "tooltip": "Controls whether users can manipulate user tags via the Control Panel"
    },
    "privileges.admin.can_view_status": {
        "type": UserInput.OPTION_TOGGLE,
        "default": False,
        "help": "Can view worker status",
        "tooltip": "Controls whether users can view worker status via the Control Panel"
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
        "global": True
    },
    "4cat.github_url": {
        "type": UserInput.OPTION_TEXT,
        "default": "https://github.com/digitalmethodsinitiative/4cat",
        "help": "Repository URL",
        "tooltip": "URL to the github repository for this 4CAT instance",
        "global": True
    },
    "4cat.phone_home_url": {
        "type": UserInput.OPTION_TEXT,
        "default": "https://ping.4cat.nl",
        "help": "Phone home URL",
        "tooltip": "This URL is called once - when 4CAT is installed. If the installing user consents, information "
                   "is sent to this URL to help the 4CAT developers (the Digital Methods Initiative) keep track of how "
                   "much it is used. There should be no need to change this URL after installation.",
        "global": True
    },
    "4cat.phone_home_asked": {
        "type": UserInput.OPTION_TOGGLE,
        "default": False,
        "help": "Shown phone home request?",
        "tooltip": "Whether you've seen the 'phone home request'. Set to `false` to see the request again. There "
                   "should be no need to change this manually.",
        "global": True
    },
    "4cat.layout_hue": {
        "type": UserInput.OPTION_HUE,
        "default": 356,
        "help": "Interface accent colour",
        "saturation": 87,
        "value": 81,
        "update_layout": True,
        "min": 0,
        "max": 360,
        "coerce_type": int
    },
    "4cat.allow_access_request": {
        "type": UserInput.OPTION_TOGGLE,
        "default": True,
        "help": "Allow access requests",
        "tooltip": "When enabled, users can request a 4CAT account via the login page if they do not have one, "
                   "provided e-mail settings are configured."
    },
    # These settings control whether top-level datasets (i.e. those created via the
    # "Create dataset" page) are deleted automatically, and if so, after how much
    # time. You can also allow users to cancel this (i.e. opt out). Note that if
    # users are allowed to opt out, data sources can still force the expiration of
    # datasets created through that data source. This cannot be overridden by the
    # user.
    "expire.timeout": {
        "type": UserInput.OPTION_TEXT,
        "default": 0,
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
        "default": {},
        "help": "Data source-specific expiration",
        "tooltip": "Allows setting expiration settings per datasource. This always overrides the above settings. It is "
                   "recommended to manage this via the 'Data sources' button in the Control Panel.",
    },
    "logging.slack.level": {
        "type": UserInput.OPTION_CHOICE,
        "default": "WARNING",
        "options": {"DEBUG": "Debug", "INFO": "Info", "WARNING": "Warning", "ERROR": "Error", "CRITICAL": "Critical"},
        "help": "Slack alert level",
        "tooltip": "Level of alerts (or higher) to be sent to Slack. Only alerts above this level are sent to the Slack webhook",
        "global": True
    },
    "logging.slack.webhook": {
        "type": UserInput.OPTION_TEXT,
        "default": "",
        "help": "Slack webhook URL",
        "tooltip": "Slack callback URL to use for alerts",
        "global": True
    },
    "mail.admin_email": {
        "type": UserInput.OPTION_TEXT,
        "default": "",
        "help": "Admin e-mail",
        "tooltip": "E-mail of admin, to send account requests etc to",
        "global": True
    },
    "mail.server": {
        "type": UserInput.OPTION_TEXT,
        "default": "localhost",
        "help": "SMTP server",
        "tooltip": "SMTP server to connect to for sending e-mail alerts.",
        "global": True
    },
    "mail.port": {
        "type": UserInput.OPTION_TEXT,
        "default": "0",
        "coerce_type": int,
        "help": "SMTP port",
        "tooltip": 'SMTP port to connect to for sending e-mail alerts. "0" defaults to "465" for SMTP_SSL or OS default for SMTP.',
        "global": True
    },
    "mail.ssl": {
        "type": UserInput.OPTION_CHOICE,
        "default": "ssl",
        "options": {"ssl": "SSL", "tls": "TLS", "none": "None"},
        "help": "SMTP over SSL, TLS, or None",
        "tooltip": "Security scheme to use to connect to e-mail server",
        "global": True
    },
    "mail.username": {
        "type": UserInput.OPTION_TEXT,
        "default": "",
        "help": "SMTP Username",
        "tooltip": "Only if your SMTP server requires login",
        "global": True
    },
    "mail.password": {
        "type": UserInput.OPTION_TEXT,
        "default": "",
        "help": "SMTP Password",
        "tooltip": "Only if your SMTP server requires login",
        "global": True
    },
    "mail.noreply": {
        "type": UserInput.OPTION_TEXT,
        "default": "noreply@localhost",
        "help": "NoReply e-mail",
        "global": True
    },
    # Explorer settings
    # The maximum allowed amount of rows (prevents timeouts and memory errors)
    "explorer.max_posts": {
        "type": UserInput.OPTION_TEXT,
        "default": 100000,
        "help": "Amount of posts",
        "coerce_type": int,
        "tooltip": "Amount of posts to show in Explorer. The maximum allowed amount of rows (prevents timeouts and "
                   "memory errors)"
    },
    "explorer.posts_per_page": {
        "type": UserInput.OPTION_TEXT,
        "default": 50,
        "help": "Posts per page",
        "coerce_type": int,
        "tooltip": "Posts to display per page"
    },
    # Web tool settings
    # These are used by the FlaskConfig class in config.py
    # Flask may require a restart to update them
    "flask.flask_app": {
        "type": UserInput.OPTION_TEXT,
        "default": "webtool/fourcat",
        "help": "Flask App Name",
        "tooltip": "",
        "global": True
    },
    "flask.server_name": {
        "type": UserInput.OPTION_TEXT,
        "default": "localhost",
        "help": "Host name",
        "tooltip": "e.g., my4CAT.com, localhost, 127.0.0.1. Default is localhost; when running 4CAT in Docker this "
                   "setting is ignored as any domain/port binding should be handled outside of the Docker container"
                   "; the Docker container itself will serve on any domain name on the port configured in the .env "
                   "file.",
        "global": True
    },
    "flask.autologin.hostnames": {
        "type": UserInput.OPTION_TEXT_JSON,
        "default": ["localhost"],
        "help": "White-listed hostnames",
        "tooltip": "A list of host names or IP addresses to automatically log in. Docker should include localhost and Server Name",
        "global": True
    },
    "flask.autologin.api": {
        "type": UserInput.OPTION_TEXT_JSON,
        "default": ["localhost"],
        "help": "White-list for API",
        "tooltip": "A list of host names or IP addresses to allow access to API endpoints with no rate limiting. Docker should include localhost and Server Name",
        "global": True
    },
    "flask.https": {
        "type": UserInput.OPTION_TOGGLE,
        "default": False,
        "help": "Use HTTPS",
        "tooltip": "If your server is using 'https', set to True and 4CAT will use HTTPS links.",
        "global": True
    },
    "flask.autologin.name": {
        "type": UserInput.OPTION_TEXT,
        "default": "Automatic login",
        "help": "Auto-login name",
        "tooltip": "Username for whitelisted hosts (automatically logged in users see this name for themselves)",
    },
    "flask.secret_key": {
        "type": UserInput.OPTION_TEXT,
        "default": "please change me... please...",
        "help": "Secret key",
        "tooltip": "Secret key for Flask, used for session cookies",
        "global": True
    },
    "flask.tag_order": {
        "type": UserInput.OPTION_TEXT_JSON,
        "default": ["admin"],
        "help": "Tag priority",
        "tooltip": "User tag priority order. It is recommended to manipulate this with the 'User tags' panel instead of directly.",
        "global": True
    },
    # YouTube variables to use for processors
    "api.youtube.name": {
        "type": UserInput.OPTION_TEXT,
        "default": "youtube",
        "help": "YouTube API Service",
        "tooltip": "YouTube API 'service name', e.g. youtube, googleapis, etc.",
        "global": True
    },
    "api.youtube.version": {
        "type": UserInput.OPTION_TEXT,
        "default": "v3",
        "help": "YouTube API Version",
        "tooltip": "e.g., ''v3'",
        "global": True
    },
    "api.youtube.key": {
        "type": UserInput.OPTION_TEXT,
        "default": "",
        "help": "YouTube API Key",
        "tooltip": "The developer key from your API console"
    },
    # service manager
    # this is a service that 4CAT can connect to to run e.g. ML models
    # it is used by a number of processors
    "dmi-service-manager.server_address": {
        "type": UserInput.OPTION_TEXT,
        "default": "",
        "help": "DMI Service Manager server/URL",
        "tooltip": "https://github.com/digitalmethodsinitiative/dmi_service_manager",
        "global": True
    },
    "dmi-service-manager.local_or_remote": {
        "type": UserInput.OPTION_CHOICE,
        "default": 0,
        "help": "DMI Services Local or Remote",
        "tooltip": "Services have local access to 4CAT files or must be transferred from remote via DMI Service Manager",
        "options": {
            "local": "Local",
            "remote": "Remote",
        },
        "global": True
    }
}

# These are used in the web interface for more readable names
# Can't think of a better place to put them...
categories = {
    "4cat": "4CAT Tool settings",
    "api": "API credentials",
    "flask": "Flask settings",
    "explorer": "Data Explorer",
    "expire": "Dataset expiration settings",
    "mail": "Mail settings & credentials",
    "logging": "Logging",
    "path": "File paths",
    "privileges": "User privileges"
}
