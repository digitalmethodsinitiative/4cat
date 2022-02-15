"""
Generate ranking per post attribute
"""
import colorsys
import csv

from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput, get_4cat_canvas
from common.lib.exceptions import ProcessorInterruptedException

from svgwrite.shapes import Rect
from svgwrite.path import Path
from svgwrite.text import Text
from svgwrite.gradients import LinearGradient
from svgwrite.container import Script, Style
from svgwrite.filters import Filter

from xml.parsers.expat import ExpatError

__author__ = ["Stijn Peeters"]
__credits__ = ["Stijn Peeters","Bernhard Rieder"]
__maintainer__ = ["Stijn Peeters"]
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)

class RankFlowRenderer(BasicProcessor):
	"""
	Visualise relative occurrence of values over time

	For example, this may be used to visualise how particular word become more
	popular over time by using this to process a set of top vectors per month.
	"""
	type = "render-rankflow"  # job type ID
	category = "Visual"  # category
	title = "RankFlow diagram"  # title displayed in UI
	description = "Create a diagram showing changes in prevalence over time for sequential ranked lists (following " \
				  "Bernhard Rieder's RankFlow grapher)."  # description displayed in UI
	extension = "svg"  # extension of result file, used internally and in UI

	references = [
		"[Rieder, B. RankFlow. *The Politics of Systems*](https://labs.polsys.net/tools/rankflow/)"
	]

	options = {
		"colour_property": {
			"type": UserInput.OPTION_CHOICE,
			"options": {
				"change": "Delta (rising or falling items are highlighted)",
				"weight": "Value (more prevalent items are highlighted)",
				"item": "Item (unique colour per item)",
				"none": "None (same colour for everything)"
			},
			"default": "change",
			"help": "Colour according to"
		},
		"size_property": {
			"type": UserInput.OPTION_CHOICE,
			"options": {
				"weight": "Value (items with a higher value are bigger)",
				"none": "None (same size for all elements)"
			},
			"default": "change",
			"help": "Size according to"
		},
		"normalise-size": {
			"type": UserInput.OPTION_TOGGLE,
			"help": "Normalise size per period",
			"tooltip": "This makes the rankings have the same height per period regardless of the amount of items in "
					   "that period. Makes the graph more readable at the cost of over-representing periods with fewer "
					   "items.",
			"default": False
		},
		"show_value": {
			"type": UserInput.OPTION_TOGGLE,
			"default": True,
			"help": "Include value in label",
			"tooltip": "Make the value (e.g. number of occurrences) part of the label."
		},
		"filter-incomplete": {
			"type": UserInput.OPTION_TOGGLE,
			"default": False,
			"help": "Remove items that do not occur in all mapped periods."
		}
	}

	# 25-colour palette via https://medialab.github.io/iwanthue/
	palette = [[0.081, 1.0, 0.902], [0.625, 0.995, 0.749], [0.23, 1.0, 0.855], [0.883, 0.863, 1.0], [0.273, 1.0, 0.659],
			   [0.823, 1.0, 0.549], [0.434, 1.0, 0.863], [0.917, 1.0, 0.82], [0.327, 0.498, 0.867],
			   [0.587, 0.996, 0.914], [0.266, 1.0, 0.537], [0.602, 0.58, 1.0], [0.987, 1.0, 0.718],
			   [0.46, 0.993, 0.549], [0.996, 0.718, 1.0], [0.397, 1.0, 0.459], [0.016, 0.541, 1.0],
			   [0.309, 0.381, 0.843], [0.986, 0.431, 1.0], [0.188, 0.951, 0.161], [0.069, 0.468, 0.988],
			   [0.179, 1.0, 0.475], [0.108, 0.502, 0.914], [0.096, 1.0, 0.502], [0.123, 1.0, 0.69]]

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor on rankable items

		:param module: Dataset or processor to determine compatibility with
		"""
		return module.is_rankable()

	def process(self):
		"""
		Render RankFlow diagram
		"""
		items = {}
		max_weight = 1
		colour_property = self.parameters.get("colour_property")
		size_property = self.parameters.get("size_property")
		include_value = self.parameters.get("show_value", False)
		normal_size = self.parameters.get("normalise-size", False)
		filter_incomplete = self.parameters.get("filter-incomplete", False)

		# completeness filter - this finds the items in the source data that
		# do not have a value for all periods
		ignore = []
		max_item_length = 0
		if filter_incomplete:
			all_periods = set()
			known_periods = {}
			for row in self.source_dataset.iterate_items(self):
				all_periods.add(row["date"])

				label = self.get_label(row)
				if label not in known_periods:
					known_periods[label] = set()

				known_periods[label].add(row["date"])

			ignore = [label for label in known_periods if len(known_periods[label]) != len(all_periods)]

		# now first create a map with the ranks for each period
		weighted = False
		processed = 0
		for row in self.source_dataset.iterate_items(self):
			processed += 1
			if processed % 250 == 0:
				self.dataset.update_status("Determining RankFlow parameters, item %i/%i" % (processed, self.source_dataset.num_rows))

			# figure out label and apply completeness filter
			label = self.get_label(row)
			if label in ignore:
				continue

			# always treat weight (value) as float - can be converted to lower
			# precision later
			try:
				weight = float(row["value"])
				weighted = True
			except (KeyError, ValueError):
				weight = 1.0

			if row["date"] not in items:
				items[row["date"]] = {}
			items[row["date"]][label] = weight

			max_weight = max(max_weight, weight)
			max_item_length = max(max_item_length, len(row["date"]))

		# determine per-period changes
		# this is used for determining what colour to give to nodes, and
		# visualise outlying items in the data
		changes = {}
		max_change = 1.0
		max_per_period = {}

		# this is only needed for normalisation, but it's not too much overhead
		for period in items:
			max_per_period[period] = 0
			for item, value in items[period].items():
				max_per_period[period] += value

		if normal_size:
			# reset, because we're recalculating the weights
			max_weight = 0.0

		# determine deltas, normalise values, figure out item label length
		for period in items:
			self.dataset.update_status("Aggregating data for period %s" % period)
			changes[period] = {}
			for item, value in items[period].items():
				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while aggregating items")

				if normal_size:
					# normalise values as a percentage of the max value for
					# that period
					value = value / max_per_period[period]
					items[period][item] = float(value)
					max_weight = max(max_weight, value)

				label = self.get_label({"item": item, "value": items[period][item]}, with_value=include_value, as_pct=normal_size)
				max_item_length = max(len(label), max_item_length)
				then = -1.0

				# find most recent known value for this item
				for previous_period in items:
					if previous_period == period:
						break
					for previous_item in items[previous_period]:
						if previous_item == item:
							then = items[previous_period][item]

				# delta can be used to highlight trending topics
				if then >= 0:
					change = abs(value - then)
					max_change = max(max_change, change)
					changes[period][item] = change
				else:
					changes[period][item] = 0.0

		# some sizing parameters for the chart - experiment with these
		fontsize_normal = 12
		fontsize_small = 8
		box_width = fontsize_normal
		box_height = fontsize_normal * 1.5  # boxes will never be smaller than this
		box_max_height = box_height * (3 if normal_size else 6)  # how dramatic are the size changes?
		box_gap_x = ((max_item_length + 3) * fontsize_normal / 2) - box_width
		box_gap_y = 5

		margin_width = max(25, 5 + ((box_gap_x + box_width) / 2))
		margin_height = 20

		# don't change this - initial X value for top left box
		box_start_x = margin_width

		# we use this to know if and where to draw the flow curve between a box
		# and its previous counterpart
		previous_boxes = {}
		previous = []

		# we need to store the svg elements before drawing them to the canvas
		# because we need to know what elements to draw before we can set the
		# canvas up for drawing to
		boxes = []
		labels = []
		flows = []
		definitions = []
		date_labels = []

		# this is the default colour for items (it's blue-ish)
		# we're using HSV, so we can increase the hue for more prominent items
		base_colour = [.55, .95, .95]
		max_y = 0

		# this is a filter to make text labels have a solid background
		# it is used for the interactive elements, to make the text stand out
		# more when a path is highlighted
		solid = Filter(start=(0, 0), size=(1, 1), id="solid")
		solid.feFlood(flood_color="white", result="bg")
		solid.feMerge(("bg", "SourceGraphic"))
		definitions.append(solid)
		flow_ids = {}

		# go through all periods and draw boxes and flows
		for period in items:
			self.dataset.update_status("Rendering items for period %s" % period)
			# reset Y coordinate, i.e. start at top
			box_start_y = margin_height + (fontsize_normal * 1.5)

			# label at the very top, one per period (column)
			date_labels.append(Text(
				text=period,
				insert=(box_start_x + (box_width / 2), (fontsize_normal * 2)),
				text_anchor="middle"
			))

			for item in items[period]:
				if item not in flow_ids:
					flow_ids[item] = len(flow_ids) + 1

				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while rendering items")

				flow_class = "flow-%i" % flow_ids[item]
				# determine weight (and thereby height) of this particular item
				weight = items[period][item]
				weight_factor = weight / max_weight
				height = int(
					max(box_height, box_max_height * weight_factor)) if size_property != "none" and weighted else box_height

				if colour_property == "item":
					# static colour from palette
					colour_index = (flow_ids[item] - 1) % len(self.palette)
					colour = self.palette[colour_index]
					opacity = "1.0"  # too much?
					text_colour = self.black_or_white(colour)
				else:
					# colour ranges from blue to red
					change = changes[period][item]
					change_factor = 0 if not weighted or change <= 0 else (changes[period][item] / max_change)
					colour = base_colour.copy()
					colour[0] += (1 - base_colour[0]) * (weight_factor if colour_property == "weight" else change_factor)
					opacity = "0.35"
					text_colour = "black"

				# first draw the box
				box_fill = "rgb(%i, %i, %i)" % tuple([int(v * 255) for v in colorsys.hsv_to_rgb(*colour)])
				box = Rect(
					insert=(box_start_x, box_start_y),
					size=(box_width, height),
					fill=box_fill,
					class_=flow_class
				)
				boxes.append(box)

				# then the text label
				label_y = (box_start_y + (height / 2)) + 3
				label = Text(
					text=self.get_label({"item": item, "value": weight}, with_value=include_value, as_pct=normal_size),
					insert=(box_start_x + (box_width / 2), label_y),
					class_=flow_class + " color-" + text_colour,
					text_anchor="middle"
				)
				labels.append(label)

				# store the max y coordinate, which marks the SVG overall height
				max_y = max(max_y, (box["y"] + box["height"]))

				# then draw the flow curve, if the box was ranked in an earlier
				# period as well
				if item in previous:
					previous_box = previous_boxes[item]

					# create a gradient from the colour of the previous box for
					# this item to this box's colour
					colour_from = previous_box["fill"]
					colour_to = box["fill"]

					gradient = LinearGradient(start=(0, 0), end=(1, 0))
					gradient.add_stop_color(offset="0%", color=colour_from)
					gradient.add_stop_color(offset="100%", color=colour_to)
					definitions.append(gradient)

					# the addition of ' none' in the auto-generated fill colour
					# messes up some viewers/browsers, so get rid of it
					gradient_key = gradient.get_paint_server().replace(" none", "")

					# calculate control points for the connecting bezier bar
					# the top_offset determines the 'steepness' of the curve,
					# experiment with the "/ 2" part to make it less or more
					# steep
					top_offset = (box["x"] - previous_box["x"] + previous_box["width"]) / 2
					control_top_left = (previous_box["x"] + previous_box["width"] + top_offset, previous_box["y"])
					control_top_right = (box["x"] - top_offset, box["y"])

					bottom_offset = top_offset  # mirroring looks best
					control_bottom_left = (
						previous_box["x"] + previous_box["width"] + bottom_offset,
						previous_box["y"] + previous_box["height"])
					control_bottom_right = (box["x"] - bottom_offset, box["y"] + box["height"])

					# now add the bezier curves - svgwrite has no convenience
					# function for beziers unfortunately. we're using cubic
					# beziers though quadratic could work as well since our
					# control points are, in principle, mirrored
					flow_start = (previous_box["x"] + previous_box["width"], previous_box["y"])
					flow = Path(fill=gradient_key, opacity=opacity, class_=flow_class)
					flow.push("M %f %f" % flow_start)  # go to start
					flow.push("C %f %f %f %f %f %f" % (
						*control_top_left, *control_top_right, box["x"], box["y"]))  # top bezier
					flow.push("L %f %f" % (box["x"], box["y"] + box["height"]))  # right boundary
					flow.push("C %f %f %f %f %f %f" % (
						*control_bottom_right, *control_bottom_left, previous_box["x"] + previous_box["width"],
						previous_box["y"] + previous_box["height"]
					))  # bottom bezier
					flow.push("L %f %f" % flow_start)  # back to start
					flow.push("Z")  # close path

					flows.append(flow)

				# mark this item as having appeared previously
				previous.append(item)
				previous_boxes[item] = box

				box_start_y += height + box_gap_y

			box_start_x += (box_gap_x + box_width)

		# generate SVG canvas to add elements to
		canvas = get_4cat_canvas(self.dataset.get_results_path(),
								 width=(margin_width * 2) + (len(items) * box_width) + ((len(items) - 1) * box_gap_x),
								 height=max_y + (margin_height * 2),
								 fontsize_normal=fontsize_normal,
								 fontsize_small=fontsize_small)

		# now add the various shapes and paths. We only do this here rather than
		# as we go because only at this point can the canvas be instantiated, as
		# before we don't know the dimensions of the SVG drawing.

		# add our gradients so they can be referenced
		for definition in definitions:
			canvas.defs.add(definition)

		# add flows (which should go beyond the boxes)
		for flow in flows:
			canvas.add(flow)

		# add boxes and labels:
		for item in (*boxes, *labels, *date_labels):
			canvas.add(item)

		# make it interactive
		canvas.defs.add(Style(self.get_css()))
		canvas.add(Script(content=self.get_svg_script()))

		# finally, save the svg file
		self.dataset.update_status("Rendering visualisation as SVG file")
		try:
			canvas.saveas(pretty=True, filename=str(self.dataset.get_results_path()))
		except ExpatError:
			# Expat seemingly can't deal with very large XML files
			# but this only triggers when trying to pretty-print
			self.dataset.log("Pretty-printing failed, retrying...")
			canvas.saveas(filename=str(self.dataset.get_results_path()))

		self.dataset.finish(len(items) * len(list(items.items()).pop()))

	def black_or_white(self, hsv):
		"""
		Determine text colour on a given background

		First calculates the perceived lightness of the colour, then returns
		either `black` or `white` depending on which of those has the highest
		contrast against this background colour.

		Thanks to https://stackoverflow.com/a/56678483 !

		:param list hsv:  HSV values to calculate against
		:return str: `black` or `white`
		"""
		red, green, blue = colorsys.hsv_to_rgb(*hsv)

		# linearise rgb
		r1 = (red / 12.92) if red <= 0.04045 else pow((red + 0.055) / 1.055, 2.4)
		g1 = (green / 12.92) if green <= 0.04045 else pow((green + 0.055) / 1.055, 2.4)
		b1 = (blue / 12.92) if blue <= 0.04045 else pow((blue + 0.055) / 1.055, 2.4)

		# calculate luminance
		y = (0.2126 * r1) + (0.7152 * g1) + (0.0722 * b1)

		# calculate perceived lightness
		l = (y * 903.3) if y <= 0.008856 else (pow(y, 1 / 3) * 116 - 16)

		return "black" if l > 50 else "white"


	def get_label(self, row, with_value=False, as_pct=False):
		"""
		Get label for row in source dataset

		This can be either simply the listed item, or a combination of
		collocated words. Simple convenience method.

		:param dict row:  Row to get label from
		:param bool with_value:  Include value in label?
		:param bool as_pct:  Show value as percentage?
		:return str:  Label
		"""
		label = ""
		if [k for k in row if k.startswith("word_")]:
			label += " ".join([row[k] for k in row if k.startswith("word_")])
		else:
			label += row["item"]

		# how do we display the value, if at all?
		# don't go further than 2 decimals for floats
		if with_value and row["value"] != 1:
			if row["value"] != int(row["value"]):
				label_weight = "{0:.2g}".format(row["value"]) if not as_pct else str(int(row["value"] * 100)) + "%"
			else:
				label_weight = str(int(row["value"]))

			label += " (%s)" % label_weight

		return label

	def get_svg_script(self):
		"""
		Simple embeddable JavaScript to highlight hovered flows

		:return str:  Script code
		"""
		return """
window.addEventListener('DOMContentLoaded', function() {
	document.querySelectorAll('rect, path, text').forEach((obj) => {
		obj.addEventListener('mouseover', function(e) {
			let path_class = e.target.classList[0];
			document.querySelectorAll('.' + path_class).forEach((component) => {
				component.classList.add('highlighted');
			});
		});
		obj.addEventListener('click', function(e) {
			let path_class = e.target.classList[0];
			let is_enabled = e.target.classList.contains('persistent');
			document.querySelectorAll('.' + path_class).forEach((component) => {
				if(!is_enabled) {
					component.classList.add('persistent');
					component.classList.add('highlighted');
				} else {
					component.classList.remove('highlighted');
					component.classList.remove('persistent');
				}
			});
		});
		obj.addEventListener('mouseout', function(e) {
			let path_class = e.target.classList[0];
			document.querySelectorAll('.' + path_class + ':not(.persistent)').forEach((component) => {
				component.classList.remove('highlighted');
			});
		});
	});
});
"""

	def get_css(self):
		"""
		Simple embeddable stylesheet to highlight hovered flows

		:return str:  CSS code
		"""
		return """
path.highlighted, rect.highlighted {
	stroke: #000;
	stroke-width: 2px;
	opacity: 1;
}

text.color-white {
    fill: #FFF;
    text-shadow: -1px 0 rgba(0,0,0,0.5), 0 1px rgba(0,0,0,0.5), 1px 0 rgba(0,0,0,0.5), 0 -1px rgba(0,0,0,0.5);
}

text.highlighted {
	filter: url(#solid);
	fill: #000;
	text-shadow: none;
}
"""
