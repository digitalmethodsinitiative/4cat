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
	return_cols = ["id", "thread_id", "reply_to", "author", "timestamp", "body", "likes", "dislikes", "subject"]

	def after_search(self, posts):
		"""
		Post-process search results

		Breitbart has some thread-level metadata that is useful to add to the
		result, so this method fetches metadata for all full articles in the
		dataset and adds it to those rows.

		:param list posts:  Posts found for the query
		:return list:  Posts with thread-level metadata added
		"""
		processed_posts = []

		thread_ids = set()
		for post in posts:
			if post["thread_id"] == post["id"] and post["subject"]:
				thread_ids.add(post["thread_id"])

		if thread_ids:
			self.dataset.update_status("Fetching thread metadata for %i threads..." % len(thread_ids))
			thread_metadata = {row["id"]: {"url": row["url"], "section": row["section"], "tags": row["tags"]} for row in
							   self.db.fetchall_interruptable(self.queue, "SELECT id, url, section, tags FROM threads_breitbart WHERE id IN %s",
															  tuple(thread_ids))}

			self.dataset.update_status("Adding metadata to %i articles..." % len(thread_ids))
			while posts:
				post = posts.pop(0)
				if post["subject"] and post["thread_id"] in thread_ids:
					post = {**post, **thread_metadata[post["thread_id"]]}
				else:
					post = {**post, **{"url": "", "section": "", "tags": ""}}

				processed_posts.append(post)
		else:
				processed_posts = posts

		return processed_posts

	def validate_query(query, request, user):
		"""
		Validate input for a dataset query on the 4chan data source.

		Will raise a QueryParametersException if invalid parameters are
		encountered. Mutually exclusive parameters may also be sanitised by
		ignoring either of the mutually exclusive options.

		:param dict query:  Query parameters, from client-side.
		:param request:  Flask request
		:param User user:  User object of user who has submitted the query
		:return dict:  Safe query parameters
		"""
		request = Search4Chan.validate_query(query, request, user)
		request["board"] = "*"

		return request
