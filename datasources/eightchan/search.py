from datasources.fourchan.search import Search4Chan


class Search8Chan(Search4Chan):
	type = "8chan-search"
	sphinx_index = "8chan"
	prefix = "8chan"
