"""
General helper functions for Flask templating and 4CAT views
"""
import datetime
import colorsys
import math
import csv
import re

from functools import wraps
from math import ceil
from calendar import monthrange
from flask_login import current_user
from flask import (current_app, request, jsonify)
from PIL import Image, ImageColor, ImageOps
from pathlib import Path

from common.config_manager import config
csv.field_size_limit(1024 * 1024 * 1024)

class Pagination(object):
	"""
	Provide pagination
	"""

	def __init__(self, page, per_page, total_count, route="show_results"):
		"""
		Set up pagination object

		:param int page:  Current page
		:param int per_page:  Items per page
		:param int total_count:  Total number of items
		:param str route:  Route to call url_for for to prepend to page links
		"""
		self.page = page
		self.per_page = per_page
		self.total_count = total_count
		self.route = route

	@property
	def pages(self):
		"""
		:return int:  Number of pages in view
		"""
		return int(ceil(self.total_count / float(self.per_page)))

	@property
	def has_prev(self):
		"""
		:return bool:  Is there a previous page?
		"""
		return self.page > 1

	@property
	def has_next(self):
		"""
		:return bool:  Is there a next page?
		"""
		return self.page < self.pages

	def iter_pages(self, left_edge=2, left_current=2, right_current=5, right_edge=2):
		"""
		Page iterator

		Yields page numbers, or none if no further page is available

		:param left_edge:  Left edge of pages that may be returned
		:param left_current:  Current left edge
		:param right_current:  Current right edge
		:param right_edge:  Right edge of pages that may be returned
		:return:  A page number, or None
		"""
		last = 0
		for num in range(1, self.pages + 1):
			if num <= left_edge or \
					(num > self.page - left_current - 1 and \
					 num < self.page + right_current) or \
					num > self.pages - right_edge:
				if last + 1 != num:
					yield None
				yield num
				last = num


def error(code=200, **kwargs):
	"""
	Custom HTTP response

	:param code:  HTTP status code
	:param kwargs:  Any items to include in the response
	:return:  JSON object to be used as Flask response
	"""
	response = jsonify(kwargs)
	response.status_code = code
	return response


def string_to_timestamp(string):
	"""
	Convert dd-mm-yyyy date to unix time

	:param string: Date string to parse
	:return: The unix time, or 0 if value could not be parsed
	"""
	bits = string.split("-")
	if re.match(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", string):
		bits = list(reversed(bits))

	if len(bits) != 3:
		return 0

	try:
		day = int(bits[0])
		month = int(bits[1])
		year = int(bits[2])
		date = datetime.datetime(year, month, day)
	except ValueError:
		return 0

	return int(date.timestamp())

def pad_interval(intervals, first_interval=None, last_interval=None):
	"""
	Pad an interval so all intermediate intervals are filled

	:param dict intervals:  A dictionary, with dates (YYYY{-MM}{-DD}) as keys
	and a numerical value.
	:param first_interval:
	:param last_interval:
	:return:
	"""
	missing = 0
	test_key = list(intervals.keys())[0]

	# first determine the boundaries of the interval
	# these may be passed as parameters, or they can be inferred from the
	# interval given

	if first_interval:
		first_interval = str(first_interval)
		first_year = int(first_interval[0:4])
		if len(first_interval) > 4:
			first_month = int(first_interval[5:7])
		if len(first_interval) > 7:
			first_day = int(first_interval[8:10])
	else:
		first_year = min([int(i[0:4]) for i in intervals])
		if len(test_key) > 4:
			first_month = min([int(i[5:7]) for i in intervals if int(i[0:4]) == first_year])
		if len(test_key) > 7:
			first_day = min(
				[int(i[8:10]) for i in intervals if int(i[0:4]) == first_year and int(i[5:7]) == first_month])
	if last_interval:
		last_interval = str(last_interval)
		last_year = int(last_interval[0:4])
		if len(last_interval) > 4:
			last_month = int(last_interval[5:7])
		if len(last_interval) > 7:
			last_day = int(last_interval[8:10])
	else:
		last_year = max([int(i[0:4]) for i in intervals])
		if len(test_key) > 4:
			last_month = max([int(i[5:7]) for i in intervals if int(i[0:4]) == last_year])
		if len(test_key) > 7:
			last_day = max(
				[int(i[8:10]) for i in intervals if int(i[0:4]) == last_year and int(i[5:7]) == last_month])

	if re.match(r"^[0-9]{4}$", test_key):
		# years are quite straightforward
		for year in range(first_year, last_year + 1):
			if str(year) not in intervals:
				intervals[str(year)] = 0
				missing += 1

	elif re.match(r"^[0-9]{4}-[0-9]{2}(-[0-9]{2})?", test_key):
		# more granular intervals require the following monstrosity to
		# ensure all intervals are available for every single graph
		has_day = re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}", test_key)

		for year in range(first_year, last_year + 1):
			start_month = first_month if year == first_year else 1
			end_month = last_month if year == last_year else 12

			for month in range(start_month, end_month + 1):
				key = str(year) + "-" + str(month).zfill(2)
				if not has_day:
					if key not in intervals:
						intervals[key] = 0
						missing += 1
				else:
					start_day = first_day if year == first_year and month == first_month else 1
					end_day = last_day if year == last_year and month == last_month else \
						monthrange(year, month)[1]

					for day in range(start_day, end_day + 1):
						day_key = key + "-" + str(day).zfill(2)
						if day_key not in intervals:
							intervals[day_key] = 0
							missing += 1

	# sort while we're at it
	intervals = {key: intervals[key] for key in sorted(intervals)}

	return missing, intervals

def make_html_colour(rgb):
	"""
	Make HTML colour code from RGB values

	Turns an array of three 0-1 RGB values
	:param rgb:
	:return:
	"""
	colour = "#"
	for bit in rgb:
		bit *= 255
		bit = int(bit)
		colour += str(hex(bit)).split("x")[1].zfill(2).upper()

	return colour


def new_favicon_color(color, input_filepath="favicon-bw.ico", output_filepath="favicon.ico"):
	"""
	Converts an RGBA image to a different color by first converting to black and then colorizing the image
	and readding the alpha stream. It works best with Black and White images (already colored images appear
	washed out).

	:param str/RGB color:   Accepts either a string represening a color from ImageColor.colormap or a
								     RGB tuple (e.g., (0, 0, 255) for blue)
	:param str input_filepath :   	 String path to image; preferably black and white
	:param str output_filepath :     String path to save new image
	"""
	possible_colors = [k for k, v in ImageColor.colormap.items()]
	if (type(color) != tuple or len(color) != 3) and (color not in possible_colors):
		raise Exception("Color not available")

	img = Image.open(input_filepath)

	# Collect original alpha data
	image_alpha = [item[3] for item in img.getdata()]

	# Convert image to black and white and then use colorize with new color
	bw_img = img.convert("L")
	new_img = ImageOps.colorize(bw_img, black=color, white="white")

	# Convert back to RGB w/ Alpha and add in the alpha from the original
	new_img = new_img.convert("RGBA")
	new_image = []
	for i, item in enumerate(new_img.getdata()):
		new_image.append((item[0], item[1], item[2], image_alpha[i]))

	# Update image with new data
	new_img.putdata(new_image)
	new_img.save(output_filepath)


def generate_css_colours(force=False):
	"""
	Write the colours.css CSS file based on configuration

	4CAT admins can change the interface colour in the 4CAT settings. Updating
	these necessitates also updating the relevant CSS files, which this method
	does.

	:param bool force:  Create colour definition file even if it exists already
	:return:
	"""
	interface_hue = config.get("4cat.layout_hue") / 360  # colorsys expects 0-1 values
	secondary_hue = config.get("4cat.layout_hue_secondary") / 360
	main_colour = colorsys.hsv_to_rgb(interface_hue, 0.87, 0.81)
	accent_colour = colorsys.hsv_to_rgb(interface_hue, 0.87, 1)
	# get opposite by adjusting the hue by 50%
	opposite_colour = colorsys.hsv_to_rgb(secondary_hue, 0.87, 0.9)

	template_file = config.get("PATH_ROOT").joinpath("webtool/static/css/colours.css.template")
	colour_file = config.get("PATH_ROOT").joinpath("webtool/static/css/colours.css")

	if colour_file.exists() and not force:
		# exists already, don't overwrite
		return

	with template_file.open() as infile:
		template = infile.read()
		template = template \
			.replace("{{ main_colour }}", make_html_colour(main_colour)) \
			.replace("{{ accent_colour }}", make_html_colour(accent_colour)) \
			.replace("{{ opposite_colour }}", make_html_colour(opposite_colour))

		with colour_file.open("w") as outfile:
			outfile.write(template)

	# Update the favicon
	new_favicon_color(
		color=tuple([int(bit*255) for bit in main_colour]),
		input_filepath=config.get("PATH_ROOT").joinpath("webtool/static/img/favicon/favicon-bw.ico"),
		output_filepath=config.get("PATH_ROOT").joinpath("webtool/static/img/favicon/favicon.ico")
	)


def get_preview(query):
	"""
	Generate a data preview of 25 rows of a results csv
	
	:param query 
	:return list: 
	"""
	preview = []
	with query.get_results_path().open(encoding="utf-8") as resultfile:
		posts = csv.DictReader(resultfile)
		i = 0
		for post in posts:
			i += 1
			preview.append(post)
			if i > 25:
				break
	return preview


def format_chan_post(post):
	"""
	Format a plain-text imageboard post post for HTML display

	Converts >>references into links and adds a class to greentext.s

	:param str post:  Post body
	:return str:  Formatted post body
	"""
	post = post.replace(">", "&gt;")
	post = re.sub(r"&gt;&gt;([0-9]+)", "<span class=\"quote\"><a href=\"#post-\\1\">&gt;&gt;\\1</a></span>", post)
	post = re.sub(r"^&gt;([^\n]+)", "<span class=\"greentext\">&gt;\\1</span>", post, flags=re.MULTILINE)
	return post


def check_restart_request():
	"""
	Check if a restart request is legit

	These requests authenticate a bit differently: they require a special token
	to be passed which should match the content of the current restart lock
	file. This ensures a restart is in progress and the request belongs to that
	specific restart.
	"""
	lock_file = Path(config.get("PATH_ROOT"), "config/restart.lock")
	if not lock_file.exists():
		return False

	with lock_file.open() as infile:
		token = infile.read().strip()
		request_is_legit = token and request.form.get("token") == token

	return request_is_legit


def setting_required(setting, required_value=True):
	"""
	Decorater that checks if the value of a certain setting is the required
	value before a route is parsed. If not, the user CANNOT PASS!

	Use like:

	@setting_required("privilege.can_restart")

	:param func: The view function to decorate.
	:param str setting: Name of the setting to check
	:param required_value: Value to check against.
	:type func: function
	"""
	def checking_decorator(func):
		@wraps(func)
		def decorated_view(*args, **kwargs):
			if not config.get(setting, user=current_user) == required_value:
				return current_app.login_manager.unauthorized()
			return func(*args, **kwargs)

		return decorated_view

	return checking_decorator
