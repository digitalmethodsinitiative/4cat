"""
Generate histogram of activity
"""
import math
import csv

from pathlib import Path
from calendar import month_abbr

from svgwrite import Drawing
from svgwrite.container import SVG
from svgwrite.shapes import Line, Rect
from svgwrite.path import Path
from svgwrite.text import Text

from backend.abstract.processor import BasicProcessor
from backend.lib.helpers import UserInput, pad_interval

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

class SVGHistogramRenderer(BasicProcessor):
	"""
	Generate activity histogram
	"""
	type = "histogram"  # job type ID
	category = "Visual"  # category
	title = "Histogram"  # title displayed in UI
	description = "Generates a histogram (bar graph) from a previous frequency analysis."  # description displayed in UI
	extension = "svg"  # extension of result file, used internally and in UI

	accepts = ["count-posts"]

	input = "csv:timestamp"
	output = "png"

	options = {
		"header": {
			"type": UserInput.OPTION_TEXT,
			"default": "",
			"help": "Graph header",
			"tooltip": "The header may be truncated if it is too large to fit"
		}
	}

	def process(self):
		"""
		Render an SVG histogram/bar chart using a previous frequency analysis
		as input.
		"""
		self.dataset.update_status("Reading source file")
		header = self.parameters.get("header", self.options["header"]["default"])
		max_posts = 0

		# collect post numbers per month
		intervals = {}
		for post in self.iterate_csv_items(self.source_file):
			intervals[post["date"]] = int(post["frequency"])
			max_posts = max(max_posts, int(post["frequency"]))

		if len(intervals) <= 1:
			self.dataset.update_status("Not enough data available for a histogram; need more than one time series.")
			self.dataset.finish(0)
			return

		self.dataset.update_status("Cleaning up data")
		(missing, intervals) = pad_interval(intervals)

		# create histogram
		self.dataset.update_status("Drawing histogram")

		# you may change the following four variables to adjust the graph dimensions
		width = 1024
		height = 786
		y_margin = 75
		x_margin = 50
		x_margin_left = x_margin * 2
		tick_width = 5

		fontsize_normal = int(height / 40)
		fontsize_small = int(height / 75)

		# better don't touch the following
		line_width = round(width / 512)
		y_margin_top = 150 if header else 50
		y_height = height - (y_margin + y_margin_top)
		x_width = width - (x_margin + x_margin_left)
		canvas = Drawing(filename=str(self.dataset.get_results_path()), size=(width, height),
						 style="font-family:monospace;font-size:%ipx" % fontsize_normal)

		# normalize the Y axis to a multiple of a power of 10
		magnitude = pow(10, len(str(max_posts)) - 1)  # ew
		max_neat = math.ceil(max_posts / magnitude) * magnitude
		self.dataset.update_status("Max (normalized): %i (%i) (magnitude: %i)" % (max_posts, max_neat, magnitude))

		# draw border
		canvas.add(Rect(
			insert=(0, 0),
			size=(width, height),
			stroke="#000",
			stroke_width=line_width,
			fill="#FFF"
		))

		# draw header on a black background if needed
		if header:
			if len(header) > 40:
				header = header[:37] + "..."

			header_rect_height = (y_margin_top / 1.5)
			header_fontsize = (width / len(header))

			header_container = SVG(insert=(0, 0), size=(width, header_rect_height))
			header_container.add(Rect(
				insert=(0, 0),
				size=(width, header_rect_height),
				fill="#000"
			))
			header_container.add(Text(
				insert=("50%", "50%"),
				text=header,
				dominant_baseline="middle",
				text_anchor="middle",
				fill="#FFF",
				style="font-size:%i" % header_fontsize
			))
			canvas.add(header_container)

		# horizontal grid lines
		for i in range(0, 10):
			offset = (y_height / 10) * i
			canvas.add(Line(
				start=(x_margin_left, y_margin_top + offset),
				end=(width - x_margin, y_margin_top + offset),
				stroke="#EEE",
				stroke_width=line_width
			))

		# draw bars
		item_width = (width - (x_margin + x_margin_left)) / len(intervals)
		item_height = (height - y_margin - y_margin_top)
		bar_width = item_width * 0.9
		x = x_margin_left + (item_width / 2) - (bar_width / 2)

		if bar_width >= 8:
			arc_adjust = max(8, int(item_width / 5)) / 2
		else:
			arc_adjust = 0

		for interval in intervals:
			posts = int(intervals[interval])
			bar_height = ((posts / max_neat) * item_height)
			self.dataset.update_status("%s: %i posts" % (interval, posts))
			bar_top = height - y_margin - bar_height
			bar_bottom = height - y_margin

			if bar_height == 0:
				x += item_width
				continue

			bar = Path(fill="#000")
			bar.push("M %f %f" % (x, bar_bottom))
			bar.push("L %f %f" % (x, bar_top + (arc_adjust if bar_height > arc_adjust else 0)))
			if bar_height > arc_adjust > 0:
				control = (x, bar_top)
				bar.push("C %f %f %f %f %f %f" % (*control, *control, x + arc_adjust, bar_top))
			bar.push("L %f %f" % (x + bar_width - arc_adjust, height - y_margin - bar_height))
			if bar_height > arc_adjust > 0:
				control = (x + bar_width, bar_top)
				bar.push("C %f %f %f %f %f %f" % (*control, *control, x + bar_width, bar_top + arc_adjust))
			bar.push("L %f %f" % (x + bar_width, height - y_margin))
			bar.push("Z")
			canvas.add(bar)

			x += item_width

		# draw X and Y axis
		canvas.add(Line(
			start=(x_margin_left, height - y_margin),
			end=(width - x_margin, height - y_margin),
			stroke="#000",
			stroke_width=2
		))
		canvas.add(Line(
			start=(x_margin_left, y_margin_top),
			end=(x_margin_left, height - y_margin),
			stroke="#000",
			stroke_width=2
		))

		# draw ticks on Y axis
		for i in range(0, 10):
			offset = (y_height / 10) * i
			canvas.add(Line(
				start=(x_margin_left - tick_width, y_margin_top + offset),
				end=(x_margin_left, y_margin_top + offset),
				stroke="#000",
				stroke_width=line_width
			))

		# draw ticks on X axis
		for i in range(0, len(intervals)):
			offset = (x_width / len(intervals)) * (i + 0.5)
			canvas.add(Line(
				start=(x_margin_left + offset, height - y_margin),
				end=(x_margin_left + offset, height - y_margin + tick_width),
				stroke="#000",
				stroke_width=line_width
			))

		# prettify

		# y labels
		origin = (x_margin_left / 2)
		step = y_height / 10
		for i in range(0, 11):
			label = str(int((max_neat / 10) * i))
			labelsize = (len(label) * fontsize_normal * 1.25, fontsize_normal)
			label_x = origin - (tick_width * 2)
			label_y = height - y_margin - (i * step) - (labelsize[1] / 2)
			label_container = SVG(
				insert=(label_x, label_y),
				size=(x_margin_left / 2, x_margin_left / 5)
			)
			label_container.add(Text(
				insert=("100%", "50%"),
				text=label,
				dominant_baseline="middle",
				text_anchor="end"
			))
			canvas.add(label_container)

		# x labels
		label_width = max(fontsize_small * 6, item_width)
		label_x = x_margin_left
		label_y = height - y_margin + (tick_width * 2)
		next = 0
		for interval in intervals:
			if len(interval) == 7:
				label = month_abbr[int(interval[5:7])] + "\n" + interval[0:4]
			elif len(interval) == 10:
				label = str(int(interval[8:10])) + month_abbr[int(interval[5:7])] + "\n" + interval[0:4]
			else:
				label = interval.replace("-", "\n")

			if label_x > next:
				shift = 0
				for line in label.split("\n"):
					label_container = SVG(
						insert=(label_x + (item_width / 2) - (label_width / 2), label_y + (tick_width * 2)),
						size=(label_width, y_margin), overflow="visible")
					label_container.add(Text(
						insert=("50%", "0%"),
						text=line,
						dominant_baseline="middle",
						text_anchor="middle",
						baseline_shift=-shift
					))
					shift += fontsize_small * 2
					canvas.add(label_container)
					next = label_x + (label_width * 0.9)
			label_x += item_width

		# 4cat logo
		label = "made with 4cat - 4cat.oilab.nl"
		footersize = (fontsize_small * len(label) * 0.7, fontsize_small * 2)
		footer = SVG(insert=(width - footersize[0], height - footersize[1]), size=footersize)
		footer.add(Rect(insert=(0, 0), size=("100%", "100%"), fill="#000"))
		footer.add(Text(
			insert=("50%", "50%"),
			text=label,
			dominant_baseline="middle",
			text_anchor="middle",
			fill="#FFF",
			style="font-size:%i" % fontsize_small
		))
		canvas.add(footer)

		canvas.save(pretty=True)

		self.dataset.update_status("Finished")
		self.dataset.finish(len(intervals))
