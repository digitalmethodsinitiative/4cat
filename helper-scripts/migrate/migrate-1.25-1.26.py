# Add 'is_deactivated' column to user table
import sys
import os
import configparser

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "'/../..")
from common.lib.database import Database
from common.lib.logger import Logger

log = Logger(output=True)

print("  Checking if preexisting config.py file...")
transfer_settings = False
try:
    import config as old_config
    transfer_settings = True
    print("  ...Yes, prexisting settings exist.")
except (SyntaxError, ImportError) as e:
    print("  ...No prexisting settings exist.")

if transfer_settings:
    db = Database(logger=log, dbname=old_config.DB_NAME, user=old_config.DB_USER, password=old_config.DB_PASSWORD, host=old_config.DB_HOST, port=old_config.DB_PORT, appname="4cat-migrate")
else:
    import common.config_manager as config
    db = Database(logger=log, dbname=config.get('DB_NAME'), user=config.get('DB_USER'), password=config.get('DB_PASSWORD'), host=config.get('DB_HOST'), port=config.get('DB_PORT'), appname="4cat-migrate")

print("  Checking if fourcat_settings table exists...")
has_table = db.fetchone("SELECT EXISTS (SELECT FROM fourcat_settings)")
if not has_table["exists"]:
    print("  ...No, adding table fourcat_setttings.")
    db.execute("""CREATE TABLE IF NOT EXISTS fourcat_settings (
      name                   TEXT UNIQUE PRIMARY KEY,
      value                  TEXT DEFAULT '{}'
    )""")
    db.commit()
else:
    print("  ...Yes, fourcat_settings table already exists.")

if transfer_settings:
    print("  Moving settings to database...")
    # FIRST update config_defaults.ini or docker_config.ini
    # Check if Docker
    USING_DOCKER = True
    configfile_to_save = old_config.DOCKER_CONFIG_FILE
    if os.path.exists(old_config.DOCKER_CONFIG_FILE):
      config_reader = configparser.ConfigParser()
      config_reader.read(old_config.DOCKER_CONFIG_FILE)
      if not config_reader['DOCKER'].getboolean('use_docker_config'):
          # Not using docker
          USING_DOCKER = False
          configfile_to_save = 'backend/config_defaults.ini'
          config_reader.read(configfile_to_save)

    # Update DB info
    if not config_reader.has_section('DATABASE'):
        config_reader.add_section('DATABASE')
    if old_config.DB_HOST:
        config_reader['DATABASE']['db_host'] = old_config.DB_HOST
    if old_config.DB_PORT:
        config_reader['DATABASE']['db_port'] = old_config.DB_PORT
    if old_config.DB_USER:
        config_reader['DATABASE']['db_user'] = old_config.DB_USER
    if old_config.DB_PASSWORD:
        config_reader['DATABASE']['db_password'] = old_config.DB_PASSWORD
    if old_config.DB_NAME:
        config_reader['DATABASE']['db_name'] = old_config.DB_NAME

    # Update API info
    if not config_reader.has_section('API'):
        config_reader.add_section('API')
    if old_config.API_HOST:
        config_reader['API']['api_host'] = old_config.API_HOST
    if old_config.API_PORT:
        config_reader['API']['api_port'] = old_config.API_PORT

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
        config_reader['GENERATE']['anonymisation_salt'] = old_config.ANONYMISATION_SALT
    if old_config.SECRET_KEY:
        config_reader['GENERATE']['secret_key'] = old_config.SECRET_KEY

    # Save config file
    with open(configfile_to_save, 'w') as configfile:
        config_reader.write(configfile)

    # UPDATE Database with other settings
    if not config:
        import common.config_manager as config
    QD = config.QuickDatabase()

    old_settings = [
        ('DATASOURCES', old_config.DATASOURCES),
        ('YOUTUBE_API_SERVICE_NAME', old_config.YOUTUBE_API_SERVICE_NAME),
        ('YOUTUBE_API_VERSION', old_config.YOUTUBE_API_VERSION),
        ('YOUTUBE_DEVELOPER_KEY', old_config.YOUTUBE_DEVELOPER_KEY),
        ('TOOL_NAME', old_config.TOOL_NAME),
        ('TOOL_NAME_LONG', old_config.TOOL_NAME_LONG),
        ('PATH_VERSION', old_config.PATH_VERSION),
        ('GITHUB_URL', old_config.GITHUB_URL),
        ('EXPIRE_DATASETS', old_config.EXPIRE_DATASETS),
        ('EXPIRE_ALLOW_OPTOUT', old_config.EXPIRE_ALLOW_OPTOUT),
        ('WARN_INTERVAL', old_config.WARN_INTERVAL),
        ('WARN_LEVEL', old_config.WARN_LEVEL),
        ('WARN_SLACK_URL', old_config.WARN_SLACK_URL),
        ('WARN_EMAILS', old_config.WARN_EMAILS),
        ('ADMIN_EMAILS', old_config.ADMIN_EMAILS),
        ('MAILHOST', old_config.MAILHOST),
        ('MAIL_SSL', old_config.MAIL_SSL),
        ('MAIL_USERNAME', old_config.MAIL_USERNAME),
        ('MAIL_PASSWORD', old_config.MAIL_PASSWORD),
        ('NOREPLY_EMAIL', old_config.NOREPLY_EMAIL),
        ('SCRAPE_TIMEOUT', old_config.SCRAPE_TIMEOUT),
        ('SCRAPE_PROXIES', old_config.SCRAPE_PROXIES),
        ('IMAGE_INTERVAL', old_config.IMAGE_INTERVAL),
        ('MAX_EXPLORER_POSTS', old_config.MAX_EXPLORER_POSTS),
        # Processor and datasource settings have a different format in new database
        ('image_downloader.MAX_NUMBER_IMAGES', old_config.MAX_NUMBER_IMAGES),
        ('image_downloader_telegram.MAX_NUMBER_IMAGES', old_config.MAX_NUMBER_IMAGES),
        ('tumblr-search.TUMBLR_CONSUMER_KEY', old_config.TUMBLR_CONSUMER_KEY),
        ('tumblr-search.TUMBLR_CONSUMER_SECRET_KEY', old_config.TUMBLR_CONSUMER_SECRET_KEY),
        ('tumblr-search.TUMBLR_API_KEY', old_config.TUMBLR_API_KEY),
        ('tumblr-search.TUMBLR_API_SECRET_KEY', old_config.TUMBLR_API_SECRET_KEY),
        ('get-reddit-votes.REDDIT_API_CLIENTID', old_config.REDDIT_API_CLIENTID),
        ('get-reddit-votes.REDDIT_API_SECRET', old_config.REDDIT_API_SECRET),
        ('tcat-auto-upload.TCAT_SERVER', old_config.TCAT_SERVER),
        ('tcat-auto-upload.TCAT_TOKEN', old_config.TCAT_TOKEN),
        ('tcat-auto-upload.TCAT_USERNAME', old_config.TCAT_USERNAME),
        ('tcat-auto-upload.TCAT_PASSWORD', old_config.TCAT_PASSWORD),
        ('pix-plot.PIXPLOT_SERVER', old_config.PIXPLOT_SERVER),
        # FlaskConfig are accessed from old_config slightly differently
        ('FLASK_APP', old_config.FlaskConfig.FLASK_APP),
        ('SERVER_NAME', old_config.FlaskConfig.SERVER_NAME),
        ('SERVER_HTTPS', old_config.FlaskConfig.SERVER_HTTPS),
        ('HOSTNAME_WHITELIST', old_config.FlaskConfig.HOSTNAME_WHITELIST),
        ('HOSTNAME_WHITELIST_API', old_config.FlaskConfig.HOSTNAME_WHITELIST_API),
        ('HOSTNAME_WHITELIST_NAME', old_config.FlaskConfig.HOSTNAME_WHITELIST_NAME),
        ]

    for name, setting in old_settings:
        if setting:
            config.set_or_create_setting(name, setting, connection=QD.connection, cursor=QD.cursor, keep_connection_open=True)

    # Close connection
    if QD.connection:
        QD.close()
    print('Setting migrated to Database!')

print("  Done!")
