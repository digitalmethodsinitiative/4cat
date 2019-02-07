"""
Generate histogram of activity
"""
import datetime
import math
import time
import csv
import os

from PIL import Image, ImageDraw, ImageFont
from backend.lib.helpers import get_absolute_folder
from backend.abstract.postprocessor import BasicPostProcessor

class HistogramRenderer(BasicPostProcessor):
	"""
	Generate activity histogram
	"""
	type = "monthly-histogram"  # job type ID
	title = "Histogram (monthly)"  # title displayed in UI
	description = "Generates a histogram (bar graph) that aggregates the number of posts per month to provide an impression of over-time activity in the data set"  # description displayed in UI
	extension = "png"  # extension of result file, used internally and in UI

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with all posts containing the original query exactly, ignoring any
		* or " in the query
		"""
		months = {}

		self.query.update_status("Reading source file")
		first_post = int(time.time())
		last_post = 0
		max_posts = 0

		# collect post numbers per month
		with open(self.source_file) as source:
			posts = csv.DictReader(source)
			for post in posts:
				timestamp = int(post.get("unix_timestamp", datetime.datetime.fromisoformat(post["timestamp"]).timestamp()))
				date = datetime.datetime.fromtimestamp(timestamp)

				first_post = min(timestamp, first_post)
				last_post = max(timestamp, last_post)

				year = date.year
				month = date.month
				if year not in months:
					months[year] = {}
					for i in range(1, 13):
						months[year][i] = 0

				months[year][month] += 1
				max_posts = max(months[year][month], max_posts)

		self.query.update_status("Cleaning up data")
		# make sure there are no missing years
		first = min(months)
		last = max(months)
		for m in range(first, last):
			if m not in months:
				months[m] = {}
				for i in range(1, 13):
					months[m][i] = 0

		# remove empty months at start and beginning of time period
		first_month = datetime.datetime.fromtimestamp(first_post).month
		first_year = datetime.datetime.fromtimestamp(first_post).year
		last_month = datetime.datetime.fromtimestamp(last_post).month
		last_year = datetime.datetime.fromtimestamp(last_post).year

		for m in range(1, first_month):
			del months[first_year][m]

		for m in range(last_month + 1, 13):
			del months[last_year][m]

		# sort dates
		months_sorted = {year: months[year] for year in sorted(months.keys())}
		for year in months_sorted:
			months_sorted[year] = {month: months_sorted[year][month] for month in sorted(months_sorted[year].keys())}
		months = months_sorted

		# create histogram
		self.query.update_status("Drawing histogram")

		# you may change the following four variables to adjust the graph dimensions
		width = 1024
		height = 786
		y_margin = 75
		y_margin_top = 150
		x_margin = 50
		x_margin_left = x_margin * 2
		tick_width = 5
		fontfile = "backend/assets/FiraCode-Retina.ttf"

		# better don't touch the following
		fontfile = get_absolute_folder("") + "/" + fontfile
		line_width = round(width / 512)
		y_height = height - (y_margin + y_margin_top)
		x_width = width - (x_margin + x_margin_left)
		histogram = Image.new("RGB", (width, height), "white")
		draw = ImageDraw.Draw(histogram)

		num_months = sum([len(months[year]) for year in months])

		# normalize the Y axis to a multiple of a power of 10
		magnitude = pow(10, len(str(max_posts)) - 1)  # ew
		max_neat = math.ceil(max_posts / magnitude) * magnitude
		self.query.update_status("Max (normalized): %i (%i) (magnitude: %i)" % (max_posts, max_neat, magnitude))

		# draw border
		draw.rectangle([(0, 0), (width, height)], fill="black")
		draw.rectangle([(line_width, line_width), (width - 1 - line_width, height - 1 - line_width)], fill="white")

		# horizontal grid lines
		for i in range(0, 10):
			offset = (y_height / 10) * i
			draw.line([(x_margin_left, y_margin_top + offset), (width - x_margin, y_margin_top + offset)], "#EEE", line_width)  # x axis

		# draw bars
		item_width = (width - (x_margin + x_margin_left)) / num_months
		item_height = (height - y_margin - y_margin_top)
		bar_width = item_width * 0.9
		x = x_margin_left + (item_width / 2) - (bar_width / 2)

		if bar_width >= 8:
			arc_size = max(4, int(item_width / 5))
		else:
			arc_size = 0

		arc_adjust = arc_size / 2

		for year in months:
			for month in months[year]:
				posts = months[year][month]
				bar_height = ((posts / max_neat) * item_height) - arc_adjust
				self.query.update_status("%i-%i: %i (%f%%)" % (year, month, posts, bar_height))
				bar_y = y_margin_top + item_height - (bar_height) + arc_adjust
				draw.rectangle([(x, bar_y - arc_adjust), (x + bar_width, height - y_margin)], "black")

				# rounded corners
				if arc_size > 0:
					draw.pieslice([x, bar_y - arc_size, x + arc_size, bar_y], start=180, end=270, fill="black")
					draw.pieslice([x + bar_width - arc_size, bar_y - arc_size, x + bar_width, bar_y], start=-90, end=0,
							  fill="black")

				draw.rectangle([(x + arc_adjust, bar_y - arc_size), (x + bar_width - arc_adjust, bar_y)], fill="black")

				x += item_width

		# blank area below bars to hide rendering artefacts
		draw.rectangle([(line_width, height - y_margin), (width - 1 - line_width, height - 1 - line_width)], fill="white")

		# draw X and Y axis
		draw.line([(x_margin_left, height - y_margin), (width - x_margin, height - y_margin)], "black", 2)  # x axis
		draw.line([(x_margin_left, y_margin_top), (x_margin_left, height - y_margin)], "black", 2)  # y axis

		# draw ticks on Y axis
		for i in range(0, 10):
			offset = (y_height / 10) * i
			draw.line([(x_margin_left - tick_width, y_margin_top + offset), (x_margin_left, y_margin_top + offset)], "black",
					  line_width)  # x axis

		# draw ticks on X axis
		for i in range(0, num_months):
			offset = (x_width / num_months) * (i + 0.5)
			draw.line(
				[(x_margin_left + offset, height - y_margin), (x_margin_left + offset, height - y_margin + tick_width)],
				"black", line_width)  # x axis

		# prettify
		if os.path.exists(fontfile):
			header_rect_height = (y_margin_top / 1.5)
			draw.rectangle([(0, 0), (width, header_rect_height)], "black")
			headerfont = ImageFont.truetype(fontfile, int(header_rect_height / 2))

			# graph header
			header = "\"" + self.parent.data["query"] + "\" - Posts per month"
			headersize = headerfont.getsize(header)
			if headersize[0] > width:
				header = "Posts per month"
				headersize = headerfont.getsize(header)

			header_x = (width / 2) - (headersize[0] / 2)
			header_y = (header_rect_height / 2) - (headersize[1] / 2)
			draw.text((header_x, header_y), header, font=headerfont, fill="white")

			# x labels
			labelfont = ImageFont.truetype(fontfile, int(x_margin_left / 5))
			origin = x_margin_left - (tick_width * 2)
			step = y_height / 10
			for i in range(0, 11):
				label = str(int((max_neat / 10) * i))
				labelsize = labelfont.getsize(label)
				label_x = origin - labelsize[0]
				label_y = height - y_margin - (i * step) - (labelsize[1] / 2)
				draw.text((label_x, label_y), label, font=labelfont, fill="black")

			# y labels
			labelfont = ImageFont.truetype(fontfile, int(x_margin_left / 6))
			month_labels = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
			label_width = labelfont.getsize("2018")[0]
			label_x = x_margin_left + (item_width / 2) - (label_width / 2)
			label_y = height - y_margin + (tick_width * 2)
			next = 0
			for year in months:
				for month in months[year]:
					label = "%s\n%s" % (month_labels[month - 1], year)
					if label_x > next:
						draw.text((label_x, label_y), label, font=labelfont, fill="black", align="center")
						next = label_x + (label_width * 2)
					label_x += item_width

			# 4cat logo
			footerfont = ImageFont.truetype(fontfile, int(height / 75))
			footer = "made with 4CAT - 4cat.oilab.nl"
			footersize = footerfont.getsize(footer)
			footer_x = width - footersize[0] * 1.1
			footer_y = height - footersize[1] * 1.4
			draw.rectangle([(width - (footersize[0] * 1.2), height - (footersize[1] * 1.8)), (width, height)], "black")
			draw.text((footer_x, footer_y), footer, font=footerfont, fill="white")
		else:
			self.log.warning("Font file missing: %s" % fontfile)

		histogram.save(self.query.get_results_path())

		self.query.update_status("Finished")
		self.query.finish(num_months)