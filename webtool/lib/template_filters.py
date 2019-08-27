import datetime
import markdown
import json

from urllib.parse import urlencode
from webtool import app

import config


@app.template_filter('datetime')
def _jinja2_filter_datetime(date, fmt=None):
	date = datetime.datetime.fromtimestamp(date)
	format = "%d-%m-%Y" if not fmt else fmt
	return date.strftime(format)


@app.template_filter('numberify')
def _jinja2_filter_numberify(number):
	try:
		number = int(number)
	except TypeError:
		return number

	if number > 1000000000:
		return "{0:.1f}".format(number / 1000000000) + "b"
	elif number > 1000000:
		return str(int(number / 1000000)) + "m"
	elif number > 1000:
		return str(int(number / 1000)) + "k"

	return str(number)


@app.template_filter("http_query")
def _jinja2_filter_httpquery(data):
	data = {key: data[key] for key in data if data[key]}

	try:
		return urlencode(data)
	except TypeError:
		return ""


@app.template_filter('markdown')
def _jinja2_filter_markdown(text):
	return markdown.markdown(text)


@app.template_filter('json')
def _jinja2_filter_json(data):
	return json.dumps(data)


@app.template_filter('config_override')
def _jinja2_filter_conf(data, property=""):
	try:
		return getattr(config.FlaskConfig, property)
	except AttributeError:
		return data


@app.context_processor
def inject_now():
	return {'__datenow': datetime.datetime.utcnow()}
