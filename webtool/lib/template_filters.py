import datetime

import json
import ural
import uuid
import math
import os
import re
import requests
import regex

from urllib.parse import urlencode, urlparse
from webtool.lib.helpers import parse_markdown
from common.lib.helpers import timify, ellipsiate

from flask import current_app, g
from flask_login import current_user
from ural import urls_from_text

@current_app.template_filter('datetime')
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


@current_app.template_filter('numberify')
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

@current_app.template_filter('commafy')
def _jinja2_filter_commafy(number):
	"""
	Applies thousands separator to ints.
	"""
	try:
		number = int(number)
	except TypeError:
		return number

	return f"{number:,}"

@current_app.template_filter('timify')
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

@current_app.template_filter('timify_long')
def _jinja2_filter_timify_long(number):
	"""
	Make a number look like an indication of time

	:param number:  Number to convert. If the number is larger than the current
	UNIX timestamp, decrease by that amount
	:return str: A nice, string, for example `1 month, 3 weeks, 4 hours and 2 minutes`
	"""
	return timify(number)

@current_app.template_filter("fromjson")
def _jinja2_filter_fromjson(data):
	try:
		return json.loads(data)
	except TypeError:
		return data

@current_app.template_filter("http_query")
def _jinja2_filter_httpquery(data):
	data = {key: data[key] for key in data if data[key]}

	try:
		return urlencode(data)
	except TypeError:
		return ""

@current_app.template_filter("add_colour")
def _jinja2_add_colours(data):
	"""
	Add colour preview to hexadecimal colour values.

	Cute little preview for #FF0099-like strings. Used (at time of writing) for
	Pinterest data, which has a "dominant colour" field.

	Only works on strings that are *just* the value, to avoid messing up HTML
	etc

	:param str data:  String
	:return str:  HTML
	"""
	if type(data) is not str or not re.match(r"#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})\b", data):
		return data

	return f'<span class="colour-preview"><i style="background:{data}" aria-hidden="true"></i> {data}</span>'

@current_app.template_filter("add_ahref")
def _jinja2_filter_add_ahref(content, ellipsiate=0):
	"""
	Add HTML links to text

	Replaces URLs with a clickable link

	:param str content:  Text to parse
	:return str:  Parsed text
	"""
	try:
		content = str(content)
	except ValueError:
		return content

	result_content = ""
	# ural.urls_from_text() cannot handle commas (comma + space seems to work more consistantly); more powerful comma-separated list here:
	# https://github.com/digitalmethodsinitiative/4cat_web_studies_extensions/blob/3b67237c0d5ca7fa1af30590363c424f68af0ac5/selenium_scraper.py#L479
	for pos_link in content.split(","):
		for link in set(ural.urls_from_text(pos_link)):
			if ellipsiate > 0:
				link_text = _jinja2_filter_ellipsiate(link, ellipsiate, True, "[&hellip;]")
			else:
				link_text = link
			result_content += (("," if result_content else "") + pos_link.replace(link, f'<a href="{link.replace("<", "%3C").replace(">", "%3E").replace(chr(34), "%22")}" rel="external">{link_text}</a>'))
	return result_content

@current_app.template_filter('markdown',)
def _jinja2_filter_markdown(text, trim_container=False):
	return parse_markdown(text, trim_container)

@current_app.template_filter('isbool')
def _jinja2_filter_isbool(value):
	return isinstance(value, bool)

@current_app.template_filter('json')
def _jinja2_filter_json(data):
	return json.dumps(data)


@current_app.template_filter('config_override')
def _jinja2_filter_conf(data, property=""):
	try:
		return g.config.get("flask." + property, user=current_user)
	except AttributeError:
		return data

@current_app.template_filter('filesize')
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

@current_app.template_filter('filesize_short')
def _jinja2_filter_filesize_short(file):
	return _jinja2_filter_filesize(file, True)

@current_app.template_filter('ext2noun')
def _jinja2_filter_extension_to_noun(ext):
	if ext == "csv":
		return "row"
	elif ext == "gdf":
		return "node"
	elif ext == "zip":
		return "file"
	else:
		return "item"

@current_app.template_filter("ellipsiate")
def _jinja2_filter_ellipsiate(*args, **kwargs):
	return ellipsiate(*args, **kwargs)


@current_app.template_filter('4chan_image')
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
		api_json = None
		try:
			api_json = requests.get(api_url, headers=headers)
		except requests.RequestException:
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


@current_app.template_filter('social_mediafy')
def _jinja2_filter_social_mediafy(body: str, datasource="") -> str:
	"""
	Adds links to a text body with hashtags, @-mentions, and URLs.
	A data source must be given to generate the correct URLs.

	:param str body:  Text to parse
	:param str datasource:  Name of the data source (e.g. "twitter")

	:return str:  Parsed text
	"""

	if not datasource:
		return body

	if not body:
		return body

	# Base URLs after which tags and @-mentions follow, per platform
	base_urls = {
		"twitter": {
			"hashtag": "https://x.com/hashtag/",
			"mention": "https://x.com/"
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
		},
		"bsky": {
			"hashtag": "https://bsky.app/hashtag/",
			"mention": "https://bsky.app/profile/",
		}
	}

	# Supported data sources
	known_datasources = list(base_urls.keys())
	datasource = datasource.replace("-search", "").replace("-import", "")

	if datasource not in known_datasources:
		return body

	# Add URL links
	if not base_urls[datasource].get("markdown"):
		for url in urls_from_text(body):
			body = re.sub(url, "<a href='%s' target='_blank'>%s</a>" % (url, url), body)

	# Add hashtag links
	if "hashtag" in base_urls[datasource]:
		tags = re.findall(r"#[\w0-9]+", body)
		# We're sorting tags by length so we don't incorrectly
		# replace tags that are a substring of another, longer tag.
		tags = sorted(tags, key=lambda x: len(x), reverse=True)
		for tag in tags:
			# Match the string, but not if it's preceded by a >, which indicates that we've already added an anchor tag.
			body = re.sub(r"(?<!'>)(" + tag + ")",
						  "<a href='%s' target='_blank'>%s</a>" % (base_urls[datasource]["hashtag"] + tag[1:], tag),
						  body)

	# Add @-mention links
	if "mention" in base_urls[datasource]:
		if datasource == "bsky":
			mentions = re.findall(r"@[\w0-9-.]+", body)
		else:
			mentions = re.findall(r"@[\w0-9-]+", body)
		mentions = sorted(mentions, key=lambda x: len(x), reverse=True)
		for mention in mentions:
			body = re.sub(r"(?<!>)(" + mention + ")", "<a href='%s' target='_blank'>%s</a>" % (
			base_urls[datasource]["mention"] + mention[1:], mention), body)

	return body


@current_app.template_filter('string_counter')
def _jinja2_filter_string_counter(string, emoji=False):
	# Returns a dictionary with counts of characters in a string.
	# Also handles emojis.

	# We need to convert multi-character emojis ("graphemes") to one character.
	if emoji:
		string = regex.finditer(r"\X", string) # \X matches graphemes
		string = [m.group(0) for m in string]

	# Count 'em
	counter = {}
	for s in string:
		if s not in counter:
			counter[s] = 0
		counter[s] += 1

	return counter

@current_app.template_filter('parameter_str')
def _jinja2_filter_parameter_str(url):
	# Returns the current URL parameters as a valid string.

	params = urlparse(url).query
	if not params:
		return ""
	else:
		params = "?" + params

	return params

@current_app.template_filter('hasattr')
def _jinja2_filter_hasattr(obj, attribute):
	return hasattr(obj, attribute)

@current_app.context_processor
def inject_now():
	def uniqid():
		"""
		Return a unique string (UUID)

		:return str:
		"""
		return str(uuid.uuid4())

	cv_path = g.config.get("PATH_ROOT").joinpath("config/.current-version")
	if cv_path.exists():
		with cv_path.open() as infile:
			version = infile.readline().strip()
	else:
		version = "???"


	return {
		"__has_https": g.config.get("flask.https"),
		"__datenow": datetime.datetime.utcnow(),
		"__notifications": current_user.get_notifications(),
		"__user_config": lambda setting: g.config.get(setting),
		"__config": g.config,
		"__user_cp_access": any([g.config.get(p) for p in g.config.config_definition.keys() if p.startswith("privileges.admin")]),
		"__version": version,
		"uniqid": uniqid
	}

@current_app.template_filter('log')
def _jinja2_filter_log(text):
	current_app.logger.info(text)
