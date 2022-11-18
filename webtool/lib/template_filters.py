import datetime
import markdown
import json
import time
import uuid
import math
import os
import re

from pathlib import Path
from urllib.parse import urlencode, urlparse
from webtool import app, db
from common.lib.helpers import timify_long

from flask_login import current_user

import common.config_manager as config

@app.template_filter('datetime')
def _jinja2_filter_datetime(date, fmt=None, wrap=True):
	date = datetime.datetime.utcfromtimestamp(date)
	format = "%d %b %Y" if not fmt else fmt
	formatted = date.strftime(format)

	if wrap:
		html_formatted = date.strftime("%Y-%m-%dT%H:%M:%S%z")
		return '<time datetime="' + html_formatted + '">' + formatted + '</time>'
	else:
		return formatted


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

@app.template_filter('commafy')
def _jinja2_filter_commafy(number):
	"""
	Applies thousands separator to ints.
	"""
	try:
		number = int(number)
	except TypeError:
		return number

	return f"{number:,}"

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

@app.template_filter('timify_long')
def _jinja2_filter_timify_long(number):
	"""
	Make a number look like an indication of time

	:param number:  Number to convert. If the number is larger than the current
	UNIX timestamp, decrease by that amount
	:return str: A nice, string, for example `1 month, 3 weeks, 4 hours and 2 minutes`
	"""
	return timify_long(number)

@app.template_filter("http_query")
def _jinja2_filter_httpquery(data):
	data = {key: data[key] for key in data if data[key]}

	try:
		return urlencode(data)
	except TypeError:
		return ""

@app.template_filter('markdown')
def _jinja2_filter_markdown(text):
	val = markdown.markdown(text)
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
		return config.get("flask." + property)
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
		format_precision = ".0f"
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

@app.template_filter('post_field')
def _jinja2_filter_post_field(field, post):
	# Extracts string values between {{ two curly brackets }} and uses that
	# as a dictionary key for the given dict. It then returns the corresponding value.
	# Mainly used in the Explorer.

	matches = False
	formatted_field = field

	for key in re.findall(r"\{\{(.*?)\}\}", str(field)):

		original_key = key

		# We're also gonna extract any other filters present
		extra_filters = []
		if "|" in key:
			extra_filters = key.split("|")[1:]
			key = key.split("|")[0]

		# They keys can also be subfields (e.g. "author.username")
		# So we're splitting and looping until we get the value.
		keys = key.split(".")
		val = post

		for k in keys:
			if isinstance(val, list):
				val = val[0]
			if isinstance(val, dict):
				val = val.get(k.strip(), "")

		# Return nothing if one of the fields is not found.
		# We see 0 as a valid value - e.g. '0 retweets'.
		if not val and val != 0:
			return ""

		# Apply further builtin filters, if present (e.g. lower)
		for extra_filter in extra_filters:
			extra_filter = extra_filter.strip()
			val = app.jinja_env.filters[extra_filter](val)
		
		formatted_field = formatted_field.replace("{{" + original_key + "}}", str(val))

	return formatted_field


@app.template_filter('parameter_str')
def _jinja2_filter_parameter_str(url):
	# Returns the current URL parameters as a valid string.

	params = urlparse(url).query
	if not params:
		return ""
	else:
		params = "?" + params

	return params

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

	notifications = current_user.get_notifications()

	return {
		"__datasources_config": config.get('4cat.datasources'),
		"__has_https": config.get("flask.https"),
		"__datenow": datetime.datetime.utcnow(),
		"__tool_name": config.get("4cat.name"),
		"__tool_name_long": config.get("4cat.name_long"),
		"__notifications": notifications,
		"__expire_datasets": config.get("expire.timeout"),
		"__expire_optout": config.get("expire.allow_optout"),
		"uniqid": uniqid
	}
