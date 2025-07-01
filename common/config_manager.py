import itertools
import threading
import pickle
import time
import json

from pymemcache.client.base import Client as MemcacheClient
from pymemcache.exceptions import MemcacheError
from pymemcache import serde
from pathlib import Path
from common.lib.database import Database

from common.lib.exceptions import ConfigException
from common.lib.config_definition import config_definition

import configparser
import os

class CacheMiss:
    """
    Helper class to distinguish memcache misses from true `None` values
    """
    pass


class ConfigManager:
    db = None
    dbconn = None
    cache = {}
    memcache = None

    core_settings = {}
    config_definition = {}

    def __init__(self, db=None):
        # ensure core settings (including database config) are loaded
        self.load_core_settings()
        self.load_user_settings()
        self.memcache = self.load_memcache()

        # establish database connection if none available
        if db:
            self.with_db(db)

    def with_db(self, db=None):
        """
        Initialise database

        Not done on init, because something may need core settings before the
        database can be initialised

        :param db:  Database object. If None, initialise it using the core config
        """
        if db or not self.db:
            # Replace w/ db if provided else only initialise if not already
            self.db = db if db else Database(logger=None, dbname=self.get("DB_NAME"), user=self.get("DB_USER"),
                                         password=self.get("DB_PASSWORD"), host=self.get("DB_HOST"),
                                         port=self.get("DB_PORT"), appname="config-reader")
        else:
            # self.db already initialized and no db provided
            pass

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
            except (ValueError, TypeError):
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

            "MEMCACHE_SERVER": config_reader.get("MEMCACHE", option="memcache_host", fallback={}),

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


    def load_memcache(self):
        """
        Initialise memcache client

        The config reader can optionally use Memcache to keep fetched values in
        memory.
        """
        if self.get("MEMCACHE_SERVER"):
            try:
                # do one test fetch to test if connection is valid
                memcache = MemcacheClient(self.get("MEMCACHE_SERVER"), serde=serde.pickle_serde, key_prefix=b"4cat-config")
                memcache.set("4cat-init-dummy", time.time())
                memcache.init_thread_id = threading.get_ident()
                return memcache
            except (SystemError, ValueError, MemcacheError, ConnectionError):
                # we have no access to the logger here so we simply pass
                # later we can detect elsewhere that a memcache address is
                # configured but no connection is there - then we can log
                # config reader still works without memcache
                pass

        return None

    def ensure_database(self):
        """
        Ensure the database is in sync with the config definition

        Deletes all stored settings not defined in 4CAT, and creates a global
        setting for all settings not yet in the database.
        """
        self.with_db()

        # create global values for known keys with the default
        known_settings = self.get_all_setting_names()
        for setting, parameters in self.config_definition.items():
            if setting in known_settings:
                continue

            self.db.log.debug(f"Creating setting: {setting} with default value {parameters.get('default', '')}")
            self.set(setting, parameters.get("default", ""))

        # make sure settings and user table are in sync
        user_tags = list(set(itertools.chain(*[u["tags"] for u in self.db.fetchall("SELECT DISTINCT tags FROM users")])))
        known_tags = [t["tag"] for t in self.db.fetchall("SELECT DISTINCT tag FROM settings")]
        tag_order = self.get("flask.tag_order")

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

    def get_all_setting_names(self):
        """
        Get names of all settings

        For when the value doesn't matter!

        :return list:  List of setting names known by the database and core settings
        """
        # attempt to initialise the database connection so we can include
        # user settings
        if not self.db:
            self.with_db()

        settings = list(self.core_settings.keys())
        settings.extend([s["name"] for s in self.db.fetchall("SELECT DISTINCT name FROM settings")])

        return settings

    def get_all(self, is_json=False, user=None, tags=None, memcache=None):
        """
        Get all known settings

        This is *not optimised* but used rarely enough that that doesn't
        matter so much.

        :param bool is_json:  if True, the value is returned as stored and not
        interpreted as JSON if it comes from the database
        :param user:  User object or name. Adds a tag `user:[username]` in
        front of the tag list.
        :param tags:  Tag or tags for the required setting. If a tag is
        provided, the method checks if a special value for the setting exists
        with the given tag, and returns that if one exists. First matching tag
        wins.
        :param MemcacheClient memcache:  Memcache client. If `None` and
        `self.memcache` exists, use that instead.

        :return dict: Setting value, as a dictionary with setting names as keys
        and setting values as values.
        """
        for setting in self.get_all_setting_names():
            yield setting, self.get(setting, None, is_json, user, tags, memcache)


    def get(self, attribute_name, default=None, is_json=False, user=None, tags=None, memcache=None):
        """
        Get a setting's value from the database

        If the setting does not exist, the provided fallback value is returned.

        :param str attribute_name:  Setting to return.
        :param default:  Value to return if setting does not exist
        :param bool is_json:  if True, the value is returned as stored and not
        interpreted as JSON if it comes from the database
        :param user:  User object or name. Adds a tag `user:[username]` in
        front of the tag list.
        :param tags:  Tag or tags for the required setting. If a tag is
        provided, the method checks if a special value for the setting exists
        with the given tag, and returns that if one exists. First matching tag
        wins.
        :param MemcacheClient memcache:  Memcache client. If `None` and
        `self.memcache` exists, use that instead.

        :return:  Setting value, or the provided fallback, or `None`.
        """
        # core settings are not from the database
        # they are therefore also not memcached - too little gain
        if type(attribute_name) is not str:
            raise TypeError(f"attribute_name must be a str, {attribute_name.__class__.__name__} given")

        if attribute_name in self.core_settings:
            # we never get to the database or memcache part of this method if
            # this is a core setting we already know
            return self.core_settings[attribute_name]

        # if trying to access a setting that's not a core setting, attempt to
        # initialise the database connection
        if not self.db:
            self.with_db()

        # get tags to look for
        # copy() because else we keep adding onto the same list, which
        # interacts badly with get_all()
        if tags:
            tags = tags.copy()
        tags = self.get_active_tags(user, tags, memcache)

        # now we have all tags - get the config values for each (if available)
        # and then return the first matching one. Add the 'empty' tag at the
        # end to fall back to the global value if no specific one exists.
        tags.append("")

        # short-circuit via memcache if appropriate
        if not memcache and self.memcache:
            memcache = self.memcache

        # first check if we have all the values in memcache, in which case we
        # do not need a database query
        if memcache:
            if threading.get_ident() != memcache.init_thread_id:
                raise RuntimeError("Thread-unsafe use of memcache! Please make sure you are using a configuration "
                                   "wrapper to read with a thread-local memcache connection.")

            cached_values = {tag: memcache.get(self._get_memcache_id(attribute_name, tag), default=CacheMiss) for tag in tags}

        else:
            cached_values = {t: CacheMiss for t in tags}

        # for the tags we could not get from memcache, run a database query
        # (and save to cache if possible)
        missing_tags = [t for t in cached_values if cached_values[t] is CacheMiss]
        if missing_tags:
            # query database for any values within the required tags
            query = "SELECT * FROM settings WHERE name = %s AND tag IN %s"
            replacements = (attribute_name, tuple(missing_tags))
            queried_settings = {setting["tag"]: setting["value"] for setting in self.db.fetchall(query, replacements)}

            if memcache:
                for tag, value in queried_settings.items():
                    memcache.set(self._get_memcache_id(attribute_name, tag), value)

            cached_values.update(queried_settings)

        # there may be some tags for which we still do not have a value at
        # this point. these simply do not have a tag-specific value but that in
        # itself is worth caching, otherwise we're going to query for a
        # non-existent value each time.
        # so: cache a magic value for such setting/tag combinations, and
        # replace the magic value with a CacheMiss in the dict that will be
        # parsed
        unconfigured_magic = "__unconfigured__"
        if memcache:
            for tag in [t for t in cached_values if cached_values[t] is CacheMiss]:
                # should this be more magic?
                memcache.set(self._get_memcache_id(attribute_name, tag), unconfigured_magic)

            for tag in [t for t in cached_values if cached_values[t] == unconfigured_magic]:
                cached_values[tag] = CacheMiss

        # now we may still have some CacheMisses in the values dict, if there
        # was no setting in the database with that tag. So, find the first
        # value that is not a CacheMiss. If nothing matches, try the global tag
        # and if even that does not match (no setting saved at all) return the
        # default
        for tag in tags:
            if tag in cached_values and cached_values.get(tag) is not CacheMiss:
                value = cached_values[tag]
                break
        else:
            value = default if default else None

        # parse some values...
        if not is_json and value is not None:
            value = json.loads(value)
        # TODO: Which default should have priority? The provided default feels like it should be the highest priority, but I think that is an old implementation and perhaps should be removed. - Dale
        elif value is None and attribute_name in self.config_definition and "default" in self.config_definition[attribute_name]:
            value = self.config_definition[attribute_name]["default"]
        elif value is None and default is not None:
            value = default

        return value

    def get_active_tags(self, user=None, tags=None, memcache=None):
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
        :param MemcacheClient memcache:  Memcache client. If `None` and
        `self.memcache` exists, use that instead.
        :return list:  List of tags
        """
        # be flexible about the input types here
        if tags is None:
            tags = []
        elif type(tags) is str:
            tags = [tags]

        user = self._normalise_user(user)

        # user-specific settings are just a special type of tag (which takes
        # precedence), same goes for user groups. so if a user was passed, get
        # that user's tags (including the 'special' user: tag) and add them
        # to the list
        if user:
            user_tags = CacheMiss
            
            if not memcache and self.memcache:
                memcache = self.memcache
                
            if memcache:
                memcache_id = f"_usertags-{user}"
                user_tags = memcache.get(memcache_id, default=CacheMiss)

            if user_tags is CacheMiss:
                user_tags = self.db.fetchone("SELECT tags FROM users WHERE name = %s", (user,))
                if user_tags and memcache:
                    memcache.set(memcache_id, user_tags)

            if user_tags:
                try:
                    tags.extend(user_tags["tags"])
                except (TypeError, ValueError):
                    # should be a JSON list, but isn't
                    pass

            tags.insert(0, f"user:{user}")

        return tags

    def set(self, attribute_name, value, is_json=False, tag="", overwrite_existing=True, memcache=None):
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
        :param MemcacheClient memcache:  Memcache client. If `None` and
        `self.memcache` exists, use that instead.

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
        self.db.log.debug(f"Updated setting for {attribute_name}: {value} (tag: {tag})")

        if not memcache and self.memcache:
            memcache = self.memcache

        if memcache:
            # invalidate any cached value for this setting
            memcache_id = self._get_memcache_id(attribute_name, tag)
            memcache.delete(memcache_id)

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

        if self.memcache:
            self.memcache.delete(self._get_memcache_id(attribute_name, tag))

        return updated_rows

    def clear_cache(self):
        """
        Clear cached configuration values

        Called when the backend restarts - helps start with a blank slate.
        """
        if not self.memcache:
            return

        self.memcache.flush_all()

    def uncache_user_tags(self, users):
        """
        Clear cached user tags

        User tags are cached with memcache if possible to avoid unnecessary
        database roundtrips. This method clears the cached user tags, in case
        a tag is added/deleted from a user.

        :param list users:  List of users, as usernames or User objects
        """
        if self.memcache:
            for user in users:
                user = self._normalise_user(user)
                self.memcache.delete(f"_usertags-{user}")

    def _normalise_user(self, user):
        """
        Normalise user object

        Users may be passed as a username, a user object, or a proxy of such an
        object. This method normalises this to a string (the username), or
        `None` if no user is provided.

        :param user:  User value to normalise
        :return str|None:  Normalised value
        """

        # can provide either a string or user object
        if type(user) is not str:
            if type(user).__name__ == "LocalProxy":
                # passed on from Flask
                user = user._get_current_object()

            if hasattr(user, "get_id"):
                user = user.get_id()
            elif user != None:  # noqa: E711
                # werkzeug.local.LocalProxy (e.g., user not yet logged in) wraps None; use '!=' instead of 'is not'
                raise TypeError(
                    f"_normalise_user() expects None, a User object or a string for argument 'user', {type(user).__name__} given"
                )

        return user

    def _get_memcache_id(self, attribute_name, tags=None):
        """
        Generate a memcache key for a config setting request

        This includes the relevant user name/tags because the value may be
        different depending on the value of these parameters.

        :param str attribute_name:
        :param str|list tags:
        :return str:
        """
        if tags and isinstance(tags, str):
            tags = [tags]

        tag_bit = []
        if tags:
            tag_bit.append("|".join(tags))

        memcache_id = attribute_name
        if tag_bit:
            memcache_id += f"-{'-'.join(tag_bit)}"

        return memcache_id.encode("ascii")

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
        if type(config) is ConfigWrapper:
            # let's not do nested wrappers, but copy properties unless
            # provided explicitly
            self.user = user if user else config.user
            self.tags = tags if tags else config.tags
            self.request = request if request else config.request
            self.config = config.config
            self.memcache = config.memcache
        else:
            self.config = config
            self.user = user
            self.tags = tags
            self.request = request

            # this ensures we use our own memcache client, important in threaded
            # contexts because pymemcache is not thread-safe. Unless we get a
            # prepared connection...
            self.memcache = self.config.load_memcache()

        # this ensures the user object in turn reads from the wrapper
        if self.user:
            self.user.with_config(self, rewrap=False)


    def set(self, *args, **kwargs):
        """
        Wrap `set()`

        :param args:
        :param kwargs:
        :return:
        """
        if "tag" not in kwargs and self.tags:
            kwargs["tag"] = self.tags

        kwargs["memcache"] = self.memcache

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

        kwargs["memcache"] = self.memcache

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

        kwargs["memcache"] = self.memcache

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


class CoreConfigManager(ConfigManager):
    """
    A configuration reader that can only read from core settings

    Can be used in thread-unsafe context and when no database is present.
    """
    def with_db(self, db=None):
        """
        Raise a RuntimeError when trying to link a database connection

        :param db:
        """
        raise RuntimeError("Trying to read non-core configuration value from a CoreConfigManager")