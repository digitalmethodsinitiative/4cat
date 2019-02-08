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

	def fetch_threads(self, thread_ids):
		"""
		Fetch post from database for given threads

		:param list thread_ids: List of thread IDs to return post data for
		:return list: List of posts, with a dictionary representing the database record for each post
		"""
		columns = ", ".join(self.return_cols)

		thread_ids = tuple([str(thread_id) for thread_id in thread_ids])
		return self.db.fetchall(
			"SELECT " + columns + " FROM posts_" + self.prefix + " WHERE thread_id IN %s ORDER BY thread_id ASC, id ASC",
			(thread_ids,))
