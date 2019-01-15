from backend.abstract.string_query import StringQuery


class Search4Chan(StringQuery):
	type = "4chan-search"
	sphinx_index = "4chan"
	prefix = "4chan"

	def fetch_posts(self, post_ids):
		columns = ", ".join(self.return_cols)
		return self.db.fetchall("SELECT " + columns + " FROM posts_" + self.prefix + " WHERE id IN %s ORDER BY id ASC",
								(post_ids,))

	def fetch_threads(self, thread_ids):
		columns = ", ".join(self.return_cols)
		return self.db.fetchall(
			"SELECT " + columns + " FROM posts_" + self.prefix + " WHERE thread_id IN %s ORDER BY thread_id ASC, id ASC",
			(thread_ids,))

	def fetch_sphinx(self, where, replacements):
		sql = "SELECT thread_id, post_id FROM `" + self.sphinx_index + "_posts` WHERE " + where + " LIMIT 5000000 OPTION max_matches = 5000000"
		self.log.info("Running Sphinx query %s " % sql)
		return self.sphinx.fetchall(sql, replacements)
