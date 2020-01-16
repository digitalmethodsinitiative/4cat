"""
Thread scraper

Parses 8chan API data, saving it to database and queueing downloads
"""
from datasources.fourchan.scrapers.scrape_threads import ThreadScraper4chan


class ThreadScraper8chan(ThreadScraper4chan):
	"""
	Scrape 8chan threads

	8chan's API is compatible with 4chan's, so we extend the 4chan thread scraper to
	work with the 8chan API instead
	"""
	type = "8chan-thread"
	max_workers = 4

	# for new posts, any fields not in here will be saved in the "unsorted_data" column for that post as part of a
	# JSONified dict
	known_fields = ["no", "resto", "sticky", "closed", "archived", "archived_on", "now", "time", "name", "trip", "id",
					"capcode", "country", "country_name", "sub", "com", "tim", "filename", "ext", "fsize", "md5", "w",
					"h", "tn_w", "tn_h", "filedeleted", "spoiler", "custom_spoiler", "omitted_posts", "omitted_images",
					"replies", "images", "bumplocked", "imagelimit", "capcode_replies", "last_modified", "tag",
					"semantic_url", "since4pass", "unique_ips", "tail_size", "fpath", "cyclical", "locked"]

	# these fields should be present for every single post, and if they're not something weird is going on
	required_fields = ["no", "resto", "time"]
	required_fields_op = ["no", "resto", "time"]

	def get_url(self):
		"""
		Get URL to scrape for the current job

		:return string: URL to scrape
		"""
		thread_id = self.job.data["remote_id"].split("/").pop()
		url = "https://8kun.net/%s/res/%s.json" % (self.job.details["board"], thread_id)
		return url

	def queue_image(self, post, thread):
		"""
		We're not scraping images for 8chan

		:param post:  Post data
		:param thread:   Thread data
		"""
		pass