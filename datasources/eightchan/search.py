"""
Search 8Chan corpus via Sphinx
"""
from datasources.fourchan.search import Search4Chan


class Search8Chan(Search4Chan):
	"""
	Search 8Chan via Sphinx

	Identical to 4chan's searcher, but with different identifiers.
	"""
	type = "8chan-search"
	sphinx_index = "8chan"
	prefix = "8chan"
