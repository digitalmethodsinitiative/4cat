"""
Update config to use the database instead of config.py

To upgrade, we need this file and the new configuration manager (which is able
to populate the new database)
"""
import sys
import os
import json
import psycopg2
import psycopg2.extras
import configparser

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "'/../..")

def set_or_create_setting(attribute_name, value, connection, cursor, keep_connection_open=False):
    """
    Insert OR set value for a paramter in the database. ON CONFLICT SET VALUE.

    :return int: number of updated rows
    """
    try:
        value = json.dumps(value)
    except ValueError:
        return None

    try:
        query = 'INSERT INTO settings (name, value) Values (%s, %s) ON CONFLICT (name) DO UPDATE SET value = EXCLUDED.value'
        cursor.execute(query, (attribute_name, value))
        updated_rows = cursor.rowcount
        connection.commit()

        if not keep_connection_open:
            connection.close()

    except (Exception, psycopg2.DatabaseError) as error:
        print('Error transfering setting %s with value %s: %s' % (attribute_name, str(value), str(error)))
        updated_rows = None
    finally:
        if connection is not None and not keep_connection_open:
            connection.close()

    return updated_rows

print("  Checking if preexisting config.py file...")
transfer_settings = False
config = None
try:
    import config as old_config
    transfer_settings = True
    print("  ...Yes, prexisting settings exist.")
except (SyntaxError, ImportError) as e:
    print("  ...No prexisting settings exist.")

print("  Checking if settings table exists...")
if transfer_settings:
    connection = psycopg2.connect(dbname=old_config.DB_NAME, user=old_config.DB_USER, password=old_config.DB_PASSWORD, host=old_config.DB_HOST, port=old_config.DB_PORT, application_name="4cat-migrate")
else:
    import common.config_manager as config
    connection = psycopg2.connect(dbname=config.get('DB_NAME'), user=config.get('DB_USER'), password=config.get('DB_PASSWORD'), host=config.get('DB_HOST'), port=config.get('DB_PORT'), application_name="4cat-migrate")
cursor = connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cursor.execute("SELECT EXISTS (SELECT * from information_schema.tables WHERE table_name=%s)", ('settings',))
has_table = cursor.fetchone()
if not has_table["exists"]:
    print("  ...No, adding table setttings.")
    cursor.execute("""CREATE TABLE IF NOT EXISTS settings (
      name                   TEXT UNIQUE PRIMARY KEY,
      value                  TEXT DEFAULT '{}'
    )""")
    connection.commit()
else:
    print("  ...Yes, settings table already exists.")

if transfer_settings:
    print("  Moving settings to database...")
    # FIRST update config_defaults.ini or docker_config.ini
    # Check if Docker
    old_config_filepath = getattr(old_config, "DOCKER_CONFIG_FILE", getattr(old_config, "CONFIG_FILE", None))
    if old_config_filepath and os.path.exists(old_config_filepath):
        # Old config file exists (Docker setup)
        config_reader = configparser.ConfigParser()
        config_reader.read(old_config_filepath)
    else:
        # new config.ini file
        config_reader = configparser.ConfigParser()
        # If there is no config file then it cannot be a Docker instance
        config_reader.add_section('DOCKER')
        config_reader['DOCKER']['use_docker_config'] = "False"

    # Update DB info
    if not config_reader.has_section('DATABASE'):
        config_reader.add_section('DATABASE')
    if old_config.DB_HOST:
        config_reader['DATABASE']['db_host'] = old_config.DB_HOST
    if old_config.DB_PORT:
        config_reader['DATABASE']['db_port'] = str(old_config.DB_PORT)
    if old_config.DB_USER:
        config_reader['DATABASE']['db_user'] = str(old_config.DB_USER)
    if old_config.DB_PASSWORD:
        config_reader['DATABASE']['db_password'] = str(old_config.DB_PASSWORD)
    if old_config.DB_NAME:
        config_reader['DATABASE']['db_name'] = old_config.DB_NAME

    # Update API info
    if not config_reader.has_section('API'):
        config_reader.add_section('API')
    if old_config.API_HOST:
        config_reader['API']['api_host'] = old_config.API_HOST
    if old_config.API_PORT:
        config_reader['API']['api_port'] = str(old_config.API_PORT)

    # Update PATH info
    if not config_reader.has_section('PATHS'):
        config_reader.add_section('PATHS')
    if old_config.PATH_LOGS:
        config_reader['PATHS']['path_logs'] = old_config.PATH_LOGS
    if old_config.PATH_IMAGES:
        config_reader['PATHS']['path_images'] = old_config.PATH_IMAGES
    if old_config.PATH_DATA:
        config_reader['PATHS']['path_data'] = old_config.PATH_DATA
    if old_config.PATH_LOCKFILE:
        config_reader['PATHS']['path_lockfile'] = old_config.PATH_LOCKFILE
    if old_config.PATH_SESSIONS:
        config_reader['PATHS']['path_sessions'] = old_config.PATH_SESSIONS

    # Update SALT and KEY
    if not config_reader.has_section('GENERATE'):
        config_reader.add_section('GENERATE')
    if old_config.ANONYMISATION_SALT:
        config_reader['GENERATE']['anonymisation_salt'] = str(old_config.ANONYMISATION_SALT)
    if old_config.FlaskConfig.SECRET_KEY:
        config_reader['GENERATE']['secret_key'] = str(old_config.FlaskConfig.SECRET_KEY)

    # Save config file
    configfile_to_save = 'config/config.ini'
    with open(configfile_to_save, 'w') as configfile:
        config_reader.write(configfile)

    # UPDATE Database with other settings
    old_settings = [
        ('DATASOURCES', getattr(old_config, "DATASOURCES", None)),
        ('api.youtube.name', getattr(old_config, "YOUTUBE_API_SERVICE_NAME", None)),
        ('api.youtube.version', getattr(old_config, "YOUTUBE_API_VERSION", None)),
        ('api.youtube.key', getattr(old_config, "YOUTUBE_DEVELOPER_KEY", None)),
        ('4cat.name', getattr(old_config, "TOOL_NAME", None)),
        ('4cat.name_long', getattr(old_config, "TOOL_NAME_LONG", None)),
        ('4cat.github_url', getattr(old_config, "GITHUB_URL", None)),
        ('path.versionfile', getattr(old_config, "PATH_VERSION", None)),
        ('expire.timeout', getattr(old_config, "EXPIRE_DATASETS", None)),
        ('expire.allow_optout', getattr(old_config, "EXPIRE_ALLOW_OPTOUT", None)),
        ('logging.slack.level', getattr(old_config, "WARN_LEVEL", None)),
        ('logging.slack.webhook', getattr(old_config, "WARN_SLACK_URL", None)),
        ('mail.admin_email', getattr(old_config, "ADMIN_EMAILS", [None])[0] if getattr(old_config, "ADMIN_EMAILS", [None]) else None),
        ('mail.server', getattr(old_config, "MAILHOST", None)),
        ('mail.ssl', getattr(old_config, "MAIL_SSL", None)),
        ('mail.username', getattr(old_config, "MAIL_USERNAME", None)),
        ('mail.password', getattr(old_config, "MAIL_PASSWORD", None)),
        ('mail.noreply', getattr(old_config, "NOREPLY_EMAIL", None)),
        ('SCRAPE_TIMEOUT', getattr(old_config, "SCRAPE_TIMEOUT", None)),
        ('SCRAPE_PROXIES', getattr(old_config, "SCRAPE_PROXIES", None)),
        ('IMAGE_INTERVAL', getattr(old_config, "IMAGE_INTERVAL", None)),
        ('explorer.max_posts', getattr(old_config, "MAX_EXPLORER_POSTS", None)),
        # Processor and datasource settings have a different format in new database
        ('image_downloader.MAX_NUMBER_IMAGES', getattr(old_config, "MAX_NUMBER_IMAGES", None)),
        ('image_downloader_telegram.MAX_NUMBER_IMAGES', getattr(old_config, "MAX_NUMBER_IMAGES", None)),
        ('api.tumblr.consumer_key', getattr(old_config, "TUMBLR_CONSUMER_KEY", None)),
        ('api.tumblr.consumer_secret', getattr(old_config, "TUMBLR_CONSUMER_SECRET_KEY", None)),
        ('api.tumblr.key', getattr(old_config, "TUMBLR_API_KEY", None)),
        ('api.tumblr.secret_key', getattr(old_config, "TUMBLR_API_SECRET_KEY", None)),
        ('api.reddit.client_id', getattr(old_config, "REDDIT_API_CLIENTID", None)),
        ('api.reddit.secret', getattr(old_config, "REDDIT_API_SECRET", None)),
        ('tcat-auto-upload.TCAT_SERVER', getattr(old_config, "TCAT_SERVER", None)),
        ('tcat-auto-upload.TCAT_TOKEN', getattr(old_config, "TCAT_TOKEN", None)),
        ('tcat-auto-upload.TCAT_USERNAME', getattr(old_config, "TCAT_USERNAME", None)),
        ('tcat-auto-upload.TCAT_PASSWORD', getattr(old_config, "TCAT_PASSWORD", None)),
        ('pix-plot.PIXPLOT_SERVER', getattr(old_config, "PIXPLOT_SERVER", None)),
        # FlaskConfig are accessed from old_config slightly differently
        ('flask.flask_app', getattr(old_config.FlaskConfig, "FLASK_APP", None)),
        ('flask.server_name', getattr(old_config.FlaskConfig, "SERVER_NAME", None)),
        ('flask.secret_key', getattr(old_config.FlaskConfig, "SECRET_KEY", None)),
        ('flask.https', getattr(old_config.FlaskConfig, "SERVER_HTTPS", None)),
        ('flask.autologin.hostnames', getattr(old_config.FlaskConfig, "HOSTNAME_WHITELIST", None)),
        ('flask.autologin.api', getattr(old_config.FlaskConfig, "HOSTNAME_WHITELIST_API", None)),
        ('flask.autologin.name', getattr(old_config.FlaskConfig, "HOSTNAME_WHITELIST_NAME", None)),
        ]

    for name, setting in old_settings:
        if setting is not None:
            set_or_create_setting(name, setting, connection=connection, cursor=cursor, keep_connection_open=True)

    print('  Setting migrated to Database!')

# Close database connection
connection.close()

print("  Done!")
