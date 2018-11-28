import atexit
import sys
import os

sys.path.insert(0, os.path.dirname(__file__) + '/../..')

from flask import Flask
from flask_login import LoginManager

from backend.lib.database import Database
from backend.lib.logger import Logger

login_manager = LoginManager()
app = Flask(__name__)
log = Logger()
db = Database(logger=log)

import config
import fourcat.access
import fourcat.views
import fourcat.api


def shutdown():
	"""
	This function runs when the app shuts down

	Right now, all it does is properly close the database connection.
	"""
	db.close()


if config.FlaskConfig.SECRET_KEY == "REPLACE_THIS":
	raise Exception("You need to set a FLASK_SECRET in config.py before running the webtool.")

app.config.from_object("config.FlaskConfig")
atexit.register(shutdown)
login_manager.init_app(app)
login_manager.login_view = "show_login"

if __name__ == "__main__":
	print('Starting server...')
	app.run(debug=True)
