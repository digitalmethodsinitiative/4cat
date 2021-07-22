"""
Generate ranking per post attribute
"""
import colorsys
import csv

from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput, get_4cat_canvas

from svgwrite.shapes import Rect
from svgwrite.path import Path
from svgwrite.text import Text
from svgwrite.gradients import LinearGradient

__author__ = ["Stijn Peeters"]
__credits__ = ["Stijn Peeters","Bernhard Rieder"]
__maintainer__ = ["Stijn Peeters"]
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)

class RankFlowRenderer(BasicProcessor):
	"""
	Count occurrence of values for a given post attribute for a given time
	frame

	For example, this may be used to count the most-used author names per year;
	most-occurring country codes per month; overall top host names, etc
	"""
	type = "render-rankflow"  # job type ID
	category = "Visual"  # category
	title = "RankFlow diagram"  # title displayed in UI
	description = "Create a diagram showing changes in prevalence over time for sequential ranked lists (following Bernhard Rieder's RankFlow grapher)."  # description displayed in UI
	extension = "svg"  # extension of result file, used internally and in UI

	options = {
		"colour_property": {
			"type": UserInput.OPTION_CHOICE,
			"options": {"change": "Change from previous", "weight": "Occurence", "none": "None"},
			"default": "change",
			"help": "Colour according to"
		},
		"size_property": {
			"type": UserInput.OPTION_CHOICE,
			"options": {"weight": "Occurence", "none": "None"},
			"default": "change",
			"help": "Size according to"
		},
		"show_value": {
			"type": UserInput.OPTION_TOGGLE,
			"default": True,
			"help": "Include value in label"
		}
	}

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor on rankable items

		:param module: Dataset or processor to determine compatibility with
		"""
		return module.is_rankable()
		
	def process(self):
		items = {}
		max_weight = 1
		colour_property = self.parameters.get("colour_property")
		size_property = self.parameters.get("size_property")
		include_value = self.parameters.get("show_value", False)

		# first create a map with the ranks for each period
		weighted = False
		for row in self.iterate_items(self.source_file):
			if row["date"] not in items:
				items[row["date"]] = {}

			try:
				weight = float(row["value"])
				weighted = True
			except (KeyError, ValueError):
				weight = 1

			# Handle collocations a bit differently
			if [k for k in row if k.startswith("word_")]:
				label = " ".join([row[k] for k in row if k.startswith("word_")])
			else:
				label = row["item"]

			items[row["date"]][label] = weight
			max_weight = max(max_weight, weight)

		# determine per-period changes
		# this is used for determining what colour to give to nodes, and
		# visualise outlying items in the data
		changes = {}
		max_change = 1
		max_item_length = 0
		for period in items:
			changes[period] = {}
			for item in items[period]:
				max_item_length = max(len(item), max_item_length)
				now = items[period][item]
				then = -1
				for previous_period in items:
					if previous_period == period:
						break
					for previous_item in items[previous_period]:
						if previous_item == item:
							then = items[previous_period][item]

				if then >= 0:
					change = abs(now - then)
					max_change = max(max_change, change)
					changes[period][item] = change
				else:
					changes[period][item] = 1

		# some sizing parameters for the chart - experiment with those
		fontsize_normal = 12
		fontsize_small = 8
		box_width = fontsize_normal
		box_height = fontsize_normal * 1.25  # boxes will never be smaller than this
		box_max_height = box_height * 10
		box_gap_x = max_item_length * fontsize_normal * 0.75
		box_gap_y = 5
		margin = 25

		# don't change this - initial X value for top left box
		box_start_x = margin

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

		# this is the default colour for items (it's blue-ish)
		# we're using HSV, so we can increase the hue for more prominent items
		base_colour = [.55, .95, .95]
		max_y = 0

		# go through all periods and draw boxes and flows
		for period in items:
			# reset Y coordinate, i.e. start at top
			box_start_y = margin

			for item in items[period]:
				# determine weight (and thereby height) of this particular item
				weight = items[period][item]
				weight_factor = weight / max_weight
				height = int(
					max(box_height, box_max_height * weight_factor)) if size_property != "none" and weighted else box_height

				# colour ranges from blue to red
				change = changes[period][item]
				change_factor = 0 if not weighted or change <= 0 else (changes[period][item] / max_change)
				colour = base_colour.copy()
				colour[0] += (1 - base_colour[0]) * (weight_factor if colour_property == "weight" else change_factor)

				# first draw the box
				box_fill = "rgb(%i, %i, %i)" % tuple([int(v * 255) for v in colorsys.hsv_to_rgb(*colour)])
				box = Rect(
					insert=(box_start_x, box_start_y),
					size=(box_width, height),
					fill=box_fill
				)
				boxes.append(box)

				# then the text label
				label_y = (box_start_y + (height / 2)) + 3
				label_value = "" if not include_value else (" (%s)" % weight if weight != 1 else "")
				label = Text(
					text=(item + label_value),
					insert=(box_start_x + box_width + box_gap_y, label_y)
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
					flow = Path(fill=gradient_key, opacity="0.35")
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
								 width=(margin * 2) + (len(items) * (box_width + box_gap_x)),
								 height=max_y + (margin * 2),
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
		for item in (*boxes, *labels):
			canvas.add(item)

		# finally, save the svg file
		canvas.saveas(pretty=True, filename=str(self.dataset.get_results_path()))
		self.dataset.finish(len(items) * len(list(items.items()).pop()))
