"""
Generate ranking per post attribute
"""
import colorsys
import csv

from backend.abstract.processor import BasicProcessor
from backend.lib.helpers import UserInput, convert_to_int
from backend.lib.svgpathtools import Path, Line, CubicBezier, disvg

from svgwrite.gradients import LinearGradient


class RankFlowRenderer(BasicProcessor):
	"""
	Count occurrence of values for a given post attribute for a given time
	frame

	For example, this may be used to count the most-used author names per year;
	most-occurring country codes per month; overall top host names, etc
	"""
	type = "render-rankflow"  # job type ID
	category = "Visual"  # category
	title = "Create RankFlow diagram"  # title displayed in UI
	description = "Create a diagram showing changes in prevalence over time for sequential ranked lists (following Bernhard Rieder's RankFlow grapher)."  # description displayed in UI
	extension = "svg"  # extension of result file, used internally and in UI

	accepts = ["vector-ranker", "preset-neologisms"]
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
		}
	}

	def process(self):
		items = {}
		max_weight = 1
		colour_property = self.options.get("colour_property", self.options["colour_property"]["default"])
		size_property = self.options.get("size_property", self.options["size_property"]["default"])

		# first create a map with the ranks for each period
		with self.source_file.open() as input:
			reader = csv.reader(input)

			# detect whether the 'include amount of occurences' options was
			# checked for the top vectors source file - read the header and
			# look for the relevant column name. We're not using a DictReader
			# because we don't know what header format to expect
			header = reader.__next__()
			weighted = ("occurrences" in header)

			# create a dictionary per period in the source file (which should
			# be in chronological order already)
			for i in range(0, len(header)):
				if not weighted or i % 2 == 0:
					items[header[i]] = {}

			# determine items that are ranked per period and also weigh them;
			# if the amount of occurence is included use that, else weight
			# is always 1. Max length is stored to later properly scale the
			# invidual items in the flowchart.
			for row in reader:
				for i in range(0, len(row)):
					if not weighted or i % 2 == 0:
						period = list(items)[int(i / (2 if weighted else 1))]
						weight = 1 if not weighted else convert_to_int(row[i + 1], default=1)
						items[period][row[i]] = weight
						max_weight = max(weight, max_weight)

		# determine per-period changes
		# this is used for determining what colour to give to nodes, and
		# visualise outlying items in the data
		changes = {}
		max_change = 1
		for period in items:
			changes[period] = {}
			for item in items[period]:
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

		# some sizing parameters for the chart
		box_width = 12
		box_height = 10  # boxes will never be smaller than this
		box_max_height = 100
		box_gap_x = 90
		box_gap_y = 5

		box_start_x = 0
		paths = []

		# we use this to know if and where to draw the flow curve between a box
		# and its previous counterpart
		previous_box_coordinates = {}
		previous_box_attributes = {}
		boxes = []

		# svgpathtools has this weird setup where path attributes are
		# decoupled from path definitions
		definitions = []
		labels = []
		flow_attributes = []
		box_attributes = []
		path_widths = []
		box_widths = []

		# this is the default colour for items (it's blue-ish)
		# we're using HSV, so we can increase the hue for more prominent items
		base_colour = [.55, .95, .95]

		for period in items:
			box_start_y = 0

			for item in items[period]:
				weight = items[period][item]
				weight_factor = weight / max_weight
				height = int(max(box_height, box_max_height * weight_factor)) if size_property and weighted else box_height

				# colour ranges from blue to red
				change = changes[period][item]
				change_factor = 0 if not weighted or change <= 0 else (changes[period][item] / max_change)
				colour = base_colour.copy()
				colour[0] += (1 - base_colour[0]) * (weight_factor if colour_property == "weight" else change_factor)

				# first draw the box
				box = (
					Line(complex(box_start_x, box_start_y), complex(box_start_x + box_width, box_start_y)),
					Line(complex(box_start_x + box_width, box_start_y),
						 complex(box_start_x + box_width, box_start_y + height)),
					Line(complex(box_start_x + box_width, box_start_y + height),
						 complex(box_start_x, box_start_y + height)),
					Line(complex(box_start_x, box_start_y + height), complex(box_start_x, box_start_y))
				)

				# add box label
				label_y = (box_start_y + (height / 2)) + 3
				labels.append((item + (" (%s)" % weight if weight != 1 else ""), "8px", Path(Line(
					complex(box_start_x + box_width + box_gap_y, label_y),
					complex(box_start_x + box_width + box_gap_x, label_y)
				))))

				box_start_y += box_gap_y + height
				boxes.append(Path(*box))
				box_attributes.append(
					{"fill": "rgb(%i, %i, %i)" % tuple([int(v * 255) for v in colorsys.hsv_to_rgb(*colour)])})
				box_widths.append(1)

				# then draw the flow curve, if the box was ranked in an earlier
				# period as well
				if item in previous_box_coordinates:
					previous_box = previous_box_coordinates[item]

					top_offset = (box[0].start.real - previous_box[1].start.real) / 2
					control_top_left = complex(previous_box[1].start.real + top_offset, previous_box[1].start.imag)
					control_top_right = complex(box[0].start.real - top_offset, box[0].start.imag)

					bottom_offset = (box[3].start.real - previous_box[2].start.real) / 2
					control_bottom_left = complex(previous_box[2].start.real + bottom_offset, previous_box[2].start.imag)
					control_bottom_right = complex(box[3].start.real - bottom_offset, box[3].start.imag)

					paths.append(Path(*(
						CubicBezier(start=previous_box[1].start, end=box[0].start, control1=control_top_left,
									control2=control_top_right),
						Line(box[0].start, box[3].start),
						CubicBezier(start=box[3].start, end=previous_box[2].start, control1=control_bottom_right,
									control2=control_bottom_left),
						Line(previous_box[2].start, previous_box[1].start)
					)))

					# create a gradient from the colour of the previous box for
					# this item to this box's colour
					colour_from = previous_box_attributes[item]["fill"]
					colour_to = box_attributes[-1]["fill"]

					gradient = LinearGradient(start=(0, 0), end=(1, 0))
					gradient.add_stop_color(offset="0%", color=colour_from)
					gradient.add_stop_color(offset="100%", color=colour_to)
					definitions.append(gradient)

					# the addition of ' none' in the auto-generated fill colour
					# messes up some viewers/browsers, so get rid of it
					gradient_key = gradient.get_paint_server().replace(" none", "")
					flow_attributes.append({"fill": gradient_key, "opacity": 0.35})
					path_widths.append(0)

				previous_box_coordinates[item] = box
				previous_box_attributes[item] = box_attributes[-1]

			box_start_x += (box_gap_x + box_width)

		paths += boxes
		path_attributes = flow_attributes + box_attributes
		path_widths += box_widths

		# generate svgwrite object
		# todo: not use the shitty svgpathtools library and just manipulate
		# the svgwrite Drawing directly
		canvas = disvg(paths=paths, stroke_widths=path_widths, attributes=path_attributes,
					   paths2Drawing=True, openinbrowser=False, text=[label[0] for label in labels],
					   text_path=[label[2] for label in labels], font_size=[label[1] for label in labels],
					   svg_attributes={"style": "font-family:monospace;"}, mindim=1)

		# add our gradients so they can be referenced
		for definition in definitions:
			canvas.defs.add(definition)

		canvas.saveas(pretty=True, filename=str(self.dataset.get_results_path()))
		self.dataset.finish(len(items) * len(list(items.items()).pop()))
