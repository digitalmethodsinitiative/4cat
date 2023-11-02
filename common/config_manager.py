import itertools
import pickle
import time
import json

from pathlib import Path
from common.lib.database import Database

from common.lib.exceptions import ConfigException
from common.lib.config_definition import config_definition
from common.lib.user_input import UserInput

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
        module_config_path = self.get("PATH_ROOT").joinpath("config/module_config.bin")
        if module_config_path.exists():
            try:
                with module_config_path.open("rb") as infile:
                    retries = 0
                    module_config = None
                    # if 4CAT is being run in two different containers
                    # (front-end and back-end) they might both be running this
                    # bit of code at the same time. If the file is half-written
                    # loading it will fail, so allow for a few retries
                    while retries < 3:
                        try:
                            module_config = pickle.load(infile)
                            break
                        except Exception:  # this can be a number of exceptions, all with the same recovery path
                            time.sleep(0.1)
                            retries += 1
                            continue

                    if module_config is None:
                        # not really a way to gracefully recover from this, but
                        # we can at least describe the error
                        raise RuntimeError("Could not read module_config.bin. The 4CAT developers did a bad job of "
                                           "preventing this. Shame on them!")

                    self.config_definition.update(module_config)
            except (ValueError, TypeError) as e:
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

    def ensure_database(self):
        """
        Ensure the database is in sync with the config definition

        Deletes all stored settings not defined in 4CAT, and creates a global
        setting for all settings not yet in the database.
        """
        self.with_db()

        # delete unknown keys
        known_keys = tuple([names for names, settings in config.config_definition.items() if settings.get("type") not in UserInput.OPTIONS_COSMETIC])
        unknown_keys = self.db.fetchall("SELECT DISTINCT name FROM settings WHERE name NOT IN %s", (known_keys,))

        if unknown_keys:
            self.db.log.info(f"Deleting unknown settings from database: {', '.join([key['name'] for key in unknown_keys])}")
            self.db.delete("settings", where={"name": tuple([key["name"] for key in unknown_keys])}, commit=False)

        self.db.commit()

        # create global values for known keys with the default
        known_settings = self.get_all()
        for setting, parameters in self.config_definition.items():
            if setting in known_settings:
                continue

            self.set(setting, parameters.get("default", ""))

        # make sure settings and user table are in sync
        user_tags = list(set(itertools.chain(*[u["tags"] for u in self.db.fetchall("SELECT DISTINCT tags FROM users")])))
        known_tags = [t["tag"] for t in self.db.fetchall("SELECT DISTINCT tag FROM settings")]
        tag_order = self.get("flask.tag_order")

        for tag in tag_order:
            # don't include tags not used by users in the tag order
            if tag not in user_tags:
                tag_order.remove(tag)

        for tag in known_tags:
            # add tags used by a setting to tag order
            if tag and tag not in tag_order:
                tag_order.append(tag)

        for tag in user_tags:
            # add tags used by a user to tag order
            if tag and tag not in tag_order:
                tag_order.append(tag)

        # admin tag should always be first in order
        if "admin" in tag_order:
            tag_order.remove("admin")

        tag_order.insert(0, "admin")

        self.set("flask.tag_order", tag_order)
        self.db.commit()

    def get_all(self, is_json=False, user=None, tags=None):
        """
        Get all known settings

        :param bool is_json:  if True, the value is returned as stored and not
        interpreted as JSON if it comes from the database
        :param user:  User object or name. Adds a tag `user:[username]` in
        front of the tag list.
        :param tags:  Tag or tags for the required setting. If a tag is
        provided, the method checks if a special value for the setting exists
        with the given tag, and returns that if one exists. First matching tag
        wins.

        :return dict: Setting value, as a dictionary with setting names as keys
        and setting values as values.
        """
        return self.get(attribute_name=None, default=None, is_json=is_json, user=user, tags=tags)

    def get(self, attribute_name, default=None, is_json=False, user=None, tags=None):
        """
        Get a setting's value from the database

        If the setting does not exist, the provided fallback value is returned.

        :param str|list|None attribute_name:  Setting to return. If a string,
        return that setting's value. If a list, return a dictionary of values.
        If none, return a dictionary with all settings.
        :param default:  Value to return if setting does not exist
        :param bool is_json:  if True, the value is returned as stored and not
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
        if type(attribute_name) is str:
            if attribute_name in self.core_settings:
                return self.core_settings[attribute_name]
            else:
                attribute_name = (attribute_name,)
        elif type(attribute_name) in (set, str):
            attribute_name = tuple(attribute_name)

        # if trying to access a setting that's not a core setting, attempt to
        # initialise the database connection
        if not self.db:
            self.with_db()

        # get tags to look for
        tags = self.get_active_tags(user, tags)

        # query database for any values within the required tags
        tags.append("")  # empty tag = default value
        if attribute_name:
            query = "SELECT * FROM settings WHERE name IN %s AND tag IN %s"
            replacements = (tuple(attribute_name), tuple(tags))
        else:
            query = "SELECT * FROM settings WHERE tag IN %s"
            replacements = (tuple(tags), )

        settings = {setting: {} for setting in attribute_name} if attribute_name else {}

        for setting in self.db.fetchall(query, replacements):
            if setting["name"] not in settings:
                settings[setting["name"]] = {}

            settings[setting["name"]][setting["tag"]] = setting["value"]

        final_settings = {}
        for setting_name, setting in settings.items():
            # return first matching setting with a required tag, in the order the
            # tags were provided
            value = None
            if setting:
                for tag in tags:
                    if tag in setting:
                        value = setting[tag]
                        break

            # no matching tags? try empty tag
            if value is None and "" in setting:
                value = setting[""]

            if not is_json and value is not None:
                value = json.loads(value)
            elif default is not None:
                value = default
            elif value is None and setting_name in self.config_definition and "default" in self.config_definition[setting_name]:
                value = self.config_definition[setting_name]["default"]

            final_settings[setting_name] = value

        if len(final_settings) == 1:
            # print(f"{user}: {attribute_name[0]} = {list(final_settings.values())[0]}")
            return list(final_settings.values())[0]
        else:
            return final_settings

    def get_active_tags(self, user=None, tags=None):
        """
        Get active tags for given user/tag list

        Used internally to harmonize tag setting for various methods, but can
        also be called directly to verify tag activation.

        :param user:  User object or name. Adds a tag `user:[username]` in
        front of the tag list.
        :param tags:  Tag or tags for the required setting. If a tag is
        provided, the method checks if a special value for the setting exists
        with the given tag, and returns that if one exists. First matching tag
        wins.
        :return list:  List of tags
        """
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
            user_tags = self.db.fetchone("SELECT tags FROM users WHERE name = %s", (user,))
            if user_tags:
                try:
                    tags.extend(user_tags["tags"])
                except (TypeError, ValueError):
                    # should be a JSON list, but isn't
                    pass

            tags.insert(0, f"user:{user}")

        return tags

    def set(self, attribute_name, value, is_json=False, tag="", overwrite_existing=True):
        """
        Insert OR set value for a setting

        If overwrite_existing=True and the setting exists, the setting is updated; if overwrite_existing=False and the
        setting exists the setting is not updated.

        :param str attribute_name:  Attribute to set
        :param value:  Value to set (will be serialised as JSON)
        :param bool is_json:  True for a value that is already a serialised JSON string; False if value is object that needs to
                          be serialised into a JSON string
        :param bool overwrite_existing: True will overwrite existing setting, False will do nothing if setting exists
        :param str tag:  Tag to write setting for

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

        if attribute_name in self.config_definition and self.config_definition.get(attribute_name).get("global"):
            tag = ""

        if overwrite_existing:
            query = "INSERT INTO settings (name, value, tag) VALUES (%s, %s, %s) ON CONFLICT (name, tag) DO UPDATE SET value = EXCLUDED.value"
        else:
            query = "INSERT INTO settings (name, value, tag) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING"

        self.db.execute(query, (attribute_name, value, tag))
        updated_rows = self.db.cursor.rowcount

        return updated_rows

    def delete_for_tag(self, attribute_name, tag):
        """
        Delete config override for a given tag

        :param str attribute_name:
        :param str tag:
        :return int: number of deleted rows
        """
        self.db.delete("settings", where={"name": attribute_name, "tag": tag})
        updated_rows = self.db.cursor.rowcount

        return updated_rows

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


class ConfigWrapper:
    """
    Wrapper for the config manager

    Allows setting a default set of tags or user, so that all subsequent calls
    to `get()` are done for those tags or that user. Can also adjust tags based
    on the HTTP request, if used in a Flask context.
    """
    def __init__(self, config, user=None, tags=None, request=None):
        """
        Initialise config wrapper

        :param ConfigManager config:  Initialised config manager
        :param user:  User to get settings for
        :param tags:  Tags to get settings for
        :param request:  Request to get headers from. This can be used to set
        a particular tag based on the HTTP headers of the request, e.g. to
        serve 4CAT with a different configuration based on the proxy server
        used.
        """
        self.config = config
        self.user = user
        self.tags = tags
        self.request = request


    def set(self, *args, **kwargs):
        """
        Wrap `set()`

        :param args:
        :param kwargs:
        :return:
        """
        if "tag" not in kwargs and self.tags:
            tag = self.tags if type(self.tags) is str else self.tags[0]
            kwargs["tag"] = self.tags

        return self.config.set(*args, **kwargs)

    def get_all(self, *args, **kwargs):
        """
        Wrap `get_all()`

        Takes the `user`, `tags` and `request` given when initialised into
        account. If `tags` is set explicitly, the HTTP header-based override
        is not applied.

        :param args:
        :param kwargs:
        :return:
        """
        if "user" not in kwargs and self.user:
            kwargs["user"] = self.user

        if "tags" not in kwargs:
            kwargs["tags"] = self.tags if self.tags else []
            kwargs["tags"] = self.request_override(kwargs["tags"])

        return self.config.get_all(*args, **kwargs)

    def get(self, *args, **kwargs):
        """
        Wrap `get()`

        Takes the `user`, `tags` and `request` given when initialised into
        account. If `tags` is set explicitly, the HTTP header-based override
        is not applied.

        :param args:
        :param kwargs:
        :return:
        """
        if "user" not in kwargs:
            kwargs["user"] = self.user

        if "tags" not in kwargs:
            kwargs["tags"] = self.tags if self.tags else []
            kwargs["tags"] = self.request_override(kwargs["tags"])

        return self.config.get(*args, **kwargs)

    def get_active_tags(self, user=None, tags=None):
        """
        Wrap `get_active_tags()`

        Takes the `user`, `tags` and `request` given when initialised into
        account. If `tags` is set explicitly, the HTTP header-based override
        is not applied.

        :param user:
        :param tags:
        :return list:
        """
        active_tags = self.config.get_active_tags(user, tags)
        if not tags:
            active_tags = self.request_override(active_tags)

        return active_tags

    def request_override(self, tags):
        """
        Force tag via HTTP request headers

        To facilitate loading different configurations based on the HTTP
        request, the request object can be passed to the ConfigWrapper and
        if a certain request header is set, the value of that header will be
        added to the list of tags to consider when retrieving settings.

        See the flask.proxy_secret config setting; this is used to prevent
        users from changing configuration by forging the header.

        :param list|str tags:  List of tags to extend based on request
        :return list:  Amended list of tags
        """
        if type(tags) is str:
            tags = [tags]

        if self.request and self.request.headers.get("X-4Cat-Config-Tag") and \
            self.config.get("flask.proxy_secret") and \
            self.request.headers.get("X-4Cat-Config-Via-Proxy") == self.config.get("flask.proxy_secret"):
            # need to ensure not just anyone can add this header to their
            # request!
            # to this end, the second header must be set to the secret value;
            # if it is not set, assume the headers are not being configured by
            # the proxy server
            if not tags:
                tags = []

            # can never set admin tag via headers (should always be user-based)
            forbidden_overrides = ("admin",)
            tags += [tag for tag in self.request.headers.get("X-4Cat-Config-Tag").split(",") if tag not in forbidden_overrides]

        return tags

    def __getattr__(self, item):
        """
        Generic wrapper

        Just pipe everything through to the config object

        :param item:
        :return:
        """
        if hasattr(self.config, item):
            return getattr(self.config, item)
        elif hasattr(self, item):
            return getattr(self, item)
        else:
            raise AttributeError(f"'{self.__name__}' object has no attribute '{item}'")

class ConfigDummy:
    """
    Dummy class to use as initial value for class-based configs

    The config manager in processor objects takes the owner of the dataset of
    the processor into account. This is only available after the object has
    been inititated, so until then use this dummy wrapper that throws an error
    when used to access config variables
    """
    def __getattribute__(self, item):
        """
        Access class attribute

        :param item:
        :raises NotImplementedError:
        """
        raise NotImplementedError("Cannot call processor config object in a class or static method - call global "
                                  "configuration manager instead.")


config = ConfigManager()
