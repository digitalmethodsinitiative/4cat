"""
Filter by unique posts
"""
import json

from processors.filtering.base_filter import BaseFilter
from common.lib.helpers import UserInput

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen", "Stijn Peeters"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"


class UniqueFilter(BaseFilter):
	"""
	Retain only posts matching a given lexicon
	"""
	type = "unique-filter"  # job type ID
	category = "Filtering"  # category
	title = "Filter for unique items"  # title displayed in UI
	description = "Only keeps the first encounter of an item. This creates a new dataset."  # description displayed in UI

	# the following determines the options available to the user via the 4CAT
	# interface.
	options = {
		"columns": {
			"type": UserInput.OPTION_TEXT,
			"help": "Item attributes to consider for uniqueness",
			"inline": True,
			"default": "body"
		},
		"match-multiple": {
			"type": UserInput.OPTION_CHOICE,
			"help": "Match multiple values",
			"default": "all",
			"options": {
				"all": "Consider duplicate if all selected values are identical",
				"any": "Consider duplicate if any selected values are identical"
			},
			"tooltip": "When matching on multiple values, you can choose to discard items if all provided values "
					   "match a similar combination of values in another item, or if any single value has been "
					   "seen before. Ignored when matching on a single value."
		},
		"fold-case": {
			"type": UserInput.OPTION_TOGGLE,
			"help": "Case insensitive",
			"default": False,
			"tooltip": "Selecting this will e.g. consider 'Cat' and and 'cat' as identical."
		},
	}

	@classmethod
	def is_compatible_with(cls, module=None, user=None):
		"""
		Allow processor on NDJSON and CSV files

		:param module: Module to determine compatibility with
		"""
		return module.is_top_dataset() and module.get_extension() in ("csv", "ndjson")

	def filter_items(self):
		"""
		Create a generator to iterate through items that can be passed to create either a csv or ndjson. Use
		`for original_item, mapped_item in self.source_dataset.iterate_mapped_items(self)` to iterate through items
		and yield `original_item`.

		:return generator:
		"""
		# now for the real deal
		self.dataset.update_status("Reading source file")

		# keep some stats
		processed = 0
		unique = 0

		match_mode = self.parameters.get("match-multiple", "all")
		fold_case = self.parameters.get("fold-case", False)
		columns = self.parameters.get("columns")
		if type(columns) is str:
			columns = {columns}
		else:
			columns = set(columns)

		# use sets, which auto-hash and deduplicate
		known_values = {column: set() for column in columns}
		known_items = set()

		# iterate through posts and see if they match
		for original_item, mapped_item in self.source_dataset.iterate_mapped_items(self):
			unique_item = False

			if match_mode == "all":
				# we can't hash a dictionary
				# so instead, hash the json dump of the dictionary!
				full_item = json.dumps({k: v for k, v in mapped_item.items() if k in columns})
				if full_item not in known_items:
					unique_item = True
					known_items.add(full_item)

			elif match_mode == "any":
				unique_columns = set()
				for column in columns:
					value = mapped_item.get(column)
					if type(value) is str and fold_case:
						value = value.lower()

					if value not in known_values[column]:
						unique_columns.add(column)
						known_values[column].add(value)

				if unique_columns == columns:
					unique_item = True

			if unique_item:
				unique += 1
				yield original_item

			if processed % 500 == 0:
				self.dataset.update_status("Processed %i posts (%i unique)" % (processed, unique))
				self.dataset.update_progress(processed / self.source_dataset.num_rows)

			processed += 1

	@classmethod
	def get_options(cls, parent_dataset=None, user=None):
		"""
		Get processor options

		This method by default returns the class's "options" attribute, or an
		empty dictionary. It can be redefined by processors that need more
		fine-grained options, e.g. in cases where the availability of options
		is partially determined by the parent dataset's parameters.

		:param DataSet parent_dataset:  An object representing the dataset that
		the processor would be run on
		:param User user:  Flask user the options will be displayed for, in
		case they are requested for display in the 4CAT web interface. This can
		be used to show some options only to privileges users.
		"""
		options = cls.options

		# Get the columns for the select columns option
		if parent_dataset and parent_dataset.get_columns():
			columns = parent_dataset.get_columns()
			options["columns"]["type"] = UserInput.OPTION_MULTI
			options["columns"]["options"] = {v: v for v in columns}
			options["columns"]["default"] = "body" if "body" in columns else None

		return options
