"""
4chan Search via Sphinx
"""
from backend.abstract.string_query import StringQuery


class Search4Chan(StringQuery):
	"""
	Search 4chan corpus

	Defines methods that are used to query the 4chan data indexed and saved.
	"""
	type = "4chan-search"  # job ID
	sphinx_index = "4chan"  # prefix for sphinx indexes for this data source. Should usually match sphinx.conf
	prefix = "4chan"  # table identifier for this platform; see below for usage

	def fetch_posts(self, post_ids):
		"""
		Fetch post data from database

		:param list post_ids:  List of post IDs to return data for
		:return list: List of posts, with a dictionary representing the database record for each post
		"""
		columns = ", ".join(self.return_cols)
		return self.db.fetchall("SELECT " + columns + " FROM posts_" + self.prefix + " WHERE id IN %s ORDER BY id ASC",
								(post_ids,))

	def fetch_threads(self, thread_ids):
		"""
		Fetch post from database for given threads

		:param list thread_ids: List of thread IDs to return post data for
		:return list: List of posts, with a dictionary representing the database record for each post
		"""
		columns = ", ".join(self.return_cols)
		return self.db.fetchall(
			"SELECT " + columns + " FROM posts_" + self.prefix + " WHERE thread_id IN %s ORDER BY thread_id ASC, id ASC",
			(thread_ids,))

	def fetch_sphinx(self, where, replacements):
		"""
		Query Sphinx for matching post IDs

		:param str where:  Drop-in WHERE clause (without the WHERE keyword) for the Sphinx query
		:param list replacements:  Values to use for parameters in the WHERE clause that should be parsed
		:return list:  List of matching posts; each post as a dictionary with `thread_id` and `post_id` as keys
		"""
		sql = "SELECT thread_id, post_id FROM `" + self.sphinx_index + "_posts` WHERE " + where + " LIMIT 5000000 OPTION max_matches = 5000000"
		self.log.info("Running Sphinx query %s " % sql)
		return self.sphinx.fetchall(sql, replacements)
