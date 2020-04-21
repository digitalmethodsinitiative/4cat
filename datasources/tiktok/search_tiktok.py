"""
Search TikTok via web scraping

TikTok is, after a fashion, an imageboard - people post videos and then
other people reply. So this datasource uses this affordance to retrieve
TikTok data for 4CAT.
"""
import asyncio
import re

from bs4 import BeautifulSoup
from pyppeteer import errors, page, launch
from pyppeteer_stealth import stealth

from backend.abstract.search import Search
from backend.lib.helpers import expand_short_number
from backend.lib.exceptions import QueryParametersException, ProcessorInterruptedException


class SearchTikTok(Search):
	"""
	TikTok scraper

	Since TikTok has no API of its own, we use pyppeteer to start a headless
	browser that we manipulate to browse the TikTok website and download the
	information we need. Unfortunately this is a bit limited - it's slower and
	requires far more resources than using an API or directly scraping HTML.
	The latter is not possible as TikTok loads everything asynchronously so the
	HTML one scrapes has no useful data. The website also does not include any
	comments, so those cannot be scraped this way.

	It's the best we can do, for now!
	"""
	type = "tiktok-search"  # job ID
	category = "Search"  # category
	title = "Search TikTok"  # title displayed in UI
	description = "Retrieve TikTok posts by hashtag or user, in TikTok's own order of preference."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	# not available as a processor for existing datasets
	accepts = [None]

	# let's not get rate limited
	max_workers = 1

	def get_posts_simple(self, parameters):
		"""
		Run custom search

		Fetches data from TikTok

		:return list:  List of dictionaries, one per scraped post
		"""
		max_posts = self.dataset.parameters.get("items", 10)
		queries = self.dataset.parameters.get("query").split(",")

		loop = asyncio.new_event_loop()
		posts = loop.run_until_complete(self.get_posts_async(queries, max_posts))
		loop.close()

		return posts

	async def get_browser(self):
		"""
		Get a new browser instance

		The scraper seemed to hang when re-using browser or page instances, so
		unfortunately we'll have to use a new browser instance every time -
		this method returns one with the proper settings
		:return pyppeteer.browser.Browser:
		"""
		return await launch(options={"defaultViewport": {"width": 1920, "height": 1080}, "handleSIGINT": False, "handleSIGHUP": False, "handleSIGTERM": False})

	async def get_posts_async(self, queries, limit):
		"""
		Get posts for queries

		This is not in get_posts_simple(), since we need to run this
		asynchronously (as that is how Pyppeteer works), and thus it needs to
		be done outside of a function where the event loop gets instantiated.

		Loads posts for a query via the overview page first, and then scrapes
		data for individual posts that have been collected.

		:param list queries:  Items to scrape, @usernames or #hashtags
		:param int limit:  Amount of posts to scrape per item
		:return list:  List of dictionaries, one per scraped post
		"""

		# we cannot handle signals as this runs in a thread, so disable those
		# handlers launching the browser

		try:
			# scrape overview pages for items first to get individual post URLs
			posts = []
			for query in queries:
				posts += await self.fetch_overview_page(query, limit)

			everything = []

			# then scrape each post's page to get post data
			for index, post in enumerate(posts):
				self.dataset.update_status("Getting post data for post %i/%i" % (index + 1, len(posts)))
				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while fetching post data from TikTok")
				post_data = await self.fetch_post(post["tiktok_url"])
				if not post_data:
					everything.append(post)
				else:
					everything.append(post_data)

		except ProcessorInterruptedException as e:
			raise ProcessorInterruptedException(str(e))

		self.dataset.update_status("Finished scraping TikTok website.")
		return everything

	async def fetch_overview_page(self, item, limit=1):
		"""
		Scrape all items for a given hashtag

		These are scraped from the hashtag overview page, which will be
		scrolled until the required amount of items have been found or no more
		items are loaded.

		:param str item: Item ID, a username (if starting with '@') or hashtag
		(if starting with '#')
		:param int limit:  Amount of posts to scrape
		:return list:  A list of posts that were scraped
		"""
		browser = await self.get_browser()
		page = await browser.newPage()
		await stealth(page)

		if item[0] == "#":
			# hashtag query
			url = "https://www.tiktok.com/tag/%s" % item[1:]
		else:
			# user query
			url = "https://www.tiktok.com/%s" % item

		try:
			await page.goto(url, option={"timeout": 5000})
			# this waits until the first video items have been loaded as these
			# are loaded asynchronously
			await page.waitForFunction("document.querySelectorAll('a.video-feed-item-wrapper').length > 0",
									   option={"timeout": 2500})
		except errors.TimeoutError:
			# takes too long to load videos... 1000 may be a bit too strict?
			await browser.close()
			await page.close()
			return []

		items = 0
		while True:
			# TikTok's overview page is one of those infinite scroll affairs,
			# so we scroll down until we have enough posts to then scrape
			# individually
			self.dataset.update_status("Getting post URLs for '%s' (%i so far)" % (item, items))
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while fetching post list from TikTok")

			# we can determine whether the new items after scrolling have
			# loaded through the page height. We give 100 pixels leeway
			# since the loading indicator itself takes up some space and we
			# don't want to interpret its appearance as the document actually
			# having scrolled properly
			page_height = await page.evaluate("document.body.scrollHeight")
			await page.evaluate("window.scrollTo(0,document.body.scrollHeight)")
			try:
				await page.waitForFunction("(document.body.scrollHeight > %i)" % (page_height + 100), option={"timeout": 1000})
			except errors.TimeoutError:
				break

			# the amount of videos on the page:
			items = await page.evaluate("document.querySelectorAll('a.video-feed-item-wrapper').length")
			if int(items) >= limit:
				break

		posts = await page.querySelectorAll("a.video-feed-item-wrapper")
		result = []
		for post in posts[0:limit]:
			# most of these are placeholders, since we know very little based
			# on just the overview page, but we need to define these
			# nevertheless in case the scrape for the post data goes wrong
			# in which case this is where the post gets defined (and something
			# is better than nothing)
			href = await page.evaluate('(element) => element.getAttribute("href")', post)
			bits = href.split("/")
			try:
				result.append({
					"id": bits[5],
					"thread_id": bits[5],
					"author_name": bits[3],
					"author_name_full": "",
					"subject": "",
					"body": "",
					"timestamp": 0,
					"has_harm_warning": "",
					"music_name": "",
					"music_url": "",
					"video_url": "",
					"tiktok_url": href,
					"likes": "",
					"comments": "",
					"hashtags": "",
					"fully_scraped": False
				})
			except IndexError:
				self.log.warning("Invalid TikTok URL %s, skipping" % href)
				continue

		await page.close()
		await browser.close()
		return result

	async def fetch_post(self, post_url):
		"""
		Fetch TikTok post data

		Retrieves data for a given post URL.

		:param str post_url:  URL of the post's page
		:return dict:  Post data
		"""
		browser = await self.get_browser()
		page = await browser.newPage()
		await stealth(page)

		try:
			await page.goto(post_url, options={"timeout": 10000})
		except errors.TimeoutError:
			# page took too long to load
			await page.close()
			await browser.close()
			return None

		# most of the post data can simply be gotten from one HTML element or
		# another or its attributes
		bits = post_url.split("/")
		data = {}

		try:
			data["id"] = bits[-1]
			data["thread_id"] = bits[-1]
			data["author_name"] = await page.evaluate('document.querySelector(".user-info .user-username").innerHTML')
			data["author_name_full"] = await page.evaluate('document.querySelector(".user-info .user-nickname").innerHTML')
			data["subject"] = ""
			data["body"] = await page.evaluate('document.querySelector(".video-meta-info .video-meta-title").innerHTML')
			data["timestamp"] = 0
			data["has_harm_warning"] = bool(await page.evaluate("document.querySelectorAll('.warn-info').length > 0"))
			data["music_name"] = await page.evaluate('document.querySelector(".music-info a").innerHTML')
			data["music_url"] = await page.evaluate('document.querySelector(".music-info a").getAttribute("href")')
			data["video_url"] = await page.evaluate('document.querySelector(".video-card video").getAttribute("src")')
			data["tiktok_url"] = post_url
		except Exception as e:
			self.log.warning("Skipping post %s for TikTok scrape (%s)" % (post_url, e))
			return None


		# these are a bit more involved
		counts = await page.evaluate('document.querySelector(".video-meta-info .video-meta-count").innerHTML')
		data["likes"] = expand_short_number(counts.split(" ")[0])
		data["comments"] = expand_short_number(counts.split(" ")[-2])
		data["hashtags"] = ",".join([tag.replace("?", "") for tag in re.findall(r'href="/tag/([^"]+)"', data["body"])])

		# we strip the HTML here because TikTok does not allow user markup
		# anyway, so this is not really significant
		body_soup = BeautifulSoup(data["body"], "html.parser")
		data["body"] = body_soup.text.strip()
		data["fully_scraped"] = True

		await page.close()
		await browser.close()
		return data

	def get_search_mode(self, query):
		"""
		Instagram searches are always simple

		:return str:
		"""
		return "simple"

	def get_posts_complex(self, query):
		"""
		Complex post fetching is not used by the Instagram datasource

		:param query:
		:return:
		"""
		pass

	def fetch_posts(self, post_ids, where=None, replacements=None):
		"""
		Posts are fetched via URL instead of ID for this datasource

		:param post_ids:
		:param where:
		:param replacements:
		:return:
		"""
		pass

	def fetch_threads(self, thread_ids):
		"""
		Thread filtering is not a toggle for TikTok datasets

		:param thread_ids:
		:return:
		"""
		pass

	def get_thread_sizes(self, thread_ids, min_length):
		"""
		Thread filtering is not a toggle for TikTok datasets

		:param tuple thread_ids:
		:param int min_length:
		results
		:return dict:
		"""
		pass

	def validate_query(query, request, user):
		"""
		Validate custom data input

		Confirms that the uploaded file is a valid CSV file and, if so, returns
		some metadata.

		:param dict query:  Query parameters, from client-side.
		:param request:  Flask request
		:param User user:  User object of user who has submitted the query
		:return dict:  Safe query parameters
		"""

		# 'location' would be possible as well but apparently requires a login
		if query.get("search_scope", "") not in ("hashtag", "username"):
			raise QueryParametersException("Invalid search scope: must be hashtag or username")

		# no query 4 u
		if not query.get("query", "").strip():
			raise QueryParametersException("You must provide a search query.")

		# 100 is mostly arbitrary - may need tweaking
		max_posts = 100 if not user.get_value("tiktok.allow_more_posts", False) and not user.is_admin() else 1000
		if query.get("max_posts", ""):
			try:
				max_posts = min(abs(int(query.get("max_posts"))), max_posts)
			except TypeError:
				raise QueryParametersException("Provide a valid number of posts to query.")

		# reformat queries to be a comma-separated list with no wrapping
		# whitespace
		whitespace = re.compile(r"[@#\s]+")
		items = whitespace.sub("", query.get("query").replace("\n", ",")).split(",")

		if len(items) > 5:
			raise QueryParametersException("You cannot query more than 5 items at a time.")

		sigil = "#" if query.get("search_scope") == "hashtag" else "@"
		items = ",".join([sigil + item for item in items])

		# simple!
		return {
			"items": max_posts,
			"query": items,
			"board": query.get("search_scope") + "s",  # used in web interface
			"search_scope": query.get("search_scope")
		}