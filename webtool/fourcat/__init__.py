from flask import Flask

app = Flask(__name__)

import config
import fourcat.views
import fourcat.api

app.config.from_object("config.FlaskConfig")

if __name__ == "__main__":
	print('Starting server...')
	app.run(debug=True)