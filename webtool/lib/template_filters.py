import datetime
import markdown
import json
import uuid
import math
import os
import re
import requests

from urllib.parse import urlencode, urlparse
from webtool import app, config
from common.lib.helpers import timify_long
from common.config_manager import ConfigWrapper

from flask import request
from flask_login import current_user

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

@app.template_filter('4chan_image')
def _jinja2_filter_4chan_image(image_4chan, post_id, board, image_md5):

	plebs_boards = ["adv","f","hr","mlpol","mo","o","pol","s4s","sp","tg","trv","tv","x"]
	archivedmoe_boards = ["3","a","aco","adv","an","asp","b","bant","biz","c","can","cgl","ck","cm","co","cock","con","d","diy","e","f","fa","fap","fit","fitlit","g","gd","gif","h","hc","his","hm","hr","i","ic","int","jp","k","lgbt","lit","m","mlp","mlpol","mo","mtv","mu","n","news","o","out","outsoc","p","po","pol","pw","q","qa","qb","qst","r","r9k","s","s4s","sci","soc","sp","spa","t","tg","toy","trash","trv","tv","u","v","vg","vint","vip","vm","vmg","vp","vr","vrpg","vst","vt","w","wg","wsg","wsr","x","xs","y"]

	headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:61.0) Gecko/20100101 Firefox/61.0"}

	img_link = None
	thumb_link = image_4chan.split(".")
	thumb_link = thumb_link[0][:4] + "/" + thumb_link[0][4:6] + "/" + thumb_link[0] + "s." + thumb_link[1]

	# If the board is archived by 4plebs, check that site first
	if board in plebs_boards:

		# First we're going to try to get the image link through the 4plebs API.
		api_url = "https://archive.4plebs.org/_/api/chan/post/?board=%s&num=%s" % (board, post_id)
		try:
			api_json = requests.get(api_url, headers=headers)
		except requests.RequestException as e:
		 	pass
		if api_json.status_code != 200:
			pass
		try:
			api_json = json.loads(api_json.content)
			img_link = api_json.get("media", {}).get("thumb_link", "")
		except json.JSONDecodeError:
			pass
		if img_link:
			return img_link

		# If that doesn't work, we can check whether we can retrieve the image directly.
		# 4plebs has a back-referral system so that some filenames are translated.
		# This means direct linking won't work for every image without API retrieval.
		# So only show if we get a 200 status code.
		img_page = requests.get("https://img.4plebs.org/boards/%s/thumb/%s" % (board, thumb_link), headers=headers)
		if img_page.status_code == 200:
			return "https://img.4plebs.org/boards/%s/thumb/%s" % (board, thumb_link)

	# If the board is archived by archivedmoe, we can also check this resource
	if board in archivedmoe_boards:
		img_page = requests.get("https://archived.moe/files/%s/thumb/%s" % (board, thumb_link), headers=headers)
		if img_page.status_code == 200:
			return img_page

	# If we couldn't retrieve the thumbnail yet, then we'll just give a search link
	# and display it as a hidden image.
	image_md5 = image_md5.replace("/", "_")
	if board in plebs_boards:
		return "retrieve:http://archive.4plebs.org/_/search/image/" + image_md5
	# Archivedmoe as a last resort - has a lot of boards
	return "retrieve:https://archived.moe/_/search/image/" + image_md5



@app.template_filter('post_field')
def _jinja2_filter_post_field(field, post):
	# Extracts string values between {{ two curly brackets }} and uses that
	# as a dictionary key for the given dict. It then returns the corresponding value.
	# Mainly used in the Explorer.

	matches = False
	formatted_field = field

	field = str(field)
	
	for key in re.findall(r"\{\{(.*?)\}\}", field):

		original_key = key

		# Remove possible slice strings so we get the original key
		string_slice = None
		if "[" in original_key and "]" in original_key:
			string_slice = re.search(r"\[(.*?)\]", original_key)
			if string_slice:
				string_slice = string_slice.group(1)
				key = key.replace("[" + string_slice + "]", "")

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
		
		# Support some basic string slicing
		if string_slice:
			field = field.replace("[" + string_slice + "]", "")
			if ":" not in string_slice:
				string_slice = slice(int(string_slice), int(string_slice) + 1)
			else:
				sl = string_slice.split(":")
				if not sl[0] and sl[0] != "0":
					sl1 = 0
					sl2 = sl[1]
				elif not sl[-1]:
					sl1 = sl[0]
					sl2 = len(st)
				else:
					sl1 = sl[0]
					sl2 = sl[1]
				string_slice = slice(int(sl1), int(sl2))

		# Apply further filters, if present (e.g. lower)
		for extra_filter in extra_filters:
			
			extra_filter = extra_filter.strip()

			# We're going to parse possible parameters to pass to the filter
			# These are passed as unnamed variables to the function.
			params = ()
			if "(" in extra_filter:
				params = extra_filter.split("(")[-1][:-1].strip()
				extra_filter = extra_filter.split("(")[0]
				params = [p.strip() for p in params.split(",")]
				params = [post[param] for param in params]
			
			val = app.jinja_env.filters[extra_filter](val, *params)

		if string_slice:
			val = val[string_slice]

		# Extract single list item
		if isinstance(val, list) and len(val) == 1:
			val = val[0]

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
