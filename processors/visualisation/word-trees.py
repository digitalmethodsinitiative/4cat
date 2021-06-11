"""
Generate word tree from dataset
"""
import re

from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput, convert_to_int

from nltk.tokenize import word_tokenize

from svgwrite import Drawing
from svgwrite.container import SVG
from svgwrite.path import Path
from svgwrite.text import Text

from anytree import Node

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

class MakeWordtree(BasicProcessor):
	"""
	Generate word tree from dataset

	Inspired by https://www.jasondavies.com/wordtree/.
	"""
	type = "word-trees"  # job type ID
	category = "Visual"  # category
	title = "Word tree"  # title displayed in UI
	description = "Generates a word tree for a given query, a \"graphical version of the traditional 'keyword-in-context' method\" (Wattenberg & Viégas, 2008)."  # description displayed in UI
	extension = "svg"  # extension of result file, used internally and in UI

	references = [
		"Wattenberg, M., & Viégas, F. B. (2008). The Word Tree, an Interactive Visual Concordance. IEEE Transactions on Visualization and Computer Graphics, 14(6), 1221–1228. <https://doi.org/10.1109/TVCG.2008.172>"
	]

	options = {
		"query": {
			"type": UserInput.OPTION_TEXT,
			"default": "",
			"help": "Word tree root query",
			"tooltip": "Enter a word here to serve as the root of the word tree. The context of this query will be mapped in the tree visualisation. Cannot be empty or contain whitespace."
		},
		"limit": {
			"type": UserInput.OPTION_TEXT,
			"default": 3,
			"min": 1,
			"max": 25,
			"help": "Max branches/level",
			"tooltip": "Limit the amount of branches per level, sorted by most-occuring phrases. Range 1-25."
		},
		"window": {
			"type": UserInput.OPTION_TEXT,
			"min": 1,
			"max": 10,
			"default": 5,
			"help": "Window size",
			"tooltip": "Up to this many words before and/or after the queried phrase will be visualised"
		},
		"sides": {
			"type": UserInput.OPTION_CHOICE,
			"default": "right",
			"options": {
				"left": "Before query",
				"right": "After query",
				"both": "Before and after query"
			},
			"help": "Query context to visualise"
		},
		"align": {
			"type": UserInput.OPTION_CHOICE,
			"default": "middle",
			"options": {
				"middle": "Vertically centered",
				"top": "Top",
			},
			"help": "Visual alignment"
		},
		"strip-urls": {
			"type": UserInput.OPTION_TOGGLE,
			"default": True,
			"help": "Remove URLs"
		},
		"strip-symbols": {
			"type": UserInput.OPTION_TOGGLE,
			"default": True,
			"help": "Remove non-alphanumeric characters"
		}
	}

	# determines how close the nodes are displayed to each other (min. 1)
	whitespace = 2

	# 'fontsize' can be changed, the others are derived
	fontsize = 16
	step = 0
	gap = 0

	# to be used later to determine dimensions of graph
	x_min = 0
	x_max = 0
	max_occurrences = {}

	# constants
	SIDE_LEFT = -1
	SIDE_RIGHT = 1

	# amount of nodes to include per branch
	# set as a parameter, but stored as a property to be accessed by child
	# methods
	limit = 1

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a plain text file
		containing all post bodies as one continuous string, sanitized.
		"""

		link_regex = re.compile(r"https?://[^\s]+")
		delete_regex = re.compile(r"[^a-zA-Z)(.,\n -]")

		# settings
		strip_urls = self.parameters.get("strip-urls")
		strip_symbols = self.parameters.get("strip-symbols")
		sides = self.parameters.get("sides")
		self.align = self.parameters.get("align")
		window = convert_to_int(self.parameters.get("window"), 5) + 1
		query = self.parameters.get("query")
		self.limit = convert_to_int(self.parameters.get("limit"), 100)

		left_branches = []
		right_branches = []

		# do some validation
		if not query.strip() or re.sub(r"\s", "", query) != query:
			self.dataset.update_status("Invalid query for word tree generation. Query cannot be empty or contain whitespace.")
			self.dataset.finish(0)
			return

		window = min(window, self.get_options()["window"]["max"] + 1)
		window = max(1, window)

		# find matching posts
		processed = 0
		for post in self.iterate_items(self.source_file):
			processed += 1
			if processed % 500 == 0:
				self.dataset.update_status("Processing and tokenising post %i" % processed)
			body = post["body"]
			if not body:
				continue

			if strip_urls:
				body = link_regex.sub("", body)

			if strip_symbols:
				body = delete_regex.sub("", body)

			body = word_tokenize(body)
			positions = [i for i, x in enumerate(body) if x.lower() == query.lower()]

			# get lists of tokens for both the left and right side of the tree
			# on the left side, all lists end with the query, on the right side,
			# they start with the query
			for position in positions:
				right_branches.append(body[position:position + window])
				left_branches.append(body[max(0, position - window):position + 1])

		# Some settings for rendering the tree later
		self.step = self.fontsize * 0.6  # approximately the width of a monospace char
		self.gap = (7 * self.step)  # space for lines between nodes
		width = 1  # will be updated later

		# invert the left side of the tree (because that's the way we want the
		# branching to work for that side)
		# we'll visually invert the nodes in the tree again later
		left_branches = [list(reversed(branch)) for branch in left_branches]

		# first create vertical slices of tokens per level
		self.dataset.update_status("Generating token tree from posts")
		levels_right = [{} for i in range(0, window)]
		levels_left = [{} for i in range(0, window)]
		tokens_left = []
		tokens_right = []

		# for each "level" (each branching point representing a level), turn
		# tokens into nodes, record the max amount of occurences for any
		# token in that level, and keep track of what nodes are in which level.
		# The latter is needed because a token may occur multiple times, at
		# different points in the graph. Do this for both the left and right
		# side of the tree.
		for i in range(0, window):
			for branch in right_branches:
				if i >= len(branch):
					continue

				token = branch[i].lower()
				if token not in levels_right[i]:
					parent = levels_right[i - 1][branch[i - 1].lower()] if i > 0 else None
					levels_right[i][token] = Node(token, parent=parent, occurrences=1, is_top_root=(parent is None))
					tokens_right.append(levels_right[i][token])
				else:
					levels_right[i][token].occurrences += 1

				occurrences = levels_right[i][token].occurrences
				self.max_occurrences[i] = max(occurrences, self.max_occurrences[i]) if i in self.max_occurrences else occurrences

			for branch in left_branches:
				if i >= len(branch):
					continue

				token = branch[i].lower()
				if token not in levels_left[i]:
					parent = levels_left[i - 1][branch[i - 1].lower()] if i > 0 else None
					levels_left[i][token] = Node(token, parent=parent, occurrences=1, is_top_root=(parent is None))
					tokens_left.append(levels_left[i][token])
				else:
					levels_left[i][token].occurrences += 1

				occurrences = levels_left[i][token].occurrences
				self.max_occurrences[i] = max(occurrences, self.max_occurrences[i]) if i in self.max_occurrences else occurrences

		# nodes that have no siblings can be merged with their parents, else
		# the graph becomes unnecessarily large with lots of single-word nodes
		# connected to single-word nodes. additionally, we want the nodes with
		# the most branches to be sorted to the top, and then only retain the
		# most interesting (i.e. most-occurring) branches
		self.dataset.update_status("Merging and sorting tree nodes")
		for token in tokens_left:
			self.merge_upwards(token)
			self.sort_node(token)
			self.limit_subtree(token)

		for token in tokens_right:
			self.merge_upwards(token)
			self.sort_node(token)
			self.limit_subtree(token)

		# somewhat annoyingly, anytree does not simply delete nodes detached
		# from the tree in the previous steps, but makes them root nodes. We
		# don't need these root nodes (we only need the original root), so the
		# next step is to remove all root nodes that are not the main root.
		# We cannot modify a list in-place, so make a new list with the
		# relevant nodes
		level_sizes = {}
		filtered_tokens_right = []
		for token in tokens_right:
			if token.is_root and not token.is_top_root:
				continue

			filtered_tokens_right.append(token)

		filtered_tokens_left = []
		for token in tokens_left:
			if token.is_root and not token.is_top_root:
				continue

			filtered_tokens_left.append(token)

		# now we know which nodes are left, and can therefore determine how
		# large the canvas needs to be - this is based on the max number of
		# branches found on any level of the tree, in other words, the number
		# of "terminal nodes"
		breadths_left = [self.max_breadth(node) for node in filtered_tokens_left if node.is_top_root]
		breadths_right = [self.max_breadth(node) for node in filtered_tokens_right if node.is_top_root]

		if not breadths_left:
			if sides == "left":
				self.dataset.update_status("No data available to the left of the query", is_final=True)
				self.dataset.finish(0)
				return None
			elif sides == "both":
				sides = "right"
				breadths_left = [0]

		if not breadths_right:
			if sides == "right":
				self.dataset.update_status("No data available to the right of the query", is_final=True)
				self.dataset.finish(0)
				return None
			elif sides == "both":
				sides = "left"
				breadths_right = [0]

		height_left = self.whitespace * self.fontsize * max(breadths_left)
		height_right = self.whitespace * self.fontsize * max(breadths_right)
		height = max(height_left, height_right)

		canvas = Drawing(str(self.dataset.get_results_path()),
						 size=(width, height),
						 style="font-family:monospace;font-size:%ipx" % self.fontsize)

		# the nodes on the left side of the graph now have the wrong word order,
		# because we reversed them earlier to generate the correct tree
		# hierarchy - now reverse the node labels so they are proper language
		# again
		for token in tokens_left:
			self.invert_node_labels(token)

		wrapper = SVG(overflow="visible")

		self.dataset.update_status("Rendering tree to SVG file")
		if sides != "right":
			wrapper = self.render(wrapper, [token for token in filtered_tokens_left if token.is_root and token.children],
								  height=height, side=self.SIDE_LEFT)

		if sides != "left":
			wrapper = self.render(wrapper, [token for token in filtered_tokens_right if token.is_root and token.children],
								  height=height, side=self.SIDE_RIGHT)

		# things may have been rendered outside the canvas, in which case we
		# need to readjust the SVG properties
		wrapper.update({"x": 0 if self.x_min >= 0 else self.x_min * -1})
		canvas.update({"width": (self.x_max - self.x_min)})

		canvas.add(wrapper)
		canvas.save(pretty=True)

		self.dataset.update_status("Finished")
		self.dataset.finish(len(tokens_left) + len(tokens_right))

	def render(self, canvas, level, x=0, y=0, origin=None, height=None, side=1, init=True, level_index=0):
		"""
		Render node set to canvas

		:param canvas:  SVG object
		:param list level:  List of nodes to render
		:param int x:  X coordinate of top left of level block
		:param int y:  Y coordinate of top left of level block
		:param tuple origin:  Coordinates to draw 'connecting' line to
		:param float height:  Block height budget
		:param int side:  What direction to move into: 1 for rightwards, -1 for leftwards
		:param bool init:  Whether the draw the top level of nodes. Only has an effect if
						   side == self.SIDE_LEFT
		:return:  Updated canvas
		"""
		if not level:
			return canvas

		# this eliminates a small misalignment where the left side of the
		# graph starts slightly too far to the left
		if init and side == self.SIDE_LEFT:
			x += self.step

		# determine how many nodes we'll need to fit on top of each other
		# within this block
		required_space_level = sum([self.max_breadth(node) for node in level])

		# draw each node and the tree below it
		for node in level:
			# determine how high this block will be based on the available
			# height and the nodes we'll need to fit in it
			required_space_node = self.max_breadth(node)

			block_height = (required_space_node / required_space_level) * height

			# determine how much we want to enlarge the text
			occurrence_ratio = node.occurrences / self.max_occurrences[level_index]
			if occurrence_ratio >= 0.75:
				embiggen = 3
			elif occurrence_ratio > 0.5:
				embiggen = 2
			elif occurrence_ratio > 0.25:
				embiggen = 1.75
			elif occurrence_ratio > 0.15:
				embiggen = 1.5
			else:
				embiggen = 1

			# determine how large the text block will be (this is why we use a
			# monospace font)
			characters = len(node.name)
			text_width = characters * self.step
			text_width *= (embiggen * 1)

			text_offset_y = self.fontsize if self.align == "top" else ((block_height) / 2)

			# determine where in the block to draw the text and where on the
			# canvas the block appears
			block_position = (x, y)
			block_offset_x = -(text_width + self.step) if side == self.SIDE_LEFT else 0

			self.x_min = min(self.x_min, block_position[0] + block_offset_x)
			self.x_max = max(self.x_max, block_position[0] + block_offset_x + text_width)

			# the first node on the left side of the graph does not need to be
			# drawn if the right side is also being drawn because in that case
			# it's already going to be included through that part of the graph
			if not (init and side == self.SIDE_LEFT):
				container = SVG(
					x=block_position[0] + block_offset_x,
					y=block_position[1],
					width=text_width,
					height=block_height,
					overflow="visible"
				)
				container.add(Text(
					text=node.name,
					insert=(0, text_offset_y),
					alignment_baseline="middle",
					style="font-size:" + str(embiggen) + "em"
				))
				canvas.add(container)
			else:
				# adjust position to make left side connect to right side
				x += text_width
				block_position = (block_position[0] + text_width, block_position[1])

			# draw the line connecting this node to the parent node
			if origin:
				destination = (x - self.step, y + text_offset_y)

				# for the left side of the graph, draw a curve leftwards
				# instead of rightwards
				if side == self.SIDE_RIGHT:
					bezier_origin = origin
					bezier_destination = destination
				else:
					bezier_origin = (destination[0] + self.step, destination[1])
					bezier_destination = (origin[0] - self.step, origin[1])

				# bezier curve control points
				control_x = bezier_destination[0] - ((bezier_destination[0] - bezier_origin[0]) / 2)
				control_left = (control_x, bezier_origin[1])
				control_right = (control_x, bezier_destination[1])

				# draw curve
				flow = Path(stroke="#000", fill_opacity=0, stroke_width=1.5)
				flow.push("M %f %f" % bezier_origin)
				flow.push("C %f %f %f %f %f %f" % tuple([*control_left, *control_right, *bezier_destination]))
				canvas.add(flow)

			# bezier curves for the next set of nodes will start at these
			# coordinates
			new_origin = (block_position[0] + ((text_width + self.step) * side), block_position[1] + text_offset_y)

			# draw this node's children
			canvas = self.render(canvas, node.children, x=x + ((text_width + self.gap) * side), y=y, origin=new_origin,
								 height=int(block_height), side=side, init=False, level_index=level_index+1)
			y += block_height

		return canvas

	def merge_upwards(self, node):
		"""
		Merge a node with the parent node if it has no siblings

		Used to string together tokens into one longer text string

		:param Node node:
		"""
		if not node or not node.parent:
			return

		parent = node.parent
		if len(node.siblings) == 0:
			node.parent.name += " " + node.name
			# we need a reference because after the next line the node will
			# have no parent
			node.parent.children = node.children

		self.merge_upwards(parent)

	def invert_node_labels(self, node):
		"""
		Invert the word order in node labels

		Used for nodes on the left side of the tree view, which would be the
		wrong way around otherwise.

		:param node:
		"""
		if hasattr(node, "is_inverted"):
			return

		node.is_inverted = True
		node.name = " ".join(reversed(node.name.split(" ")))
		for child in node.children:
			self.invert_node_labels(child)

	def max_children(self, node, current_max=1):
		"""
		Get max amount of children of any node under the given node

		:param Node node:  Node to check
		:param int current_max:  Max amount found so far
		:return int:
		"""
		for child in node.children:
			current_max = max(current_max, self.max_children(child, current_max))

		return max(len(node.children), current_max)

	def max_breadth(self, node):
		"""
		Get max sibling nodes at any underlying level of children for a node

		:param Node node:  Node to check
		:return int:
		"""
		return len([descendant for descendant in node.descendants if not descendant.children]) + 1

	def sort_node(self, node):
		"""
		Sort node recursively by most children

		:param Node node:
		:return Node:
		"""
		if node.children:
			node.children = [self.sort_node(child) for child in node.children]

		node.children = sorted(node.children, reverse=True, key=lambda x: len(x.children))
		return node

	def limit_subtree(self, node):
		"""
		Limit the amount of branches in a (sub)tree

		Branches are sorted by most occurences and then the top n are kept.

		:param node: Node of which to filter children
		:return:  Node, with pruned branches
		"""
		if node.children:
			node.children = [self.limit_subtree(child) for child in node.children]

		node.children = sorted(node.children, reverse=True, key=lambda x: x.occurrences)[0:self.limit]
		return node
