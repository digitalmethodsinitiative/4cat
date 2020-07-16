"""
8kun board scraper - indexes threads and queues them for scraping
"""
from datasources.fourchan.scrapers.scrape_boards import BoardScraper4chan


class BoardScraper8kun(BoardScraper4chan):
	"""
	Scrape 8kun boards

	8kun's API is compatible with 4chan's, so we extend the 4chan board scraper to
	work with the 8kun API instead
	"""
	type = "8kun-board"
	datasource = "8kun"
	max_workers = 4
	log_level="info"

	def get_url(self):
		"""
		Get URL to scrape for the current job

		:return string: URL to scrape
		"""
		board_id = self.job.data["remote_id"].split("/").pop()
		return "http://8kun.top/%s/threads.json" % board_id
