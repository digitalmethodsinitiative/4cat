from flask import Flask

app = Flask(__name__)

import fourcat.views
import fourcat.api

app.config.from_object('config')

if __name__ == "__main__":
	print('Starting server...')
	app.run(debug=True)