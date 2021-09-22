import datetime
import markdown
import json
import uuid
import math
import os

from pathlib import Path
from urllib.parse import urlencode
from webtool import app

from common.lib.helpers import strip_tags

import config


@app.template_filter('datetime')
def _jinja2_filter_datetime(date, fmt=None):
	date = datetime.datetime.utcfromtimestamp(date)
	format = "%d %b %Y" if not fmt else fmt
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

@app.template_filter('timify')
def _jinja2_filter_numberify(number):
	try:
		number = int(number)
	except TypeError:
		return number

	time_str = ""

	hours = math.floor(number / 3600)
	if hours > 0:
		time_str += "%ih " % hours
		number -= (hours * 3600)

	minutes = math.floor(number / 60)
	if minutes > 0:
		time_str += "%im " % minutes
		number -= (minutes * 60)

	seconds = number
	time_str += "%is " % seconds

	return time_str.strip()




@app.template_filter("http_query")
def _jinja2_filter_httpquery(data):
	data = {key: data[key] for key in data if data[key]}

	try:
		return urlencode(data)
	except TypeError:
		return ""


@app.template_filter('markdown')
def _jinja2_filter_markdown(text):
	text = "<p>" + text + "</p>"
	val = markdown.markdown(strip_tags(text))
	return val


@app.template_filter('isbool')
def _jinja2_filter_isbool(value):
	return isinstance(value, bool)

@app.template_filter('json')
def _jinja2_filter_json(data):
	return json.dumps(data)


@app.template_filter('config_override')
def _jinja2_filter_conf(data, property=""):
	try:
		return getattr(config.FlaskConfig, property)
	except AttributeError:
		return data

@app.template_filter('filesize')
def _jinja2_filter_filesize(file, short=False):
	try:
		stats = os.stat(file)
	except FileNotFoundError:
		return "0 bytes"

	bytes = stats.st_size
	format_precision = ".2f" if not short else ".0f"

	if bytes > (1024 * 1024 * 1024):
		return "{0:.2f}GB".format(bytes / 1024 / 1024 / 1024)
	if bytes > (1024 * 1024):
		return ("{0:" + format_precision + "}MB").format(bytes / 1024 / 1024)
	elif bytes > 1024:
		return ("{0:" + format_precision + "}kB").format(bytes / 1024)
	elif short:
		return "%iB" % bytes
	else:
		return "%i bytes" % bytes

@app.template_filter('filesize_short')
def _jinja2_filter_filesize_short(file):
	return _jinja2_filter_filesize(file, True)

@app.template_filter('ext2noun')
def _jinja2_filter_extension_to_noun(ext):
	if ext == "csv":
		return "row"
	elif ext == "gdf":
		return "node"
	elif ext == "zip":
		return "file"
	else:
		return "item"

@app.template_filter('hasattr')
def _jinja2_filter_hasattr(obj, attribute):
	return hasattr(obj, attribute)

@app.context_processor
def inject_now():
	def uniqid():
		"""
		Return a unique string (UUID)

		:return str:
		"""
		return str(uuid.uuid4())

	announcement_file = Path(config.PATH_ROOT, "ANNOUNCEMENT.md")

	return {
		"__datasources_config": config.DATASOURCES,
		"__has_https": config.FlaskConfig.SERVER_HTTPS,
		"__datenow": datetime.datetime.utcnow(),
		"__tool_name": config.TOOL_NAME,
		"__tool_name_long": config.TOOL_NAME_LONG,
		"__announcement": announcement_file.open().read().strip() if announcement_file.exists() else None,
		"uniqid": uniqid
	}
