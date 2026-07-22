"""
Make word clouds of columns with text and values

"""

from wordcloud import WordCloud

from backend.lib.processor import BasicProcessor
from common.lib.compatibility import Compatibility
from common.lib.exceptions import QueryParametersException
from common.lib.helpers import UserInput, convert_to_int

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"


class MakeWordCloud(BasicProcessor):
	"""
	Generate activity histogram
	"""
	type = "wordcloud"  # job type ID
	category = "Visual"  # category
	title = "Word cloud"  # title displayed in UI
	description = "Generates a word cloud with words sized on occurrence."  # description displayed in UI
	extension = "svg"

	# Allow processor on rankable items
	compatibility = Compatibility(types={
		"tfidf", "collocations", "vector-ranker", "vectorise-tokens-by-category",
		"similar-word2vec", "extract-nouns", "get-entities"
	})

	@classmethod
	def get_options(cls, parent_dataset=None, config=None):

		options = {}
		if not parent_dataset:
			return options
		parent_columns = parent_dataset.get_columns()

		if parent_columns:
			parent_columns = {c: c for c in sorted(parent_columns)}
			options = {
				"word_column": {
					"type": UserInput.OPTION_CHOICE,
					"options": parent_columns,
					"help": "Word column",
					"default": "item" if "item" in parent_columns else "",
				},
				"count_column": {
					"type": UserInput.OPTION_CHOICE,
					"options": parent_columns,
					"help": "Count column",
					"default": "value" if "value" in parent_columns else "",
				},
				"to_lower": {
					"type": UserInput.OPTION_TOGGLE,
					"default": True,
					"help": "Convert to lowercase?"
				},
				"max_words": {
					"type": UserInput.OPTION_TEXT,
					"default": 200,
					"min": 1,
					"help": "Max words to show"
				}
			}
		return options

	@staticmethod
	def validate_query(query, request, config):
		"""
		Check that a word and count column were chosen

		The column choices default to an empty value when the parent dataset
		has no obvious word and count columns, so the form can be submitted
		with an empty choice. Catch that here so the user can fix it in the
		form, instead of the processor failing after it has started.

		:param dict query:  Query parameters, from client-side.
		:param request:  Flask request
		:param ConfigManager|None config:  Configuration reader (context-aware)
		:return dict:  Safe query parameters
		"""
		if "word_column" in query and not query.get("word_column"):
			raise QueryParametersException("Select the column containing the words for the word cloud.")

		if "count_column" in query and not query.get("count_column"):
			raise QueryParametersException("Select the column containing the word counts.")

		return query

	def process(self):
		"""
		Render an SVG histogram/bar chart using a previous frequency analysis
		as input.
		"""

		words = {}

		word_column = self.parameters.get("word_column")
		count_column = self.parameters.get("count_column")
		to_lower = self.parameters.get("to_lower")
		# form input is checked when the job is queued, but presets and other
		# code can start this processor with unchecked values, so make sure
		# the amount is a usable number here as well
		max_words = max(1, convert_to_int(self.parameters.get("max_words"), 200))

		self.dataset.update_status("Extracting words and counts.")

		# also checked when the job is queued, but kept for jobs started by
		# presets and other code, which skip that check
		if not word_column:
			self.dataset.finish_with_error("Please set a valid word column.")
			return

		if not count_column:
			self.dataset.finish_with_error("Please set a valid count column.")
			return

		for post in self.source_dataset.iterate_items(self):

			word = post[word_column]
			if to_lower:
				word = word.lower()
			if len(word) > 50:
				word = word[:47] + "..."

			try:
				count = int(post[count_column])
			except ValueError:
				self.dataset.finish_with_error(f"Couldn't convert value '{post[count_column]}' to an integer. Please set a valid count column.")
				return

			# Add to general dict
			if word in words:
				words[word] += count
			else:
				words[word] = count

		self.dataset.update_status("Making word cloud.")
		cloud = WordCloud(prefer_horizontal=1, background_color="rgba(255, 255, 255, 0)", mode="RGBA", color_func=lambda *args, **kwargs: (0,0,0), width=1600, height=1000, collocations=False, max_words=max_words).generate_from_frequencies(words)

		# Write to svg
		cloud = cloud.to_svg()
		file = open(self.dataset.get_results_path(), "w")
		file.write(cloud)
		self.dataset.finish(1)
