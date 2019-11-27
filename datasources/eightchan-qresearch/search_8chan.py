"""
8chan Search via Sphinx
"""
from datasources.fourchan.search_4chan import Search4Chan


class Search8Chan(Search4Chan):
	"""
	Search 8chan corpus

	Defines methods that are used to query the 8chan data indexed and saved.

	Apart from the prefixes, this works identically to the 4chan searcher, so
	most methods are inherited from there.
	"""
	type = "8chan-search"
	sphinx_index = "8chan"
	prefix = "8chan"