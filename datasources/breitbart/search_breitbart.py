"""
Breitbart Search via Sphinx
"""
from datasources.fourchan.search_4chan import Search4Chan


class SearchBreitbart(Search4Chan):
	"""
	Search Breitbart corpus

	Defines methods that are used to query the Breitbart data indexed and saved.

	Apart from the prefixes, this works identically to the 4chan searcher, so
	most methods are inherited from there.
	"""
	type = "breitbart-search"
	sphinx_index = "breitbart"
	prefix = "breitbart"


	# Columns to return in csv
	return_cols = ["id", "thread_id", "reply_to", "author", "timestamp", "likes", "dislikes"]