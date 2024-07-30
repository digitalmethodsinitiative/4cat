import datetime
import markdown
import json
import uuid
import math
import os
import re
import requests
import regex

from urllib.parse import urlencode, urlparse
from webtool import app, config
from common.lib.helpers import timify_long
from common.config_manager import ConfigWrapper

from pathlib import Path
from flask import request
from flask_login import current_user
from ural import urls_from_text

@app.template_filter('datetime')
def _jinja2_filter_datetime(date, fmt=None, wrap=True):
	if isinstance(date, str):
		try:
			date = int(date)
		except ValueError:
			return date

	try:
		date = datetime.datetime.utcfromtimestamp(date)
	except (ValueError, OverflowError):
		return date

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
def _jinja2_filter_timify(number):
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

@app.template_filter("fromjson")
def _jinja2_filter_fromjson(data):
	try:
		return json.loads(data)
	except TypeError:
		return data

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
		return config.get("flask." + property, user=current_user)
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

@app.template_filter('social_mediafy')
def _jinja2_filter_social_mediafy(body, datasource=""):
	# Adds links to a text body with hashtags, @-mentions, and URLs
	# A data source must be given to generate the correct URLs. 

	if not datasource:
		return body

	# Base URLs after which tags and @-mentions follow, per platform
	base_urls = {
		"twitter": {
			"hashtag": "https://twitter.com/hashtag/",
			"mention": "https://twitter.com/"
		},
		"tiktok": {
			"hashtag": "https://tiktok.com/tag/",
			"mention": "https://tiktok.com/@"
		},
		"instagram": {
			"hasthag": "https://instagram.com/explore/tags/",
			"mention": "https://instagram.com/"
		},
		"tumblr": {
			"mention": "https://tumblr.com/",
			"markdown": True
			# Hashtags aren't linked in the post body
		},
		"linkedin": {
			"hashtag": "https://linkedin.com/feed/hashtag/?keywords=",
			"mention": "https://linkedin.com/in/"
		},
		"telegram": {
			"markdown": True
		}
	}

	# Supported data sources
	known_datasources = list(base_urls.keys())
	if datasource not in known_datasources:
		return body

	# Add URL links
	if not base_urls[datasource].get("markdown"):
		for url in urls_from_text(body):
			body = re.sub(url, "<a href='%s' target='_blank'>%s</a>" % (url, url), body)

	# Add hashtag links
	if "hashtag"  in base_urls[datasource]:
		tags = re.findall(r"#[\w0-9]+", body)
		# We're sorting tags by length so we don't incorrectly
		# replace tags that are a substring of another, longer tag.
		tags = sorted(tags, key=lambda x: len(x), reverse=True)
		for tag in tags:
			# Match the string, but not if it's preceded by a >, which indicates that we've already added an anchor tag.
			body = re.sub(r"(?<!'>)(" + tag + ")", "<a href='%s' target='_blank'>%s</a>" % (base_urls[datasource]["hashtag"] + tag[1:], tag), body)

	# Add @-mention links
	if "mention"  in base_urls[datasource]:
		mentions = re.findall(r"@[\w0-9-]+", body)
		mentions = sorted(mentions, key=lambda x: len(x), reverse=True)
		for mention in mentions:
			body = re.sub(r"(?<!>)(" + mention + ")", "<a href='%s' target='_blank'>%s</a>" % (base_urls[datasource]["mention"] + mention[1:], mention), body)

	return body

@app.template_filter('string_counter')
def _jinja2_filter_string_counter(string, emoji=False):
	# Returns a dictionary with counts of characters in a string. 
	# Also handles emojis.

	# We need to convert multi-character emojis ("graphemes") to one character.
	if emoji == True:
		string = regex.finditer(r"\X", string) # \X matches graphemes
		string = [m.group(0) for m in string]

	# Count 'em
	counter = {}
	for s in string:
		if s not in counter:
			counter[s] = 0
		counter[s] += 1

	return counter 

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

	wrapped_config = ConfigWrapper(config, user=current_user, request=request)

	cv_path = wrapped_config.get("PATH_ROOT").joinpath("config/.current-version")
	if cv_path.exists():
		with cv_path.open() as infile:
			version = infile.readline().strip()
	else:
		version = "???"

	return {
		"__has_https": wrapped_config.get("flask.https"),
		"__datenow": datetime.datetime.utcnow(),
		"__notifications": current_user.get_notifications(),
		"__user_config": lambda setting: wrapped_config.get(setting),
		"__user_cp_access": any([wrapped_config.get(p) for p in config.config_definition.keys() if p.startswith("privileges.admin")]),
		"__version": version,
		"uniqid": uniqid
	}
