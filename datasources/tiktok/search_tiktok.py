"""
Search TikTok via web scraping

TikTok is, after a fashion, an imageboard - people post videos and then
other people reply. So this datasource uses this affordance to retrieve
TikTok data for 4CAT.
"""
import urllib.parse
import time
import re

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import NoSuchElementException, JavascriptException

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

		posts = []
		for query in queries:
			posts += self.fetch_from_overview_page(query, max_posts)

		raise RuntimeError()
		return posts



	def fetch_from_overview_page(self, item, limit=10):
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
		options = Options()
		options.headless = True
		options.add_argument("--user-agent=%s" % "Naverbot")
		options.add_argument("--disable-gpu")

		browser = webdriver.Chrome(options=options)
		browser.set_page_load_timeout(10)
		browser.set_script_timeout(5)
		browser.implicitly_wait(2)

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

		self.stealthify_browser(browser)
		browser.get(url)
		self.stealthify_browser(browser)

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
			time.sleep(1)
			page_height = browser.execute_script("return document.body.scrollHeight")
			browser.execute_script("window.scrollTo(0,document.body.scrollHeight)")

			start_time = time.time()
			have_new_content = False
			while time.time() - 5 < start_time:
				# a somewhat generous timeout here as as you scroll down on the
				# page it takes longer and longer to load the new posts
				scroll_height = browser.execute_script("return document.body.scrollHeight")
				if scroll_height > page_height + 100:
					page_height = scroll_height
					have_new_content = True
					break
				time.sleep(0.25)

			# the amount of videos on the page:
			items = int(browser.execute_script("return document.querySelectorAll('a.video-feed-item-wrapper').length"))
			if not have_new_content or int(items) >= limit:
				break


		if items == 0:
			return []

		# next determine what selector we need to use to find the modal window
		# containing the actual tiktok post. this seems to differ from time to
		# time (possibly resolution-related?) so we try a list until we find
		# one that works
		browser.execute_script("document.querySelector('a.video-feed-item-wrapper').click()")
		selectors = [".video-card-big.browse-mode", ".video-card-modal"]
		have_selector = False

		while selectors:
			selector = selectors[0]
			selectors = selectors[1:]

			have_selector = False
			try:
				browser.find_element_by_css_selector("%s .user-info" % selector)
				have_selector = True
				break
			except (JavascriptException, NoSuchElementException):
				continue

		# if at this point we still don't have a selector it means that we
		# don't know how to find the post info in the page, so we can't scrape
		if not have_selector:
			self.dataset.update_status("Could not load post data. Scraping not possible.", is_final=True)
			browser.close()
			return []

		result = []
		while len(result) < limit:
			if self.interrupted:
				browser.close()
				raise ProcessorInterruptedException("Interrupted while downloading post data")

			# wait until the post info has been loaded asynchronously
			try:
				browser.find_element_by_css_selector("%s .user-info" % selector)
			except NoSuchElementException:
				continue

			# annoyingly the post URL does not seem to be loaded into the modal
			# but we can use the share buttons (that include the post URL in
			# their share URL) to infer it
			href = browser.execute_script("return document.querySelector('%s .share-group a').getAttribute('href')" % selector)
			href = href.split("&u=")[1].split("&")[0]
			href = urllib.parse.unquote(href)
			bits = href.split("/")

			# now extract the data from the various page elements containing
			# them
			data = {}
			try:
				data["id"] = bits[-1]
				data["thread_id"] = bits[-1]
				data["author"] = browser.execute_script(
					"return document.querySelector('%s .user-info .user-username').innerHTML" % selector)
				data["author_full"] = browser.execute_script(
					"return document.querySelector('%s .user-info .user-nickname').innerHTML" % selector)
				data["subject"] = ""
				data["body"] = browser.execute_script(
					"return document.querySelector('%s .video-meta-title').innerHTML" % selector)
				data["timestamp"] = 0
				data["has_harm_warning"] = bool(
					browser.execute_script("return document.querySelectorAll('%s .warn-info').length > 0" % selector))
				data["music_name"] = browser.execute_script(
					"return document.querySelector('%s .music-info a').innerHTML" % selector)
				data["music_url"] = browser.execute_script(
					"return document.querySelector('%s .music-info a').getAttribute('href')" % selector)
				data["video_url"] = browser.execute_script(
					"return document.querySelector('%s video').getAttribute('src')" % selector)
				data["tiktok_url"] = href

				# these are a bit more involved
				data["likes"] = expand_short_number(
					browser.execute_script("return document.querySelector('%s .like-text').innerHTML" % selector))
				data["comments"] = expand_short_number(
					browser.execute_script("return document.querySelector('%s .comment-text').innerHTML" % selector))

				# we strip the HTML here because TikTok does not allow user markup
				# anyway, so this is not really significant
				data["hashtags"] = ",".join(
					[tag.replace("?", "") for tag in re.findall(r'href="/tag/([^"]+)"', data["body"])])
				body_soup = BeautifulSoup(data["body"], "html.parser")
				data["body"] = body_soup.text.strip()
			except Exception as e:
				self.log.warning("Skipping post %s for TikTok scrape (%s)" % (href, e))
				break


			# store data and - if possible - click the "next post" button to
			# load the next one. If the button does not exist, no more posts
			# can be loaded, so end the scrape
			result.append(data)
			if len(result) % 10 == 0:
				self.dataset.update_status("Scraped data for %i/%i posts..." % (len(result), min(items, limit)))

			try:
				has_next = browser.find_element_by_css_selector("%s .control-icon.arrow-right" % selector)
				browser.execute_script("document.querySelector('%s .control-icon.arrow-right').click()" % selector)
				time.sleep(0.8)
			except NoSuchElementException:
				break

		browser.close()
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

	def stealthify_browser(self, browser):
		"""
		Stealth scripts to hide that we're headless

		From https://github.com/MeiK2333/pyppeteer_stealth

		:param browser:  Selenium browser to stealthify
		"""
		browser.execute_script("""
() => {
    window.chrome = {
        runtime: {}
    }
};

() => {
    window.console.debug = () => {
        return null
    }
};

() => {
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-US', 'en']
    })
};

() => {
    const originalQuery = window.navigator.permissions.query

    window.navigator.permissions.__proto__.query = parameters =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters)


    const oldCall = Function.prototype.call
    function call () {
        return oldCall.apply(this, arguments)
    }

    Function.prototype.call = call

    const nativeToStringFunctionString = Error.toString().replace(
        /Error/g,
        'toString'
    )
    const oldToString = Function.prototype.toString

    function functionToString () {
        if (this === window.navigator.permissions.query) {
            return 'function query() { [native code] }'
        }
        if (this === functionToString) {
            return nativeToStringFunctionString
        }
        return oldCall.call(oldToString, this)
    }

    Function.prototype.toString = functionToString
};

() => {
    function mockPluginsAndMimeTypes() {
        const makeFnsNative = (fns = []) => {
            const oldCall = Function.prototype.call
            function call() {
                return oldCall.apply(this, arguments)
            }

            Function.prototype.call = call

            const nativeToStringFunctionString = Error.toString().replace(
                /Error/g,
                'toString'
            )
            const oldToString = Function.prototype.toString

            function functionToString() {
                for (const fn of fns) {
                    if (this === fn.ref) {
                        return `function ${fn.name}() { [native code] }`
                    }
                }

                if (this === functionToString) {
                    return nativeToStringFunctionString
                }
                return oldCall.call(oldToString, this)
            }

            Function.prototype.toString = functionToString
        }

        const mockedFns = []

        const fakeData = {
            mimeTypes: [
                {
                    type: 'application/pdf',
                    suffixes: 'pdf',
                    description: '',
                    __pluginName: 'Chrome PDF Viewer'
                },
                {
                    type: 'application/x-google-chrome-pdf',
                    suffixes: 'pdf',
                    description: 'Portable Document Format',
                    __pluginName: 'Chrome PDF Plugin'
                },
                {
                    type: 'application/x-nacl',
                    suffixes: '',
                    description: 'Native Client Executable',
                    enabledPlugin: Plugin,
                    __pluginName: 'Native Client'
                },
                {
                    type: 'application/x-pnacl',
                    suffixes: '',
                    description: 'Portable Native Client Executable',
                    __pluginName: 'Native Client'
                }
            ],
            plugins: [
                {
                    name: 'Chrome PDF Plugin',
                    filename: 'internal-pdf-viewer',
                    description: 'Portable Document Format'
                },
                {
                    name: 'Chrome PDF Viewer',
                    filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai',
                    description: ''
                },
                {
                    name: 'Native Client',
                    filename: 'internal-nacl-plugin',
                    description: ''
                }
            ],
            fns: {
                namedItem: instanceName => {
                    const fn = function (name) {
                        if (!arguments.length) {
                            throw new TypeError(
                                `Failed to execute 'namedItem' on '${instanceName}': 1 argument required, but only 0 present.`
                            )
                        }
                        return this[name] || null
                    }
                    mockedFns.push({ ref: fn, name: 'namedItem' })
                    return fn
                },
                item: instanceName => {
                    const fn = function (index) {
                        if (!arguments.length) {
                            throw new TypeError(
                                `Failed to execute 'namedItem' on '${instanceName}': 1 argument required, but only 0 present.`
                            )
                        }
                        return this[index] || null
                    }
                    mockedFns.push({ ref: fn, name: 'item' })
                    return fn
                },
                refresh: instanceName => {
                    const fn = function () {
                        return undefined
                    }
                    mockedFns.push({ ref: fn, name: 'refresh' })
                    return fn
                }
            }
        }

        const getSubset = (keys, obj) =>
            keys.reduce((a, c) => ({ ...a, [c]: obj[c] }), {})

        function generateMimeTypeArray() {
            const arr = fakeData.mimeTypes
                .map(obj => getSubset(['type', 'suffixes', 'description'], obj))
                .map(obj => Object.setPrototypeOf(obj, MimeType.prototype))
            arr.forEach(obj => {
                arr[obj.type] = obj
            })

            arr.namedItem = fakeData.fns.namedItem('MimeTypeArray')
            arr.item = fakeData.fns.item('MimeTypeArray')

            return Object.setPrototypeOf(arr, MimeTypeArray.prototype)
        }

        const mimeTypeArray = generateMimeTypeArray()
        Object.defineProperty(navigator, 'mimeTypes', {
            get: () => mimeTypeArray
        })

        function generatePluginArray() {
            const arr = fakeData.plugins
                .map(obj => getSubset(['name', 'filename', 'description'], obj))
                .map(obj => {
                    const mimes = fakeData.mimeTypes.filter(
                        m => m.__pluginName === obj.name
                    )

                    mimes.forEach((mime, index) => {
                        navigator.mimeTypes[mime.type].enabledPlugin = obj
                        obj[mime.type] = navigator.mimeTypes[mime.type]
                        obj[index] = navigator.mimeTypes[mime.type]
                    })
                    obj.length = mimes.length
                    return obj
                })
                .map(obj => {
                    obj.namedItem = fakeData.fns.namedItem('Plugin')
                    obj.item = fakeData.fns.item('Plugin')
                    return obj
                })
                .map(obj => Object.setPrototypeOf(obj, Plugin.prototype))
            arr.forEach(obj => {
                arr[obj.name] = obj
            })

            arr.namedItem = fakeData.fns.namedItem('PluginArray')
            arr.item = fakeData.fns.item('PluginArray')
            arr.refresh = fakeData.fns.refresh('PluginArray')

            return Object.setPrototypeOf(arr, PluginArray.prototype)
        }

        const pluginArray = generatePluginArray()
        Object.defineProperty(navigator, 'plugins', {
            get: () => pluginArray
        })


        makeFnsNative(mockedFns)
    }
    try {
        const isPluginArray = navigator.plugins instanceof PluginArray
        const hasPlugins = isPluginArray && navigator.plugins.length > 0
        if (isPluginArray && hasPlugins) {
            return
        }
        mockPluginsAndMimeTypes()
    } catch (err) { }
};

() => {
    const newProto = navigator.__proto__
    delete newProto.webdriver
    navigator.__proto__ = newProto
};

() => {
    try {
        const getParameter = WebGLRenderingContext.getParameter
        WebGLRenderingContext.prototype.getParameter = function (parameter) {
            if (parameter === 37445) {
                return 'Intel Inc.'
            }
            if (parameter === 37446) {
                return 'Intel Iris OpenGL Engine'
            }
            return getParameter(parameter)
        }
    } catch (err) { }
};

() => {
    try {
        if (window.outerWidth && window.outerHeight) {
            return
        }
        const windowFrame = 85
        window.outerWidth = window.innerWidth
        window.outerHeight = window.innerHeight + windowFrame
    } catch (err) { }
};		
		""")

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