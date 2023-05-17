import json

from pathlib import Path
from common.lib.database import Database

from common.lib.exceptions import ConfigException
from common.lib.config_definition import config_definition

import configparser
import os


class ConfigManager:
    db = None
    dbconn = None
    cache = {}

    core_settings = {}
    config_definition = {}
    tag_context = []  # todo

    def __init__(self, db=None):
        # ensure core settings (including database config) are loaded
        self.load_core_settings()
        self.load_user_settings()

        # establish database connection if none available
        self.db = db

    def with_db(self, db=None):
        """
        Initialise database

        Not done on init, because something may need core settings before the
        database can be initialised

        :param db:  Database object. If None, initialise it using the core config
        """
        self.db = db if db else Database(logger=None, dbname=self.get("DB_NAME"), user=self.get("DB_USER"),
                           password=self.get("DB_PASSWORD"), host=self.get("DB_HOST"),
                           port=self.get("DB_PORT"), appname="config-reader") if not db else db

    def load_user_settings(self):
        """
        Load settings configurable by the user

        Does not load the settings themselves, but rather the definition so
        values can be validated, etc
        """
        # basic 4CAT settings
        self.config_definition.update(config_definition)

        # module settings can't be loaded directly because modules need the
        # config manager to load, so that becomes circular
        # instead, this is cached on startup and then loaded here
        module_config_path = self.get("PATH_ROOT").joinpath("backend/module_config.json")
        if module_config_path.exists():
            try:
                with module_config_path.open() as infile:
                    self.config_definition.update(json.load(infile))
            except (json.JSONDecodeError, TypeError):
                pass

    def load_core_settings(self):
        """
        Load 4CAT core settings

        These are (mostly) stored in config.ini and cannot be changed from the
        web interface.

        :return:
        """
        config_file = Path(__file__).parent.parent.joinpath("config/config.ini")

        config_reader = configparser.ConfigParser()
        in_docker = False
        if config_file.exists():
            config_reader.read(config_file)
            if config_reader["DOCKER"].getboolean("use_docker_config"):
                # Can use throughtout 4CAT to know if Docker environment
                in_docker = True
        else:
            # config should be created!
            raise ConfigException("No config/config.ini file exists! Update and rename the config.ini-example file.")

        self.core_settings.update({
            "CONFIG_FILE": config_file.resolve(),
            "USING_DOCKER": in_docker,
            "DB_HOST": config_reader["DATABASE"].get("db_host"),
            "DB_PORT": config_reader["DATABASE"].get("db_port"),
            "DB_USER": config_reader["DATABASE"].get("db_user"),
            "DB_NAME": config_reader["DATABASE"].get("db_name"),
            "DB_PASSWORD": config_reader["DATABASE"].get("db_password"),

            "API_HOST": config_reader["API"].get("api_host"),
            "API_PORT": config_reader["API"].getint("api_port"),

            "PATH_ROOT": Path(os.path.abspath(os.path.dirname(__file__))).joinpath(
                "..").resolve(),  # better don"t change this
            "PATH_LOGS": Path(config_reader["PATHS"].get("path_logs", "")),
            "PATH_IMAGES": Path(config_reader["PATHS"].get("path_images", "")),
            "PATH_DATA": Path(config_reader["PATHS"].get("path_data", "")),
            "PATH_LOCKFILE": Path(config_reader["PATHS"].get("path_lockfile", "")),
            "PATH_SESSIONS": Path(config_reader["PATHS"].get("path_sessions", "")),

            "ANONYMISATION_SALT": config_reader["GENERATE"].get("anonymisation_salt"),
            "SECRET_KEY": config_reader["GENERATE"].get("secret_key")
        })

    def get(self, attribute_name, default=None, raw=False, user=None, tags=None):
        """
        Get a setting's value from the database

        If the setting does not exist, the provided fallback value is returned.

        :param str attribute_name:  Setting to return
        :param default:  Value to return if setting does not exist
        :param bool raw:  if True, the value is returned as stored and not
        interpreted as JSON if it comes from the database
        :param user:  User object or name. Adds a tag `user:[username]` in
        front of the tag list.
        :param tags:  Tag or tags for the required setting. If a tag is
        provided, the method checks if a special value for the setting exists
        with the given tag, and returns that if one exists. First matching tag
        wins.

        :return:  Setting value, or the provided fallback, or `None`.
        """
        # core settings are not from the database
        if attribute_name in self.core_settings:
            return self.core_settings[attribute_name]

        # if trying to access a setting that's not a core setting, attempt to
        # initialise the database connection
        if not self.db:
            self.with_db()

        # be flexible about the input types here
        if tags is None:
            tags = []
        elif type(tags) is str:
            tags = [tags]

        # can provide either a string or user object
        if type(user) is not str:
            if hasattr(user, "get_id"):
                user = user.get_id()
            elif user is not None:
                raise TypeError("get() expects None, a User object or a string for argument 'user'")

        # user-specific settings are just a special type of tag (which takes
        # precedence), same goes for user groups
        if user:
            groups = self.db.fetchall("SELECT group FROM user_groups WHERE user = %s", (user,))

            for group in groups:
                tags.insert(0, f"group:{group['group']}")

            tags.insert(0, f"user:{user}")


        # query database for any values within the required tags
        tags.append("")  # empty tag = default value
        settings = {s["tag"]: s["value"] for s in
                    self.db.fetchall("SELECT * FROM settings WHERE name = %s AND tag IN %s", (attribute_name, tuple(tags)))}

        # return first matching setting with a required tag, in the order the
        # tags were provided
        value = None
        if settings:
            for tag in tags:
                if tag in settings:
                    value = settings[tag]
                    break

        # no matching tags? try empty tag
        if value is None and "" in settings:
            value = settings[""]

        if not raw and value is not None:
            value = json.loads(value)
        elif default is not None:
            value = default
        elif value is None and attribute_name in config_definition and "default" in config_definition[attribute_name]:
            value = config_definition[attribute_name]["default"]

        return value

    def __getattr__(self, attr):
        """
        Getter so we can directly request values

        :param attr:  Config setting to get
        :return:  Value
        """

        if attr in dir(self):
            # an explicitly defined attribute should always be called in favour
            # of this passthrough
            attribute = getattr(self, attr)
            return attribute
        else:
            return self.get(attr)

    def set(self, attribute_name, value, is_json, overwrite_existing=True, connection=None, cursor=None,
            keep_connection_open=False):
        """
        Insert OR set value for a setting

        If overwrite_existing=True and the setting exists, the setting is updated; if overwrite_existing=False and the
        setting exists the setting is not updated.

        :param str attribute_name:  Attribute to set
        :param value:  Value to set (will be serialised as JSON)
        :param bool is_json:  True for a value that is already a serialised JSON string; False if value is object that needs to
                          be serialised into a JSON string
        :param bool overwrite_existing: True will overwrite existing setting, False will do nothing if setting exists
        :param connection: Database connection, if None then a new connection will be created
        :param cursor: Database cursor, if None then a new cursor will be created
        :param keep_connection_open: Close connection after query?
        :return int: number of updated rows
        """
        # Check value is valid JSON
        if is_json:
            try:
                json.dumps(json.loads(value))
            except json.JSONDecodeError:
                return None
        else:
            try:
                value = json.dumps(value)
            except json.JSONDecodeError:
                return None

        if overwrite_existing:
            query = "INSERT INTO settings (name, value) Values (%s, %s) ON CONFLICT (name) DO UPDATE SET value = EXCLUDED.value"
        else:
            query = "INSERT INTO settings (name, value) Values (%s, %s) ON CONFLICT DO NOTHING"

        self.db.execute(query, (attribute_name, value))
        updated_rows = cursor.rowcount

        return updated_rows

config = ConfigManager()