"""
8kun Search via Sphinx
"""
from datasources.fourchan.search_4chan import Search4Chan


class Search8Kun(Search4Chan):
	"""
	Search 8kun corpus

	Defines methods that are used to query the 8kun data indexed and saved.

	Apart from the prefixes, this works identically to the 4chan searcher, so
	most methods are inherited from there.
	"""
	type = "8kun-search"
	sphinx_index = "8kun"
	prefix = "8kun"