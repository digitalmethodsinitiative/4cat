"""
Search TikTok via web scraping

TikTok is, after a fashion, an imageboard - people post videos and then
other people reply. So this datasource uses this affordance to retrieve
TikTok data for 4CAT.
"""
import urllib.parse
import asyncio
import time
import re

from bs4 import BeautifulSoup
from pyppeteer import errors, launch
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
				posts += await self.fetch_from_overview_page(query, limit)
				time.sleep(3)  # give some time to clean up

		except ProcessorInterruptedException as e:
			raise ProcessorInterruptedException(str(e))

		self.dataset.update_status("Finished scraping TikTok website.")
		return posts

	async def fetch_from_overview_page(self, item, limit=1):
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
		elif item[0] == "@":
			# user query
			url = "https://www.tiktok.com/%s" % item
		else:
			# music
			music_id = item.split("?")[0].split("-")[-1]
			url = "https://www.tiktok.com/music/original-sound-%s" % music_id

		try:
			await page.goto(url, option={"timeout": 5000})
			# this waits until the first video items have been loaded as these
			# are loaded asynchronously
			await page.waitForFunction("document.querySelectorAll('a.video-feed-item-wrapper').length > 0",
									   option={"timeout": 5000})
		except errors.TimeoutError:
			# takes too long to load videos...
			await page.close()
			await browser.close()
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
				# a somewhat generous timeout here as as you scroll down on the
				# page it takes longer and longer to load the new posts
				await page.waitForFunction("(document.body.scrollHeight > %i)" % (page_height + 100), options={"timeout": 3000})
			except errors.TimeoutError:
				break

			# the amount of videos on the page:
			items = await page.evaluate("document.querySelectorAll('a.video-feed-item-wrapper').length")
			if int(items) >= limit:
				break

		# next determine what selector we need to use to find the modal window
		# containing the actual tiktok post. this seems to differ from time to
		# time (possibly resolution-related?) so we try a list until we find
		# one that works
		await page.click("a.video-feed-item-wrapper")
		selectors = [".video-card-big.browse-mode", ".video-card-modal"]
		have_selector = False

		while selectors:
			selector = selectors[0]
			selectors = selectors[1:]

			try:
				# just opening the modal is not enough - we need to know that
				# the post info has actually been loaded into it
				await page.waitForFunction("document.querySelectorAll('%s .user-info').length > 0" % selector,
										   options={"timeout": 2000})
				have_selector = True
				break
			except errors.TimeoutError:
				continue

		# if at this point we still don't have a selector it means that we
		# don't know how to find the post info in the page, so we can't scrape
		if not have_selector:
			self.dataset.update_status("Could not load post data. Scraping not possible.", is_final=True)
			await page.close()
			await browser.close()
			return []

		result = []
		while len(result) < limit:
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while downloading post data")

			# wait until the post info has been loaded asynchronously
			try:
				await page.waitForFunction("document.querySelectorAll('%s .user-info').length > 0" % selector,
										   options={"timeout": 2000})
			except errors.TimeoutError:
				continue

			# annoyingly the post URL does not seem to be loaded into the modal
			# but we can use the share buttons (that include the post URL in
			# their share URL) to infer it
			href = await page.evaluate("document.querySelector('%s .share-group a').getAttribute('href')" % selector)
			href = href.split("&u=")[1].split("&")[0]
			href = urllib.parse.unquote(href)
			bits = href.split("/")

			# now extract the data from the various page elements containing
			# them
			data = {}
			try:
				data["id"] = bits[-1]
				data["thread_id"] = bits[-1]
				data["author"] = await page.evaluate(
					'document.querySelector("%s .user-info .user-username").innerHTML' % selector)
				data["author_full"] = await page.evaluate(
					'document.querySelector("%s .user-info .user-nickname").innerHTML' % selector)
				data["subject"] = ""
				data["body"] = await page.evaluate(
					'document.querySelector("%s .video-meta-title").innerHTML' % selector)
				data["timestamp"] = 0
				data["has_harm_warning"] = bool(
					await page.evaluate("document.querySelectorAll('%s .warn-info').length > 0" % selector))
				data["music_name"] = await page.evaluate('document.querySelector("%s .music-info a").innerHTML' % selector)
				data["music_url"] = await page.evaluate(
					'document.querySelector("%s .music-info a").getAttribute("href")' % selector)
				data["video_url"] = await page.evaluate(
					'document.querySelector("%s video").getAttribute("src")' % selector)
				data["tiktok_url"] = href

				# these are a bit more involved
				data["likes"] = expand_short_number(
					await page.evaluate('document.querySelector("%s .like-text").innerHTML' % selector))
				data["comments"] = expand_short_number(
					await page.evaluate('document.querySelector("%s .comment-text").innerHTML' % selector))

				# we strip the HTML here because TikTok does not allow user markup
				# anyway, so this is not really significant
				data["hashtags"] = ",".join(
					[tag.replace("?", "") for tag in re.findall(r'href="/tag/([^"]+)"', data["body"])])
				body_soup = BeautifulSoup(data["body"], "html.parser")
				data["body"] = body_soup.text.strip()
				data["fully_scraped"] = True
			except Exception as e:
				self.log.warning("Skipping post %s for TikTok scrape (%s)" % (href, e))
				break


			# store data and - if possible - click the "next post" button to
			# load the next one. If the button does not exist, no more posts
			# can be loaded, so end the scrape
			result.append(data)
			if len(result) % 10 == 0:
				self.dataset.update_status("Scraped data for %i/%i posts..." % (len(result), min(items, limit)))

			has_next = int(await page.evaluate("document.querySelectorAll('%s .control-icon.arrow-right').length" % selector)) > 0
			if has_next:
				await page.click("%s .control-icon.arrow-right" % selector)
			else:
				break

		await page.close()
		await browser.close()

		return result

	def get_search_mode(self, query):
		"""
		TikTok searches are always simple

		:return str:
		"""
		return "simple"

	def get_posts_complex(self, query):
		"""
		Complex post fetching is not used by the TikTok datasource

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
		if query.get("search_scope", "") not in ("hashtag", "username", "music"):
			raise QueryParametersException("Invalid search scope: must be hashtag, username or music")

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

		sigil = {"hashtag": "#", "username": "@", "music": "🎶"}[query.get("search_scope")]
		items = ",".join([sigil + item for item in items])

		# simple!
		return {
			"items": max_posts,
			"query": items,
			"board": query.get("search_scope"),  # used in web interface
			"search_scope": query.get("search_scope")
		}