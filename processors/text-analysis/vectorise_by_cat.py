"""
Transform tokeniser output into vectors by category w/ filter
"""
import csv
import json
import pickle

from backend.lib.processor import BasicProcessor
from common.lib.helpers import UserInput

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl", "Stijn Peeters"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"

class VectoriseByCategory(BasicProcessor):
	"""
	Creates word vectors from tokens and organises them by category.
	"""
	type = "vectorise-tokens-by-category"  # job type ID
	category = "Text analysis"  # category
	title = "Count words by category"  # title displayed in UI
	description = "Counts all tokens and categorizes them so they are transformed into category => token => frequency counts. " \
				  "This is also known as a bag of words."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	followups = ["wordcloud", "render-graphs-isometric", "render-rankflow"]

	@classmethod
	def is_compatible_with(cls, module=None, config=None):
		"""
		Allow processor on token sets

		:param module: Module to determine compatibility with
		"""
		return module.type == "tokenise-posts"

	@classmethod
	def get_options(cls, parent_dataset=None, config=None):
		"""
		Allow user to select category column
		"""
		#TODO: Network, allow weight column or calculate weight (i.e., as it normally does)
		#TODO: test word cloud; edit word cloud to optionally add weight to words
		options = {
			"category": {
				"type": UserInput.OPTION_CHOICE,
				"help": "Category column",
				"options": {},
			},
			"split_categories": {
				"type": UserInput.OPTION_TOGGLE,
				"default": False,
				"help": "Split category column by comma?",
				"tooltip": "If enabled, values separated by commas are considered separate categories. "
						   "Useful if columns contain e.g. lists of hashtags. This will create multiple "
						   "entries for each document's words/tokens that has more than one category."
			},
			"separate_by_interval": {
				"type": UserInput.OPTION_TOGGLE,
				"default": False,
				"help": "Separate by interval?",
				"tooltip": "If enabled, categories and tokens are separated per interval enabling comparisons over time. "
						   "Interval used is based on selection in the tokenization process."
			},
			# This is a OPTION_CHOICE to take advantage of the filtering options
			"threshold_type": {
				"type": UserInput.OPTION_CHOICE,
				"help": "Threshold Filter",
				"options": {
					"none": "All words/tokens included",
					"true": "Filter by number of occurrences",
				},
				"default": "none",
				"tooltip": "Per category, only include words/tokens that are above a certain threshold and only the top N number of words/tokens."
			},
			"threshold_value": {
				"type": UserInput.OPTION_TEXT,
				"default": 1,
				"help": "Threshold (include if >= X occurrences)",
				"coerce_type": int,
				"min": 1,
				"tooltip": "Only include words/tokens that occur at least this many times in a given category",
				"requires": "threshold_type=true",
			},
			"top_n": {
				"type": UserInput.OPTION_TEXT,
				"default": 0,
				"help": "Top N words/tokens per category",
				"coerce_type": int,
				"min": 0,
				"tooltip": "Only include the top N words/tokens in a given category (0 includes all)",
				"requires": "threshold_type=true",
			},
			# This is a OPTION_CHOICE to take advantage of the filtering options
			"use_word_filter": {
				"type": UserInput.OPTION_CHOICE,
				"help": "Word Filter",
				"options": {
					"none": "All words/tokens included",
					"include": "Only include certain words/tokens",
					"exclude": "Exclude certain words/tokens",
				},
				"default": "none",
			},
			"word_filter_list": {
				"type": UserInput.OPTION_TEXT,
				"default": "",
				"help": "Words/tokens to include/exclude",
				"tooltip": "Either include or exclude words/tokens based on the Word Filter selection; separate words/tokens by commas for exact matches",
				"requires": "use_word_filter!=none",
			},
		}

		# Get category column
		if not parent_dataset:
			return options
		category_dataset = cls.get_category_dataset(parent_dataset)
		if not category_dataset or not category_dataset.get_columns():
			return options
		cat_columns = {c: c for c in sorted(category_dataset.get_columns())}
		options.update({
			"category": {
				"type": UserInput.OPTION_CHOICE,
				"options": cat_columns,
				"help": "Category column",
			},
		})
		return options

	@staticmethod
	def get_category_dataset(dataset):
		"""
		Get the dataset that contains the category column; this should be the dataset above the tokenise-posts dataset
		"""
		genealogy = dataset.get_genealogy()

		# Find parent of tokenise-posts dataset; this dataset will contain the categories related to the tokens extracted from it
		tokeniser_found = False
		for source_dataset in reversed(genealogy):
			if tokeniser_found:
				return source_dataset
			if source_dataset.type == "tokenise-posts":
				tokeniser_found = True
		return None

	def process(self):
		"""
		Unzips token sets, vectorises them and zips them again.
		"""
		# Get metadata
		self.dataset.update_status("Collecting token and post/category metadata")
		try:
			metadata_file = self.extract_archived_file_by_name(".token_metadata.json", self.source_file)
		except FileNotFoundError:
			self.dataset.finish_with_error("Metadata file not found; cannot match categories to tokens")
			return
		with open(metadata_file) as file:
			metadata = json.load(file)

		# Check token metadata is correct format
		metadata.pop('parameters') # remove parameters as we do not need them
		first_key = next(iter(metadata))
		for interval, token_data in metadata[first_key].items():
			if any([required_keys not in token_data for required_keys in
					['filename', 'document_numbers']]):
				self.dataset.finish_with_error("Token metadata is not in correct format; please re-run tokenise-posts processor if not run since 4CAT update")
				return
			break

		# Get source dataset for categories
		category_dataset = self.get_category_dataset(self.source_dataset)
		self.for_cleanup.append(category_dataset)
		if not category_dataset:
			self.dataset.finish_with_error("No top dataset found; unable to identify categories")
			return

		# Create file/docs to categories
		category_column = self.parameters.get("category")
		split_comma = self.parameters.get("split_categories")
		file_to_category_mapping = {}
		for row in category_dataset.iterate_items():
			item_id = row.get("id")
			if not item_id or not row.get(category_column) or item_id not in metadata:
				# No item ID or category or metadata; skip
				continue
			# Possible to have multiple intervals/documents per item/post
			for interval, token_data in metadata[item_id].items():
				filename = token_data.get("filename")
				document_numbers = token_data.get("document_numbers")
				if split_comma:
					category_values = row.get(category_column).split(",")
				else:
					category_values = [row.get(category_column)]
				for document_number in document_numbers:
					file_to_category_mapping[(filename, document_number)] = category_values
		if not file_to_category_mapping:
			self.dataset.finish_with_error("No categories found")
			return

		# Get options
		threshold_type = self.parameters.get("threshold_type")
		threshold_value = self.parameters.get("threshold_value", None)
		top_n = self.parameters.get("top_n", None)
		use_word_filter = self.parameters.get("use_word_filter")
		word_filter_list = [word.strip().lower() for word in self.parameters.get("word_filter_list", "").split(",")]
		separate_by_interval = self.parameters.get("separate_by_interval")

		# go through all archived token sets and vectorise them
		self.dataset.update_status("Processing token sets")
		vector_sets = {}
		index = 0
		# Each file is a token set (Tokenize processor separates tokens by dates or all) and contains a list of tokens for each document
		# A single item/post may have multiple documents (e.g., if it was seperated by sentance)
		for packed_tokens in self.source_dataset.iterate_items():
			if packed_tokens.file.name == '.token_metadata.json':
				# Skip metadata
				continue

			index += 1
			vector_set_name = packed_tokens.file.stem  # we don't need the full path
			self.dataset.update_status("Processing token set %i (%s)" % (index, vector_set_name))
			self.dataset.update_progress(index / self.source_dataset.num_rows)

			# we support both pickle and json dumps of vectors
			token_unpacker = pickle if vector_set_name.split(".")[-1] == "pb" else json

			if not separate_by_interval:
				# Lump all intervals together
				vector_set_name = "all"

			if vector_set_name not in vector_sets:
				vector_sets[vector_set_name] = {}

			# temporarily extract file (we cannot use ZipFile.open() as it doesn't support binary modes)
			with packed_tokens.file.open("rb") as binary_tokens:
				# these were saved as pickle dumps so we need the binary mode
				documents = token_unpacker.load(binary_tokens)

				# Cycle through tokens
				for i, document in enumerate(documents):
					if (packed_tokens.file.name, i) not in file_to_category_mapping:
						# No category for this document
						self.dataset.log("No category found for document %s-%s" % (packed_tokens.file.name, i))
						continue

					# Allow for multiple categories
					categories = file_to_category_mapping[(packed_tokens.file.name, i)]
					for category in categories:
						if category not in vector_sets[vector_set_name]:
							vector_sets[vector_set_name][category] = {}
						for token in document:
							if token not in vector_sets[vector_set_name][category]:
								vector_sets[vector_set_name][category][token] = 1
							else:
								vector_sets[vector_set_name][category][token] += 1

		sets_of_categories = 0
		for interval, category_data in vector_sets.items():
			if not category_data:
				self.dataset.log(f"No tokens found for interval {interval}")
			else:
				sets_of_categories += 1

		if not sets_of_categories:
			self.dataset.finish_with_error("No tokens found")
			return

		# Write vectors to file
		self.dataset.update_status("Writing results file")
		done = 0
		with open(self.dataset.get_results_path(), "w", encoding="utf-8") as output:
			writer = csv.DictWriter(output, fieldnames=("date", "category", "item", "value"))
			writer.writeheader()
			for interval, category_data in vector_sets.items():
				for category, tokens in category_data.items():
					# Sort categories by frequency
					token_list = sorted(tokens.items(), key=lambda x: x[1], reverse=True)
					num_per_category = 0
					for token, frequency in token_list:
						# We filter here as opposed to during the vectorisation to avoid unnecessary calculations; i.e., choosing speed over memory
						if use_word_filter == "include" and token not in word_filter_list:
							# Skip if not in include list
							continue
						if use_word_filter == "exclude" and token in word_filter_list:
							# Skip if in exclude list
							continue
						if threshold_type == "true" and (frequency < threshold_value or (0 < top_n <= num_per_category)):
							# Skip if below threshold or top N reached; relies on sorted token_list
							break
						writer.writerow({"date": interval, "category": category, "item": token, "value": frequency})
						num_per_category += 1
						done += 1

		# Finish
		self.dataset.update_status("Finished")
		self.dataset.finish(done)

	@classmethod
	def exclude_followup_processors(cls, processor_type):
		"""
		Exclude followups if they are not compatible with the module
		"""
		if processor_type in ["consolidate-urls", "preset-neologisms", "sentence-split", "tokenise-posts", "image-downloader-stable-diffusion", "word-trees", "histogram", "extract-urls-filter"]:
			return True
		return False