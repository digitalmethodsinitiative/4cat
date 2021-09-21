"""
Generate histogram of activity
"""
import math

from pathlib import Path
from calendar import month_abbr

from svgwrite.container import SVG
from svgwrite.shapes import Line
from svgwrite.path import Path
from svgwrite.text import Text

from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput, pad_interval, get_4cat_canvas

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
	extension = "svg"

	options = {
		"header": {
			"type": UserInput.OPTION_TEXT,
			"default": "",
			"help": "Graph header",
			"tooltip": "The header may be truncated if it is too large to fit"
		}
	}

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor on rankable items

		:param module: Dataset or processor to determine compatibility with
		"""
		return module.is_rankable(multiple_items=False)
		
	def process(self):
		"""
		Render an SVG histogram/bar chart using a previous frequency analysis
		as input.
		"""
		self.dataset.update_status("Reading source file")
		header = self.parameters.get("header")
		max_posts = 0

		# collect post numbers per month
		intervals = {}
		for post in self.iterate_items(self.source_file):
			value = int(float(post["value"]))
			intervals[post["date"]] = value
			max_posts = max(max_posts, value)

		if len(intervals) <= 1:
			self.dataset.update_status("Not enough data available for a histogram; need more than one time series.")
			self.dataset.finish(0)
			return

		self.dataset.update_status("Cleaning up data")
		try:
			(missing, intervals) = pad_interval(intervals)
		except ValueError:
			self.dataset.update_status("Some of the items in the dataset contain invalid dates; cannot count frequencies per interval.", is_final=True)
			self.dataset.finish(0)
			return

		# create histogram
		self.dataset.update_status("Drawing histogram")

		# you may change the following four variables to adjust the graph dimensions
		width = 1024
		height = 786
		y_margin = 75
		x_margin = 50
		x_margin_left = x_margin * 2
		tick_width = 5

		fontsize_small = width / 100
		fontsize_normal = width / 75
		fontsize_large = width / 50

		# better don't touch the following
		line_width = round(width / 512)
		y_margin_top = 50
		if header:
			y_margin_top += (2 * fontsize_large)
		y_height = height - (y_margin + y_margin_top)
		x_width = width - (x_margin + x_margin_left)

		# normalize the Y axis to a multiple of a power of 10
		magnitude = pow(10, len(str(max_posts)) - 1)  # ew
		max_neat = math.ceil(max_posts / magnitude) * magnitude
		self.dataset.update_status("Max (normalized): %i (%i) (magnitude: %i)" % (max_posts, max_neat, magnitude))

		canvas = get_4cat_canvas(self.dataset.get_results_path(), width, height,
								 header=(header[:37] + "..." if len(header) > 40 else header),
								 fontsize_small=fontsize_small,
								 fontsize_large=fontsize_large,
								 fontsize_normal=fontsize_normal)

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

		interval_type = self.source_dataset.parameters.get("timeframe", "overall")
		for interval in intervals:
			if len(interval) == 7:
				if interval_type == "month":
					label = month_abbr[int(interval[5:7])] + "\n" + interval[0:4]
				else:
					label = interval[0:4] + "\nW" + interval[5:7]

			elif len(interval) == 10:
				label = str(int(interval[8:10])) + " " + month_abbr[int(interval[5:7])] + "\n" + interval[0:4]
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
						dy=[shift]
					))
					shift += fontsize_small * 1.5
					canvas.add(label_container)
					next = label_x + (label_width * 0.9)
			label_x += item_width


		canvas.save(pretty=True)

		self.dataset.update_status("Finished")
		self.dataset.finish(len(intervals))
