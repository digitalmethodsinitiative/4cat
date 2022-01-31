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

@app.template_filter('timify_long')
def _jinja2_filter_timify_long(number):
	"""
	Make a number look like an indication of time

	:param number:  Number to convert. If the number is larger than the current
	UNIX timestamp, decrease by that amount
	:return str: A nice, string, for example `1 month, 3 weeks, 4 hours and 2 minutes`
	"""
	components = []
	if number > time.time():
		number = time.time() - number

	month_length = 30.42 * 86400
	months = math.floor(number / month_length)
	if months:
		components.append("%i month%s" % (months, "s" if months != 1 else ""))
		number -= (months * month_length)

	week_length = 7 * 86400
	weeks = math.floor(number / week_length)
	if weeks:
		components.append("%i week%s" % (weeks, "s" if weeks != 1 else ""))
		number -= (weeks * week_length)

	day_length = 86400
	days = math.floor(number / day_length)
	if days:
		components.append("%i day%s" % (days, "s" if days != 1 else ""))
		number -= (days * day_length)

	hour_length = 3600
	hours = math.floor(number / hour_length)
	if hours:
		components.append("%i hour%s" % (hours, "s" if hours != 1 else ""))
		number -= (hours * hour_length)

	minute_length = 60
	minutes = math.floor(number / minute_length)
	if minutes:
		components.append("%i minute%s" % (minutes, "s" if minutes != 1 else ""))

	last_str = components.pop()
	time_str = ""
	if components:
		time_str = ", ".join(components)
		time_str += " and "

	return time_str + last_str

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

@app.template_filter('post_field')
def _jinja2_filter_post_field(field, post):
	# Takes a value in between {{ two curly brackets }} and uses that
	# as a dictionary key. It then returns the corresponding value.
	
	matches = False
	formatted_field = field

	for key in re.findall(r"\{\{(.*?)\}\}", str(field)):

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

		formatted_field = formatted_field.replace("{{" + key + "}}", str(val))

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

	announcement_file = Path(config.PATH_ROOT, "ANNOUNCEMENT.md")

	return {
		"__datasources_config": config.DATASOURCES,
		"__has_https": config.FlaskConfig.SERVER_HTTPS,
		"__datenow": datetime.datetime.utcnow(),
		"__tool_name": config.TOOL_NAME,
		"__tool_name_long": config.TOOL_NAME_LONG,
		"__announcement": announcement_file.open().read().strip() if announcement_file.exists() else None,
		"__expire_datasets": config.EXPIRE_DATASETS if hasattr(config, "EXPIRE_DATASETS") else None,
		"__expire_optout": config.EXPIRE_ALLOW_OPTOUT if hasattr(config, "EXPIRE_ALLOW_OPTOUT") else None,
		"uniqid": uniqid
	}

