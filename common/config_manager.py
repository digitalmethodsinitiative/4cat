""" 4CAT configuration """
import os
import json
from pathlib import Path
import psycopg2
import psycopg2.extras
import configparser

from common.lib.exceptions import ConfigException
from common.lib.config_definition import config_definition


class ConfigManager:
    """
    Manage 4CAT configuration options that cannot be recorded in database
    (generally because they are used to get to the database!).

    Note: some options are here until additional changes are made and they can
    be moved to more appropriate locations.
    """
    def __init__(self, config_ini_path="data/config/config.ini"):
        self.CONFIG_FILE = Path(__file__).parent.parent.joinpath(config_ini_path)

        # Do not need two configs, BUT Docker config.ini has to be in shared volume for both front and backend to access it
        config_reader = configparser.ConfigParser()
        self.USING_DOCKER = False
        if self.CONFIG_FILE.exists():
            config_reader.read(self.CONFIG_FILE)
            if config_reader["DOCKER"].getboolean("use_docker_config"):
                # Can use throughtout 4CAT to know if Docker environment
                self.USING_DOCKER = True
        else:
            # config should be created!
            raise ConfigException("No data/config/config.ini file exists! Update and rename the config.ini-example file.")

        self.DB_HOST = config_reader["DATABASE"].get("db_host")
        self.DB_PORT = config_reader["DATABASE"].getint("db_port")
        self.DB_USER = config_reader["DATABASE"].get("db_user")
        self.DB_NAME = config_reader["DATABASE"].get("db_name")
        self.DB_PASSWORD = config_reader["DATABASE"].get("db_password")

        self.API_HOST = config_reader["API"].get("api_host")
        self.API_PORT = config_reader["API"].getint("api_port")

        self.PATH_ROOT = Path(os.path.abspath(os.path.dirname(__file__))).joinpath("..").resolve()  # better don"t change this
        self.PATH_LOGS = Path(config_reader["PATHS"].get("path_logs", ""))
        self.PATH_IMAGES = Path(config_reader["PATHS"].get("path_images", ""))
        self.PATH_DATA = Path(config_reader["PATHS"].get("path_data", ""))
        self.PATH_LOCKFILE = Path(config_reader["PATHS"].get("path_lockfile", ""))
        self.PATH_SESSIONS = Path(config_reader["PATHS"].get("path_sessions", ""))

        self.ANONYMISATION_SALT = config_reader["GENERATE"].get("anonymisation_salt")
        self.SECRET_KEY = config_reader["GENERATE"].get("secret_key")


# Instantiate the default manager to be used with helper functions below
try:
    config_manager = ConfigManager()
except ConfigException as e:
    # No config.ini file yet; cannot use database
    config_manager = None


def quick_db_connect():
    """
    Create a connection and cursor with the database

    We're not using lib.database.Database because that one relies on some
    config options, which would get paradoxical really fast.

    :return list: [connection, cursor]
    """
    if config_manager is None:
        raise ConfigException("config.ini file does not exist!")
    connection = psycopg2.connect(dbname=config_manager.DB_NAME, user=config_manager.DB_USER,
                                  password=config_manager.DB_PASSWORD, host=config_manager.DB_HOST,
                                  port=config_manager.DB_PORT)
    cursor = connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return connection, cursor


def get(attribute_name, default=None, connection=None, cursor=None, keep_connection_open=False, raw=False):
    """
    Get a setting's value from the database

    If the setting does not exist, the provided fallback value is returned.

    :param str attribute_name:  Setting to return
    :param default:  Value to return if setting does not exist
    :param connection:  Database connection, if None then a new connection will be created
    :param cursor:  Database cursor, if None then a new cursor will be created
    :param bool keep_connection_open:  Close connection after query?
    :param bool raw:  True returns value as JSON serialized string; False returns JSON object
    :return:  Setting value, or the provided fallback, or `None`.
    """
    if config_manager is None:
        raise ConfigException("config.ini file does not exist!")
    
    if attribute_name in dir(config_manager):
        # an explicitly defined attribute should always be called in favour
        # of this passthrough
        attribute = getattr(config_manager, attribute_name)
        return attribute
    else:
        try:
            if not connection or not cursor:
                connection, cursor = quick_db_connect()

            query = "SELECT value FROM settings WHERE name = %s"
            cursor.execute(query, (attribute_name,))
            row = cursor.fetchone()

            if not keep_connection_open:
                connection.close()

            value = row.get("value", None) if row else None
            if not raw and value is not None:
                value = json.loads(value)
        except (Exception, psycopg2.DatabaseError) as error:
            raise ConfigException("Error getting setting {}: {}".format(attribute_name, repr(error)))

        finally:
            if connection is not None and not keep_connection_open:
                connection.close()

        if value is None:
            # no value explicitly defined in the database...
            if default is not None:
                # if an explicit default was provided, return it
                return default
            elif attribute_name in config_definition and "default" in config_definition[attribute_name]:
                # if a default is available from the config definition, return that
                return config_definition[attribute_name]["default"]
            else:
                # use None as the last resort
                return None
        else:
            return value


def get_all(connection=None, cursor=None, keep_connection_open=False, raw=False):
    """
    Gets all database settings in 4cat_settings table. These are editable,
    while other attributes (part of the ConfigManager class are not directly
    editable)

    :param connection: Database connection, if None then a new connection will
    be created
    :param cursor: Database cursor, if None then a new cursor will be created
    :param keep_connection_open: Close connection after query?
    :param bool raw:  True returns values as JSON serialized strings; False returns JSON objects
    :return dict:  Settings, as setting -> value. Values are decoded from JSON
    """
    try:
        if not connection or not cursor:
            connection, cursor = quick_db_connect()

        query = "SELECT name, value FROM settings"
        cursor.execute(query)
        rows = cursor.fetchall()

        if not keep_connection_open:
            connection.close()

        values = {}
        for row in rows:
            value = row.get("value", None) if row else None
            if not raw and value is not None:
                value = json.loads(value)
            values[row["name"]] = value
    except (Exception, psycopg2.DatabaseError) as error:
        raise ConfigException("Error getting settings: {}".format(repr(error)))

    finally:
        if connection is not None and not keep_connection_open:
            connection.close()

    return values


def set_or_create_setting(attribute_name, value, raw, overwrite_existing=True, connection=None, cursor=None, keep_connection_open=False):
    """
    Insert OR set value for a setting

    If overwrite_existing=True and the setting exists, the setting is updated; if overwrite_existing=False and the
    setting exists the setting is not updated.

    :param str attribute_name:  Attribute to set
    :param value:  Value to set (will be serialised as JSON)
    :param bool raw:  True for a value that is already a serialised JSON string; False if value is object that needs to
                      be serialised into a JSON string
    :param bool overwrite_existing: True will overwrite existing setting, False will do nothing if setting exists
    :param connection: Database connection, if None then a new connection will be created
    :param cursor: Database cursor, if None then a new cursor will be created
    :param keep_connection_open: Close connection after query?
    :return int: number of updated rows
    """
    # Check value is valid JSON
    if raw:
        try:
            json.dumps(json.loads(value))
        except json.JSONDecodeError:
            return None
    else:
        try:
            value = json.dumps(value)
        except json.JSONDecodeError:
            return None

    try:
        if not connection or not cursor:
            connection, cursor = quick_db_connect()

        if overwrite_existing:
            query = "INSERT INTO settings (name, value) Values (%s, %s) ON CONFLICT (name) DO UPDATE SET value = EXCLUDED.value"
        else:
            query = "INSERT INTO settings (name, value) Values (%s, %s) ON CONFLICT DO NOTHING"
        cursor.execute(query, (attribute_name, value))
        updated_rows = cursor.rowcount
        connection.commit()

        if not keep_connection_open:
            connection.close()

    except (Exception, psycopg2.DatabaseError) as error:
        raise ConfigException("Error setting setting {}: {}".format(attribute_name, repr(error)))

    finally:
        if connection is not None and not keep_connection_open:
            connection.close()

    return updated_rows


def delete_setting(attribute_name):
    """
    Delete a setting from the database

    :poram str attribute_name:  Name of the setting to delete
    :return int:  Affected rows
    """
    try:
        connection, cursor = quick_db_connect()
        cursor.execute("DELETE FROM settings WHERE name = %s", (attribute_name,))
        updated_rows = cursor.rowcount
        connection.commit()

        return updated_rows

    except (Exception, psycopg2.DatabaseError) as error:
        raise ConfigException("Error setting setting {}: {}".format(attribute_name, repr(error)))

    finally:
        if connection is not None:
            connection.close()
