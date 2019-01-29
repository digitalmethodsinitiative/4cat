import sys
import os

sys.path.insert(0, os.path.dirname(__file__) + '/../..')

from flask import Flask
from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from backend.lib.database import Database
from backend.lib.logger import Logger
from backend.lib.queue import JobQueue

login_manager = LoginManager()
app = Flask(__name__)
log = Logger()
db = Database(logger=log)
queue = JobQueue(logger=log, database=db)


# initialize openapi endpoint collector for later speficiation generation
from fourcat.openapi_collector import OpenAPICollector
openapi = OpenAPICollector(app)

# initialize rate limiter
limiter = Limiter(app, key_func=get_remote_address)

import config
import fourcat.access
import fourcat.views
import fourcat.api


if config.FlaskConfig.SECRET_KEY == "REPLACE_THIS":
	raise Exception("You need to set a FLASK_SECRET in config.py before running the webtool.")

app.config.from_object("config.FlaskConfig")
login_manager.init_app(app)
login_manager.login_view = "show_login"

if __name__ == "__main__":
	print('Starting server...')
	app.run(debug=True)
