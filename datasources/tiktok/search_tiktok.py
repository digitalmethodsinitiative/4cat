"""
Search TikTok via web scraping

TikTok is, after a fashion, an imageboard - people post videos and then
other people reply. So this datasource uses this affordance to retrieve
TikTok data for 4CAT.
"""
import requests
import time
import json
import re

from seleniumwire import webdriver
from selenium.webdriver.chrome.options import Options
#from selenium.webdriver.firefox.options import Options
from selenium.common.exceptions import JavascriptException

from backend.abstract.search import Search
from common.lib.helpers import UserInput
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException


class SearchTikTok(Search):
	"""
	TikTok scraper

	Since TikTok has no API of its own, we use selenium to start a headless
	browser that we manipulate to browse the TikTok website and download the
	information we need. Unfortunately this is a bit limited - we can't
	download comments for example, though we could potentially if we log in
	(but logging in is complicated in itself).

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

	options = {
		"intro": {
			"type": UserInput.OPTION_INFO,
			"help": "Note that TikTok is a predominantly video-based platform, and videos cannot currently be "
					"downloaded via 4CAT. As such 4CAT will be of limited use processing and analysing the data; "
					"nevertheless you can use this scraper to get a quick list of URLs and metadata for posts for a "
					"given username or hashtag. The dataset will contain links to all videos scraped.\n\nPosts are "
					"scraped in reverse chronological order; the most recent post for a given query will be scraped "
					"first. Unfortunately comments cannot be scraped at this time."
		},
		"search_scope": {
			"type": UserInput.OPTION_CHOICE,
			"options": {
				"hashtag": "Hashtag",
				"username": "Username",
				"music": "Music"
			},
			"help": "Search by"
		},
		"syntax-intro": {
			"type": UserInput.OPTION_INFO,
			"help": "You can scrape up to **five** items at a time. Separate the items with commas or blank lines. "
					"Including `#` in hashtags is optional. For *music* queries, insert the music URL or ID (e.g. "
					"https://www.tiktok.com/music/`sonido-original-6815021149295069958`)"
		},
		"query": {
			"type": UserInput.OPTION_TEXT_LARGE,
			"help": "Items to scrape",
			"tooltip": "Separate with commas or new lines."
		},
		"max_posts": {
			"type": UserInput.OPTION_TEXT,
			"help": "Posts per item",
			"min": 1,
			"max": 100
		}
	}

	def get_items(self, parameters):
		"""
		Run custom search

		Fetches data from TikTok

		:return list:  List of dictionaries, one per scraped post
		"""
		max_posts = self.dataset.parameters.get("items", 10)
		queries = self.dataset.parameters.get("query").split(",")

		posts = []
		for query in queries:
			posts += self.fetch_from_overview_page_with_api(query, max_posts)

		if posts:
			self.dataset.update_status("Scraped %i posts." % len(posts))

		return posts

	def fetch_from_overview_page_with_api(self, item, limit=10):
		# first, open a browser to sign requests with
		iphone_ua = "Naverbot" #Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.1 Safari/605.1.15"

		options = Options()
		options.headless = True
		options.add_argument("--user-agent=%s" % iphone_ua)
		options.add_argument("--disable-gpu")
		options.add_argument("--disable-infobars")
		options.add_argument("--window-position=0,0")
		options.add_argument("--ignore-certificate-errors")
		options.add_argument("--ignore-certificate-errors-spki-list")

		# not clear if this actually has any benefit
		#mobile_emulation = {"deviceName": "iPhone X"}
		#chrome_options = webdriver.ChromeOptions()
		#chrome_options.add_experimental_option("mobileEmulation", mobile_emulation)

		self.dataset.update_status("Initialising scraper")
		browser = webdriver.Chrome(options=options) #, desired_capabilities=chrome_options.to_capabilities())

		browser.set_page_load_timeout(15)
		browser.set_script_timeout(10)
		browser.implicitly_wait(5)
		# capture only requests to tiktok's own API
		browser.scopes = [".*" + re.escape("tiktok.com") + ".*"]

		result = []
		type = ""
		if item[0] == "#":
			# hashtag query
			base_url = "https://www.tiktok.com/tag/%s" % item[1:]
			item_type = 3
		elif item[0] == "@":
			# user query
			base_url = "https://www.tiktok.com/%s" % item
			item_type = 1
		else:
			# music
			music_id = item.split("?")[0].split("-")[-1]
			base_url = "https://www.tiktok.com/music/original-sound-%s" % music_id
			item_type = 4

		self.stealthify_browser(browser)
		browser.get(base_url)
		self.stealthify_browser(browser)

		# we need the item ID to send API requests - this is a number that is
		# unique to each hashtag, music, or user. It's included in the page
		# loaded, as a meta property. However, presumably due to some
		# javascript shenanigans we can't get it via querySelector - the
		# element is opaque to it. So we extract it from the 'raw' HTML of the
		# request with a regex.
		time.sleep(1)
		page_request = browser.wait_for_request(base_url)
		item_iri = re.findall(r'<meta\s+property="al:ios:url"\s+content="([^"]+)"\s*/>', page_request.response.body.decode("utf-8"))
		item_id = item_iri[0].split("/")[-1].split("?")[0]
		browser.get("https://www.tiktok.com/discover")

		# API requests need to be 'signed', and this is done via some
		# complicated mechanism we don't need to figure out because it is a
		# javascript function we can simply call through the selenium instance
		# thanks to: https://github.com/carcabot/tiktok-signature/
		try:
			web_id = browser.execute_script("return document.cookie.split(';').filter((a) => a.split('=')[0].trim() == 's_v_web_id')[0].split('=')[1];")
		except JavascriptException:
			web_id = None

		have_signing_function = browser.execute_script("return typeof(window.byted_acrawler.sign) === 'function'")
		if not have_signing_function:
			browser.close()
			self.dataset.update_status("Could not initiate API scrape. No data scraped.", is_final=True)
			return []

		# this is a wrapper method that signs and calls any TikTok API request
		def get_signed(url, verifyFp=None):
			if verifyFp:
				url += "&verifyFp=" + verifyFp

			api_signature = browser.execute_script("return window.byted_acrawler.sign({url:'%s'});" % url)
			url += "&_signature=%s" % api_signature

			api_headers={
				"Method": "GET",
				"Accept-encoding": "gzip, deflate, br",
				"Referer": base_url,
				"User-Agent": iphone_ua
			}
			response = requests.get(url, headers=api_headers)

			return response.json()

		# now we have everything we need to make API calls - start the actual
		# scraping
		offset = 0
		while len(result) < limit:
			self.dataset.update_status("Scraped %i/%i posts for query '%s'" % (len(result), limit, item))
			api_url = "https://m.tiktok.com/share/item/list?secUid=&id=%s&type=%i&count=30&minCursor=0&maxCursor=%i&shareUid=&lang=&verifyFp=" % (item_id, item_type, offset)
			api_call = get_signed(api_url, web_id)

			for post_data in api_call["body"]["itemListData"]:
				post = post_data["itemInfos"]
				user = post_data["authorInfos"]
				user_stats = post_data["authorStats"]
				music = post_data["musicInfos"]
				hashtags = [item["HashtagName"] for item in post_data["textExtra"] if item["HashtagName"]]

				post_entry = {
					"id": post["id"],
					"thread_id": post["id"],
					"author": user["uniqueId"],
					"author_full": user["nickName"],
					"author_followers": user_stats["followerCount"],
					"subject": "",
					"body": post["text"],
					"timestamp": int(post["createTime"]),
					"is_harmful": len(post["warnInfo"]) > 0,
					"is_duet": post_data["duetInfo"] != "0",
					"music_name": music["musicName"],
					"music_id": music["musicId"],
					"video_url": post["video"]["urls"][0],
					"tiktok_url": "https://tiktok.com/@%s/video/%s" % (user["uniqueId"], post["id"]),
					"thumbnail_url": post["covers"][0],
					"amount_likes": post["diggCount"],
					"amount_comments": post["commentCount"],
					"amount_shares": post["shareCount"],
					"amount_plays": post["playCount"],
					"hashtags": ",".join(hashtags),
				}

				result.append(post_entry)

			if not api_call["body"]["hasMore"]:
				break

			offset += 30
			time.sleep(1.5)

		browser.close()
		return result

	def fetch_from_overview_page_with_selenium(self, item, limit=10):
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

		# Naverbot seems to get a free pass while other UAs will make the
		# website not load any data
		scraper_ua = "Naverbot"
		iphone_ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 13_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.5 Mobile/15E148 Safari/604.1"

		options = Options()
		options.headless = False
		options.add_argument("--user-agent=%s" % scraper_ua)
		options.add_argument("--disable-gpu")

		# not clear if this actually has any benefit
		mobile_emulation = {"deviceName": "iPhone X"}
		chrome_options = webdriver.ChromeOptions()
		chrome_options.add_experimental_option("mobileEmulation", mobile_emulation)

		browser = webdriver.Chrome(options=options, desired_capabilities=chrome_options.to_capabilities())

		# capture only requests to tiktok's own API
		browser.scopes = [
			".*" + re.escape("m.tiktok.com/share/item/list") + ".*"
		]
		browser.set_page_load_timeout(15)
		browser.set_script_timeout(10)
		browser.implicitly_wait(5)

		if len(item) < 2:
			# empty query... should have been discarded though
			return []

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

		browser.get(url)
		self.stealthify_browser(browser)
		time.sleep(1.5)

		items = 0
		while True:
			# TikTok's overview page is one of those infinite scroll affairs,
			# so we scroll down until we have enough posts to then scrape
			# individually
			self.dataset.update_status("Finding posts for '%s' (%i so far)" % (item, items))
			if self.interrupted:
				browser.close()
				raise ProcessorInterruptedException("Interrupted while fetching post list from TikTok")

			# we can determine whether the new items after scrolling have
			# loaded through the page height. We give 100 pixels leeway
			# since the loading indicator itself takes up some space and we
			# don't want to interpret its appearance as the document actually
			# having scrolled properly
			time.sleep(1)
			page_height = browser.execute_script("return document.body.scrollHeight")
			browser.execute_script("window.scrollTo(0,document.body.scrollHeight)")
			time.sleep(1)

			start_time = time.time()
			have_new_content = False
			while time.time() - 5 < start_time:
				# a somewhat generous timeout here as as you scroll down on the
				# page it takes longer and longer to load the new posts
				scroll_height = browser.execute_script("return document.body.scrollHeight")
				if scroll_height > page_height + 100:
					have_new_content = True
					break
				time.sleep(0.25)

			# the amount of posts on the page:
			items = int(browser.execute_script("return document.querySelectorAll('a.video-feed-item-wrapper').length"))
			if not have_new_content or int(items) >= limit:
				break

		result = []
		for update in browser.requests:
			try:
				data = json.loads(update.response.body)
			except json.JSONDecodeError:
				self.log.warning("Error decoding TikTok response for %s" % update)
				continue

			if "body" not in data or "statusCode" not in data:
				self.log.info("Trying to parse TikTok API request %s, but unknown format" % update)
				continue

			if data["statusCode"] != 0:
				continue

			items = data["body"]["itemListData"]
			for post_data in items:
				if len(result) >= limit:
					break

				post = post_data["itemInfos"]
				user = post_data["authorInfos"]
				user_stats = post_data["authorStats"]
				music = post_data["musicInfos"]
				hashtags = [item["HashtagName"] for item in post_data["textExtra"] if item["HashtagName"]]

				post_entry = {
					"id": post["id"],
					"thread_id": post["id"],
					"author": user["uniqueId"],
					"author_full": user["nickName"],
					"author_followers": user_stats["followerCount"],
					"subject": "",
					"body": post["text"],
					"timestamp": int(post["createTime"]),
					"is_harmful": len(post["warnInfo"]) > 0,
					"is_duet": post_data["duetInfo"] != "0",
					"music_name": music["musicName"],
					"music_id": music["musicId"],
					"video_url": post["video"]["urls"][0],
					"tiktok_url": "https://tiktok.com/@%s/video/%s" % (user["uniqueId"], post["id"]),
					"thumbnail_url": post["covers"][0],
					"amount_likes": post["diggCount"],
					"amount_comments": post["commentCount"],
					"amount_shares": post["shareCount"],
					"amount_plays": post["playCount"],
					"hashtags": ",".join(hashtags),
				}

				result.append(post_entry)

			if len(result) >= limit:
				break

		browser.close()

		if not result:
			self.dataset.update_status("No posts could be scraped for '%s'." % item)

		return result[:limit]

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
		# no query 4 u
		if not query.get("query", "").strip():
			raise QueryParametersException("You must provide a search query.")

		# reformat queries to be a comma-separated list with no wrapping
		# whitespace
		whitespace = re.compile(r"[@#\s]+")
		items = whitespace.sub("", query.get("query").replace("\n", ",")).split(",")

		if len(items) > 5:
			raise QueryParametersException("You cannot query more than 5 items at a time.")

		sigil = {"hashtag": "#", "username": "@", "music": "🎶"}[query.get("search_scope")]
		items = ",".join([sigil + item for item in items if item])

		# simple!
		return {
			"items": query.get("max_posts"),
			"query": items,
			"board": query.get("search_scope"),  # used in web interface
			"search_scope": query.get("search_scope")
		}