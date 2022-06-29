""" 4CAT configuration """
import os
import json
from pathlib import Path
import psycopg2
import psycopg2.extras
import configparser

from common.lib.exceptions import ConfigException


class ConfigManager:
    """
    Manage 4CAT configuration options that cannot be recorded in database
    (generally because they are used to get to the database!).

    Note: some options are here until additional changes are made and they can
    be moved to more appropriate locations.
    """
    CONFIG_FILE = Path(__file__).parent.parent.joinpath("config/config.ini")

    # TODO: work out best structure for docker vs non-docker
    # Do not need two configs, BUT Docker config.ini has to be in shared volume for both front and backend to access it
    config_reader = configparser.ConfigParser()
    USING_DOCKER = False
    if CONFIG_FILE.exists():
        config_reader.read(CONFIG_FILE)
        if config_reader["DOCKER"].getboolean("use_docker_config"):
            # Can use throughtout 4CAT to know if Docker environment
            USING_DOCKER = True
    else:
        # config should be created!
        raise ConfigException("No config/config.ini file exists! Update and rename the config.ini-example file.")

    DB_HOST = config_reader["DATABASE"].get("db_host")
    DB_PORT = config_reader["DATABASE"].getint("db_port")
    DB_USER = config_reader["DATABASE"].get("db_user")
    DB_NAME = config_reader["DATABASE"].get("db_name")
    DB_PASSWORD = config_reader["DATABASE"].get("db_password")

    API_HOST = config_reader["API"].get("api_host")
    API_PORT = config_reader["API"].getint("api_port")

    PATH_ROOT = str(Path(os.path.abspath(os.path.dirname(__file__))).joinpath(".."))  # better don"t change this
    PATH_LOGS = config_reader["PATHS"].get("path_logs", "")
    PATH_IMAGES = config_reader["PATHS"].get("path_images", "")
    PATH_DATA = config_reader["PATHS"].get("path_data", "")
    PATH_LOCKFILE = config_reader["PATHS"].get("path_lockfile", "")
    PATH_SESSIONS = config_reader["PATHS"].get("path_sessions", "")

    ANONYMISATION_SALT = config_reader["GENERATE"].get("anonymisation_salt")
    SECRET_KEY = config_reader["GENERATE"].get("secret_key")


def quick_db_connect():
    """
    Create a connection and cursor with the database

    We're not using lib.database.Database because that one relies on some
    config options, which would get paradoxical really fast.

    :return list: [connection, cursor]
    """
    connection = psycopg2.connect(dbname=ConfigManager.DB_NAME, user=ConfigManager.DB_USER,
                                  password=ConfigManager.DB_PASSWORD, host=ConfigManager.DB_HOST,
                                  port=ConfigManager.DB_PORT)
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
    :param bool raw:  Do not parse as JSON?
    :return:  Setting value, or the provided fallback, or `None`.
    """
    if attribute_name in dir(ConfigManager):
        # an explicitly defined attribute should always be called in favour
        # of this passthrough
        attribute = getattr(ConfigManager, attribute_name)
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
            return default
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


def set_value(attribute_name, value, connection=None, cursor=None, keep_connection_open=False, raw=True):
    """
    Update setting

    Updates database attribute with new value. Returns number of updated rows
    (which ought to be either 1 for success or 0 for failure).

    :param str attribute_name:  Attribute to set
    :param value:  Value to set (will be serialised as JSON)
    :param connection:  Database connection, if None then a new connection will be created
    :param cursor:  Database cursor, if None then a new cursor will be created
    :param bool keep_connection_open:  Close connection after query?
    :param bool raw:  Do not parse as JSON?
    :return int:  Number of updated rows
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
        query = "UPDATE settings SET value = %s WHERE name = %s"
        cursor.execute(query, (value, attribute_name))
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


def create_setting(attribute_name, value, connection=None, cursor=None, keep_connection_open=False):
    """
    Insert a new setting into the database.

    If the setting already exists, nothing is changed.

    :param str attribute_name:  Attribute to set
    :param value:  Value to set (will be serialised as JSON)
    :param connection: Database connection, if None then a new connection will
    be created
    :param cursor: Database cursor, if None then a new cursor will be created
    :param keep_connection_open: Close connection after query?
    :return int: number of updated rows
    """
    try:
        value = json.dumps(value)
    except ValueError:
        return None

    try:
        if not connection or not cursor:
            connection, cursor = quick_db_connect()

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


def set_or_create_setting(attribute_name, value, connection=None, cursor=None, keep_connection_open=False, raw=True):
    """
    Insert OR set value for a setting

    If the setting exists, it is updated; if not, it is created with the given
    value.

    :param str attribute_name:  Attribute to set
    :param value:  Value to set (will be serialised as JSON)
    :param connection: Database connection, if None then a new connection will
    be created
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

        query = "INSERT INTO settings (name, value) Values (%s, %s) ON CONFLICT (name) DO UPDATE SET value = EXCLUDED.value"
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