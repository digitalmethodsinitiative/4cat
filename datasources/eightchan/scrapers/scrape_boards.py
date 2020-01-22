"""
8Chan board scraper - indexes threads and queues them for scraping
"""
from datasources.fourchan.scrapers.scrape_boards import BoardScraper4chan


class BoardScraper8chan(BoardScraper4chan):
	"""
	Scrape 8chan boards

	8chan's API is compatible with 4chan's, so we extend the 4chan board scraper to
	work with the 8chan API instead
	"""
	type = "8chan-board"
	datasource = "8chan"
	max_workers = 4

	def get_url(self):
		"""
		Get URL to scrape for the current job

		:return string: URL to scrape
		"""
		board_id = self.job.data["remote_id"].split("/").pop()
		return "http://8kun.net/%s/threads.json" % board_id
