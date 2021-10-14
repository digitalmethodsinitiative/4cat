"""
Make word clouds of columns with text and values

"""

from wordcloud import WordCloud

import config
from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput

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

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor on rankable items

		:param module: Dataset or processor to determine compatibility with
		"""
		return module.type in ("tfidf", "collocations", "vector-ranker", "similar-word2vec", "topic-model-words", "extract-nouns", "get-entities")

	@classmethod
	def get_options(self, parent_dataset=None, user=None):
		
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
					"help": "Word column"
				},
				"count_column": {
					"type": UserInput.OPTION_CHOICE,
					"options": parent_columns,
					"help": "Count column"
				},
				"to_lower": {
					"type": UserInput.OPTION_TOGGLE,
					"default": True,
					"help": "Convert to lowercase?"
				},
				"max_words": {
					"type": UserInput.OPTION_TEXT,
					"default": 200,
					"help": "Convert to lowercase?"
				}
			}
		return options
		
	def process(self):
		"""
		Render an SVG histogram/bar chart using a previous frequency analysis
		as input.
		"""

		words = {}

		word_column = self.parameters.get("word_column")
		count_column = self.parameters.get("count_column")
		to_lower = self.parameters.get("to_lower")
		try:
			max_words = int(self.parameters.get("max_words"))
		except (ValueError, TypeError) as e:
			max_words = self.parameters["max_words"]["default"]

		self.dataset.update_status("Extracting words and counts.")

		if not word_column:
			self.dataset.update_status("Please set a valid word column.")
			self.finish(0)

		if not count_column:
			self.dataset.update_status("Please set a valid count column.")
			self.finish(0)
			return

		for post in self.iterate_items(self.source_file):

			word = post[word_column]
			if to_lower:
				word = word.lower()
			if len(word) > 50:
				word = word[:47] + "..."

			try:
				count = int(post[count_column])
			except ValueError:
				self.dataset.update_status("Couldn't convert value '%s' to an integer. Please set a valid count column." % post[count_column])
				self.dataset.finish(0)
				return

			# Add to general dict
			if word in words:
				words[word] += count
			else:
				words[word] = count

		self.dataset.update_status("Making word cloud.")
		cloud = WordCloud(prefer_horizontal=1, background_color="rgba(255, 255, 255, 0)", mode="RGBA", color_func=lambda *args, **kwargs: (0,0,0), width=1600, height=1000, collocations=False, max_words=max_words).generate_from_frequencies(words)
		
		# Write to svg
		cloud = cloud.to_svg(embed_font=True)
		file = open(self.dataset.get_results_path(), "w")
		file.write(cloud)
		self.dataset.finish(1)