"""
Default 4CAT Configuration Options

Possible options and their default values. Options are actually set in 4CAT"s
Database. Additional options can be defined in Data sources or Processors as
`config` objects.
"""
from common.lib.user_input import UserInput
import json

config_definition = {
    "datasources._intro": {
        "type": UserInput.OPTION_INFO,
        "help": "Data sources enabled below will be offered to people on the 'Create Dataset' page. Additionally, "
                "people can upload datasets for these by for example exporting them with "
                "[Zeeschuimer](https://github.com/digitalmethodsinitiative/zeeschuimer) to this 4CAT instance.\n\n"
                "Some data sources offer further settings which may be configured on other tabs."
    },
    "datasources.enabled": {
        "type": UserInput.OPTION_DATASOURCES,
        "default": ["ninegag", "douban", "douyin", "imgur", "upload", "instagram", "linkedin", "parler",
                    "telegram", "tiktok", "twitter"],
        "help": "Data Sources",
        "tooltip": "A list of enabled data sources that people can choose from when creating a dataset page."
    },
    "datasources._intro2": {
        "type": UserInput.OPTION_INFO,
        "help": "*Warning:* changes take effect immediately. Datasets that would have expired under the new settings "
                "will be deleted. You can use the 'Dataset bulk management' module in the control panel to manage the "
                "expiration status of existing datasets."
    },
    "datasources.expiration": {
        "type": UserInput.OPTION_TEXT_JSON,
        "default": {"fourchan": {"enabled": False, "allow_optout": False, "timeout": 0}, "eightchan": {"enabled": False, "allow_optout": False, "timeout": 0}, "eightkun": {"enabled": False, "allow_optout": False, "timeout": 0}, "ninegag": {"enabled": True, "allow_optout": False, "timeout": 0}, "bitchute": {"enabled": True, "allow_optout": False, "timeout": 0}, "dmi-tcat": {"enabled": False, "allow_optout": False, "timeout": 0}, "dmi-tcatv2": {"enabled": False, "allow_optout": False, "timeout": 0}, "douban": {"enabled": True, "allow_optout": False, "timeout": 0}, "douyin": {"enabled": True, "allow_optout": False, "timeout": 0}, "imgur": {"enabled": True, "allow_optout": False, "timeout": 0}, "upload": {"enabled": True, "allow_optout": False, "timeout": 0}, "instagram": {"enabled": True, "allow_optout": False, "timeout": 0}, "linkedin": {"enabled": True, "allow_optout": False, "timeout": 0}, "parler": {"enabled": True, "allow_optout": False, "timeout": 0}, "reddit": {"enabled": False, "allow_optout": False, "timeout": 0}, "telegram": {"enabled": True, "allow_optout": False, "timeout": 0}, "tiktok": {"enabled": True, "allow_optout": False, "timeout": 0}, "tiktok-urls": {"enabled": False, "allow_optout": False, "timeout": 0}, "tumblr": {"enabled": False, "allow_optout": False, "timeout": 0}, "twitter": {"enabled": True, "allow_optout": False, "timeout": 0}, "twitterv2": {"enabled": False, "allow_optout": False, "timeout": 0}, "usenet": {"enabled": False, "allow_optout": False, "timeout": 0}, "vk": {"enabled": False, "allow_optout": False, "timeout": 0}},
        "help": "Data source-specific expiration",
        "tooltip": "Allows setting expiration settings per datasource. Configured by proxy via the 'data sources' "
                   "setting.",
        "indirect": True
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
        "help": "Can view private datasets",
        "tooltip": "Controls whether users can see the datasets made private by their owners."
    },
    "privileges.can_create_api_token": {
        "type": UserInput.OPTION_TOGGLE,
        "default": True,
        "help": "Can create API token",
        "tooltip": "Controls whether users can create a token for authentication with 4CAT's Web API."
    },
    "privileges.can_use_explorer": {
        "type": UserInput.OPTION_TOGGLE,
        "default": True,
        "help": "Can use explorer",
        "tooltip": "Controls whether users can use the Explorer feature to navigate datasets."
    },
    "privileges.can_export_datasets": {
        "type": UserInput.OPTION_TOGGLE,
        "default": True,
        "help": "Can export datasets",
        "tooltip": "Allows users to export datasets they own to other 4CAT instances."
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
        "help": "Can manage notifications",
        "tooltip": "Controls whether users can add, edit and delete notifications via the Control Panel"
    },
    "privileges.admin.can_manage_settings": {
        "type": UserInput.OPTION_TOGGLE,
        "default": False,
        "help": "Can manage settings",
        "tooltip": "Controls whether users can manipulate 4CAT settings via the Control Panel"
    },
    "privileges.admin.can_manipulate_all_datasets": {
        "type": UserInput.OPTION_TOGGLE,
        "default": False,
        "help": "Can manipulate datasets",
        "tooltip": "Controls whether users can manipulate all datasets as if they were an owner, e.g. sharing it with "
                   "others, running processors, et cetera."
    },
    "privileges.admin.can_restart": {
        "type": UserInput.OPTION_TOGGLE,
        "default": False,
        "help": "Can restart/upgrade",
        "tooltip": "Controls whether users can restart and upgrade 4CAT via the Control Panel"
    },
    "privileges.can_upgrade_to_dev": {
        # this is NOT an admin privilege, because all admins automatically
        # get all admin privileges! users still need the above privilege
        # to actually use this, anyway
        "type": UserInput.OPTION_TOGGLE,
        "default": False,
        "help": "Can upgrade to development branch",
        "tooltip": "Controls whether users can upgrade 4CAT to a development branch of the code via the Control Panel. "
                   "This is an easy way to break 4CAT so it is recommended to not enable this unless you're really "
                   "sure of what you're doing."
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
        "default": True,
        "help": "Shown phone home request?",
        "tooltip": "Whether you've seen the 'phone home request'. Set to `False` to see the request again. There "
                   "should be no need to change this manually.",
        "global": True
    },
    "4cat.layout_hue": {
        "type": UserInput.OPTION_HUE,
        "default": 356,
        "help": "Interface accent colour",
        "saturation": 87,
        "value": 81,
        "min": 0,
        "max": 360,
        "coerce_type": int,
        "global": True
    },
    "4cat.layout_hue_secondary": {
        "type": UserInput.OPTION_HUE,
        "default": 86,
        "help": "Interface secondary colour",
        "saturation": 87,
        "value": 90,
        "min": 0,
        "max": 360,
        "coerce_type": int,
        "global": True
    },
    "4cat.allow_access_request": {
        "type": UserInput.OPTION_TOGGLE,
        "default": True,
        "help": "Allow access requests",
        "tooltip": "When enabled, users can request a 4CAT account via the login page if they do not have one, "
                   "provided e-mail settings are configured."
    },
    "4cat.sphinx_host": {
        "type": UserInput.OPTION_TEXT,
        "default": "localhost",
        "help": "Sphinx host",
        "tooltip": "Sphinx is used for full-text search for collected datasources (e.g., 4chan, 8kun, 8chan) and requires additional setup (see 4CAT wiki on GitHub).",
        "global": True
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
        "default": "",
        "help": "SMTP server",
        "tooltip": "SMTP server to connect to for sending e-mail alerts.",
        "global": True
    },
    "mail.port": {
        "type": UserInput.OPTION_TEXT,
        "default": 0,
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
        "default": "4cat.local:5000",
        "help": "Host name",
        "tooltip": "e.g., my4CAT.com, localhost, 127.0.0.1. Default is localhost; when running 4CAT in Docker this "
                   "setting is ignored as any domain/port binding should be handled outside of the Docker container"
                   "; the Docker container itself will serve on any domain name on the port configured in the .env "
                   "file.",
        "global": True
    },
    "flask.autologin.hostnames": {
        "type": UserInput.OPTION_TEXT_JSON,
        "default": [],
        "help": "White-listed hostnames",
        "tooltip": "A list of host names or IP addresses to automatically log in. Docker should include localhost and Server Name",
        "global": True
    },
    "flask.autologin.api": {
        "type": UserInput.OPTION_TEXT_JSON,
        "default": [],
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
    "flask.proxy_override": {
        "type": UserInput.OPTION_MULTI_SELECT,
        "default": [],
        "options": {
            "x_for": "X-Forwarded-For",
            "x_proto": "X-Forwarded-Proto",
            "x_host": "X-Forwarded-Host",
            "x_port": "X-Forwarded-Port",
            "x_prefix": "X-Forwarded-Prefix"
        },
        "help": "Use proxy headers for URL",
        "tooltip": "These proxy headers will be taken into account when building URLs. For example, if "
                   "X-Forwarded-Proto is enabled, the URL scheme (http/https) of the built URL will be based on the "
                   "scheme defined by this header. Use when running 4CAT behind a reverse proxy. Requires a front-end "
                   "restart to take effect."
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
    "flask.proxy_secret": {
        "type": UserInput.OPTION_TEXT,
        "default": "",
        "help": "Proxy secret",
        "tooltip": "Secret value to authenticate proxy headers. If the value of the X-4CAT-Config-Via-Proxy header "
                   "matches this value, the X-4CAT-Config-Tag header can be used to enable a given configuration tag. "
                   "Leave empty to disable this functionality."
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
    "dmi-service-manager.aa_DSM-intro-1": {
            "type": UserInput.OPTION_INFO,
            "help": "The [DMI Service Manager](https://github.com/digitalmethodsinitiative/dmi_service_manager#start-dmi-service-manager) is a support tool used to run some advanced processors. These processors generally require high CPU usage, a lot of RAM, or a dedicated GPU and thus do not fit within 4CAT's arcitecture. It is also possible for multiple 4CAT instances to use the same service manager. Please see the link for instructions on setting up your own instance of the DMI Service Manager.",
        },
    "dmi-service-manager.ab_server_address": {
        "type": UserInput.OPTION_TEXT,
        "default": "",
        "help": "DMI Service Manager server/URL",
        "tooltip": "The URL of the DMI Service Manager server, e.g. http://localhost:5000",
        "global": True
    },
    "dmi-service-manager.ac_local_or_remote": {
        "type": UserInput.OPTION_CHOICE,
        "default": 0,
        "help": "DMI Services Local or Remote",
        "tooltip": "Services have local access to 4CAT files or must be transferred from remote via DMI Service Manager",
        "options": {
            "local": "Local",
            "remote": "Remote",
        },
        "global": True
    },
    # UI settings
    # this configures what the site looks like
    "ui.homepage": {
        "type": UserInput.OPTION_CHOICE,
        "options": {
            "about": "'About' page",
            "create-dataset": "'Create dataset' page",
            "datasets": "Dataset overview"
        },
        "help": "4CAT home page",
        "default": "about"
    },
    "ui.inline_preview": {
        "type": UserInput.OPTION_TOGGLE,
        "help": "Show inline preview",
        "default": False,
        "tooltip": "Show main dataset preview directly on dataset pages, instead of behind a 'preview' button"
    },
    "ui.show_datasource": {
        "type": UserInput.OPTION_TOGGLE,
        "help": "Show data source",
        "default": True,
        "tooltip": "Show data source for each dataset. Can be useful to disable if only one data source is enabled."
    },
    "ui.nav_pages": {
        "type": UserInput.OPTION_MULTI_SELECT,
        "help": "Pages in navigation",
        "options": {
            "faq": "FAQ",
            "data-policy": "Data Policy",
            "citing": "How to cite",
        },
        "default": ["faq"],
        "tooltip": "These pages will be included in the navigation bar at the top of the interface."
    },
    "ui.prefer_mapped_preview": {
        "type": UserInput.OPTION_TOGGLE,
        "help": "Prefer mapped preview",
        "default": True,
        "tooltip": "If a dataset is a JSON file but it can be mapped to a CSV file, show the CSV in the preview instead"
                   "of the underlying JSON."
    },
    "ui.option_email": {
        "type": UserInput.OPTION_CHOICE,
        "options": {
            "none": "No Emails",
            "processor_only": "Processors only",
            "datasources_only": "Create Dataset only",
            "both": "Both datasets and processors"
        },
        "default": "none",
        "help": "Show email when complete option",
        "tooltip": "If a mail server is set up, enabling this allow users to request emails when datasets and processors are completed."
    },
}

# These are used in the web interface for more readable names
# Can't think of a better place to put them...
categories = {
    "4cat": "4CAT Tool settings",
    "api": "API credentials",
    "flask": "Flask settings",
    "explorer": "Data Explorer",
    "datasources": "Data sources",
    "expire": "Dataset expiration settings",
    "mail": "Mail settings & credentials",
    "logging": "Logging",
    "path": "File paths",
    "privileges": "User privileges",
    "dmi-service-manager": "DMI Service Manager",
    "ui": "User interface",
    "image-visuals": "Image visualization",
}
