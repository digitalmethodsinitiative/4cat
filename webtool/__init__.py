import configparser
import subprocess
import sys
import os
import logging

from functools import partial
from pathlib import Path

# first-run.py ensures everything is set up right when running 4CAT for the first time
first_run = Path(__file__).parent.parent.joinpath("helper-scripts", "first-run.py")
result = subprocess.run([sys.executable, str(first_run)], stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE)

if result.returncode != 0:
    print("Unexpected error while preparing 4CAT. You may need to re-install 4CAT.")
    print("stdout:\n".join(["  " + line for line in result.stdout.decode("utf-8").split("\n")]))
    print("stderr:\n".join(["  " + line for line in result.stderr.decode("utf-8").split("\n")]))
    exit(1)

from flask import Flask
from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import config

from common.lib.database import Database
from common.lib.logger import Logger
from common.lib.queue import JobQueue

from webtool.lib.user import User

# initialize global objects for interacting with all the things
database_name = config.DB_NAME_TEST if hasattr(config.FlaskConfig,
                                               "DEBUG") and config.FlaskConfig.DEBUG == "Test" else config.DB_NAME
login_manager = LoginManager()
app = Flask(__name__)

# Set up logging for Gunicorn; only run w/ Docker
if hasattr(config, "CONFIG_FILE") and os.path.exists(config.CONFIG_FILE):
    # rename 4cat.log to 4cat_frontend.log
    # Normally this is mostly empty; could combine it, but may be useful to identify processes running on both front and backend
    log = Logger(filename='frontend_4cat.log')

    docker_config_parser = configparser.ConfigParser()
    docker_config_parser.read(config.CONFIG_FILE)
    if docker_config_parser['DOCKER'].getboolean('use_docker_config'):
        # Add Gunicorn error log to main app logger
        gunicorn_logger = logging.getLogger('gunicorn.error')
        app.logger.handlers = gunicorn_logger.handlers
        app.logger.setLevel(gunicorn_logger.level) # debug is int 10

        # Gunicorn Error Log file
        error_file_path = Path(config.PATH_ROOT, config.PATH_LOGS, 'error_gunicorn.log')
        file_handler = logging.handlers.RotatingFileHandler(
                                                            filename=error_file_path,
                                                            maxBytes=int( 50 * 1024 * 1024),
                                                            backupCount= 1,
                                                            )
        logFormatter = logging.Formatter("%(asctime)s [%(levelname)-5.5s]  %(message)s")
        file_handler.setFormatter(logFormatter)
        app.logger.addHandler(file_handler)

else:
    log = Logger()

db = Database(logger=log, dbname=database_name, appname="frontend")
queue = JobQueue(logger=log, database=db)

# initialize openapi endpoint collector for later specification generation
from webtool.lib.openapi_collector import OpenAPICollector
openapi = OpenAPICollector(app)

# initialize rate limiter
limiter = Limiter(app, key_func=get_remote_address)

# make sure a secret key was set in the config file, for secure session cookies
if config.FlaskConfig.SECRET_KEY == "REPLACE_THIS":
    raise Exception("You need to set a FLASK_SECRET in config.py before running the web tool.")

# initialize login manager
app.config.from_object("config.FlaskConfig")
login_manager.anonymous_user = partial(User.get_by_name, db=db, name="anonymous")
login_manager.init_app(app)
login_manager.login_view = "show_login"

# import all views
import webtool.views.views_misc
import webtool.views.views_dataset
import webtool.views.views_admin
import webtool.views.views_processors
import webtool.views.access
import webtool.views.api_explorer
import webtool.views.api_standalone
import webtool.views.api_tool

# import custom jinja2 template filters
import webtool.lib.template_filters

# run it
if __name__ == "__main__":
    print('Starting server...')
    app.run(host='0.0.0.0', debug=True)
