from flask import Flask
from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import config

from common.lib.database import Database
from common.lib.logger import Logger
from common.lib.queue import JobQueue

database_name = config.DB_NAME_TEST if hasattr(config.FlaskConfig, "DEBUG") and config.FlaskConfig.DEBUG == "Test" else config.DB_NAME
login_manager = LoginManager()
app = Flask(__name__)
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
login_manager.init_app(app)
login_manager.login_view = "show_login"

# import all views
import webtool.access
import webtool.views
import webtool.views_admin
import webtool.api_tool
import webtool.api_data
import webtool.api_standalone

# import custom jinja2 template filters
import webtool.lib.template_filters

# run it
if __name__ == "__main__":
	print('Starting server...')
	app.run(host='0.0.0.0', debug=True)
