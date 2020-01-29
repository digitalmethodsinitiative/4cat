"""
Search Telegram via API
"""
import traceback
import asyncio
import json
import re

from pathlib import Path

from backend.abstract.search import Search
from backend.lib.exceptions import QueryParametersException, ProcessorInterruptedException
from backend.lib.helpers import convert_to_int

from telethon.sync import TelegramClient
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import User, Message, PeerChannel, PeerChat, PeerUser


class SearchTelegram(Search):
	"""
	Search Telegram via API
	"""
	type = "telegram-search"  # job ID
	category = "Search"  # category
	title = "Telegram API search"  # title displayed in UI
	description = "Scrapes messages from open Telegram groups via its API."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	# not available as a processor for existing datasets
	accepts = [None]

	# cache
	eventloop = None
	usermap = {}
	botmap = {}

	max_workers = 1
	max_retries = 3

	def get_posts_simple(self, query):
		"""
		In the case of Telegram, there is no need for multiple pathways, so we
		can route it all to the one post query method.
		:param query:
		:return:
		"""
		return self.get_posts_complex(query)

	def get_posts_complex(self, query):
		"""
		Execute a query; get messages for given parameters

		:param dict query:  Query parameters, as part of the DataSet object
		:return list:  Posts, sorted by thread and post ID, in ascending order
		"""
		self.eventloop = asyncio.new_event_loop()
		session_path = Path(__file__).parent.joinpath("sessions", self.dataset.parameters.get("session"))
		client = TelegramClient(str(session_path), self.dataset.parameters.get("api_id"),
								self.dataset.parameters.get("api_hash"), loop=self.eventloop)

		try:
			client.start()
		except Exception as e:
			self.dataset.update_status("Error connecting to the Telegram API with provided credentials.")
			self.dataset.finish()
			client.disconnect()
			return None

		# ready our parameters
		parameters = self.dataset.get_parameters()
		queries = [query.strip() for query in parameters.get("query", "").split(",")]
		max_items = convert_to_int(parameters.get("items", 10), 10)

		# userinfo needs some work before it can be retrieved, something with
		# async method calls
		userinfo = False  # bool(parameters.get("scrape-userinfo", False))

		try:
			posts = self.gather_posts(client, queries, max_items, userinfo)
		except Exception as e:
			self.dataset.update_status("Error scraping posts from Telegram")
			self.log.error("Telegram scraping error: %s" % traceback.format_exc())
			posts = None
		finally:
			client.disconnect()

		# delete personal data from parameters. We still have a Telegram
		# session saved to disk, but it's useless without this information.
		self.dataset.delete_parameter("api_id")
		self.dataset.delete_parameter("api_hash")
		self.dataset.delete_parameter("api_phone")

		return posts

	def gather_posts(self, client, queries, max_items, userinfo):
		"""
		Gather messages for each entity for which messages are requested

		:param TelegramClient client:  Telegram Client
		:param list queries:  List of entities to query (as string)
		:param int max_items:  Messages to scrape per entity
		:param bool userinfo:  Whether to scrape detailed user information
		rather than just the ID
		:return list:  List of messages, each message a dictionary.
		"""
		posts = []
		for query in queries:
			query_posts = []
			i = 0
			try:
				for message in client.iter_messages(entity=query):
					if self.interrupted:
						raise ProcessorInterruptedException("Interrupted while fetching message data from the Telegram API")

					if i % 500 == 0:
						self.dataset.update_status("Retrieved %i posts for entity '%s'" % (len(query_posts) + len(posts), query))
					parsed_message = self.import_message(client, message, query, get_full_userinfo=userinfo)
					query_posts.append(parsed_message)

					i += 1
					if i > max_items:
						break
			except ValueError as e:
				self.dataset.update_status("Could not scrape entity '%s'" % query)

			posts += list(reversed(query_posts))

		return posts

	def import_message(self, client, message, entity, get_full_userinfo=False):
		"""
		Convert Message object to 4CAT-ready data object

		:param TelegramClient client:  Telethon TelegramClient instance
		:param Message message:  Message to parse
		:param bool get_full_userinfo:  Whether to get user info for users. Takes an extra request, so it's slow.
		:return dict:  4CAT-compatible item object
		"""
		thread = message.to_id

		# determine thread ID (= entity ID)
		if type(thread) == PeerChannel:
			thread_id = thread.channel_id
		elif type(thread) == PeerChat:
			thread_id = thread.chat_id
		elif type(thread) == PeerUser:
			thread_id = thread.user_id
		else:
			thread_id = 0

		# determine username
		# API responses only include the user *ID*, not the username, and to
		# complicate things further not everyone is a user and not everyone
		# has a username. If no username is available, try the first and
		# last name someone has supplied
		if message.from_id and not get_full_userinfo:
			user_id = message.from_id
			username = None
			user_is_bot = None
		elif message.from_id:
			# this is broken
			if message.from_id not in self.usermap:
				user = User(message.from_id)
				full = client.loop.run_until_complete(GetFullUserRequest(message.from_id))
				if full.user.username:
					self.usermap[message.from_id] = full.user.username
				elif full.user.first_name:
					self.usermap[message.from_id] = full.user.first_name
					if full.user.last_name:
						self.usermap[message.from_id] += " " + full.user.last_name
				else:
					self.usermap[message.from_id] = None

				self.botmap[message.from_id] = full.user.bot

			user_id = message.from_id
			username = self.usermap[message.from_id]
			user_is_bot = self.botmap[message.from_id]
		elif message.post_author:
			user_id = message.post_author
			username = message.post_author
			user_is_bot = False
		else:
			user_id = "stream"
			username = None
			user_is_bot = False

		# determine media type
		# these store some extra information of the attachment in
		# attachment_data. Since the final result will be serialised as a csv
		# file, we can only store text content. As such some media data is
		# serialised as JSON.
		attachment_type = self.get_media_type(message.media)
		if attachment_type == "contact":
			attachment = message.contact
			attachment_data = json.dumps({property: attachment[property] for property in
										  ("phone_number", "first_name", "last_name", "vcard", "user_id")})

		elif attachment_type == "document":
			# videos, etc
			# This could add a separate routine for videos to make them a
			# separate type, which could then be scraped later, etc
			attachment_type = message.media.document.mime_type.split("/")[0]
			attachment_data = ""

		elif attachment_type == "game":
			# there is far more data in the API response for games but this
			# seems like a reasonable number of items to include
			attachment = message.game
			attachment_data = json.dumps(
				{property: attachment[property] for property in ("id", "short_name", "title", "description")})

		elif attachment_type in ("geo", "geo_live"):
			# untested whether geo_live is significantly different from geo
			attachment_data = "%s %s" % (message.geo.lat, message.geo.long)

		elif attachment_type == "invoice":
			# unclear when and where this would be used
			attachment = message.invoice
			attachment_data = json.dumps(
				{property: attachment[property] for property in ("title", "description", "currency", "total_amount")})

		elif attachment_type == "photo":
			# we don't actually store any metadata about the photo, since very
			# little of the metadata attached is of interest. Instead, the
			# actual photos may be downloaded via a processor that is run on the
			# search results
			attachment_data = ""

		elif attachment_type == "poll":
			# unfortunately poll results are only available when someone has
			# actually voted on the poll - that will usually not be the case,
			# so we store -1 as the vote count
			attachment = message.poll
			options = {option.option: option.text for option in attachment.poll.answers}
			attachment_data = json.dumps({
				"question": attachment.poll.question,
				"voters": attachment.results.total_voters,
				"answers": [{
					"answer": options[answer.option],
					"votes": answer.voters
				} for answer in attachment.results.results] if attachment.results.results else [{
					"answer": options[option],
					"votes": -1
				} for option in options]
			})

		elif attachment_type == "venue":
			# weird
			attachment = message.venue
			attachment_data = json.dumps({**{"geo": "%s %s" % (attachment.geo.lat, attachment.geo.long)}, **{
				{property: attachment[property] for property in
				 ("title", "address", "provider", "venue_id", "venue_type")}
			}})

		elif attachment_type == "url":
			# easy!
			if hasattr(message.web_preview, "url"):
				attachment_data = message.web_preview.url
			else:
				attachment_data = ""

		else:
			attachment_data = ""

		# was the message forwarded from somewhere and if so when?
		forwarded = None
		forwarded_timestamp = None
		if message.fwd_from:
			forwarded_timestamp = message.fwd_from.date.timestamp()

			if message.fwd_from.post_author:
				forwarded = message.fwd_from.post_author
			elif message.fwd_from.from_id:
				forwarded = message.fwd_from.from_id
			elif message.fwd_from.channel_id:
				forwarded = message.fwd_from.channel_id
			else:
				from_id = "stream"

		msg = {
			"id": message.id,
			"thread_id": thread_id,
			"search_entity": entity,
			"author": user_id,
			"author_name": username,
			"author_is_bot": user_is_bot,
			"author_forwarded_from": forwarded,
			"subject": "",
			"body": message.message,
			"reply_to": message.reply_to_msg_id,
			"views": message.views,
			"timestamp": int(message.date.timestamp()),
			"timestamp_edited": int(message.edit_date.timestamp()) if message.edit_date else None,
			"timestamp_forwarded_from": forwarded_timestamp,
			"grouped_id": message.grouped_id,
			"attachment_type": attachment_type,
			"attachment_data": attachment_data
		}

		if not get_full_userinfo:
			del msg["author_name"]
			del msg["author_is_bot"]

		return msg

	def get_media_type(self, media):
		"""
		Get media type for a Telegram attachment

		:param media:  Media object
		:return str:  Textual identifier of the media type
		"""
		try:
			return {
				"NoneType": "",
				"MessageMediaContact": "contact",
				"MessageMediaDocument": "document",
				"MessageMediaEmpty": "",
				"MessageMediaGame": "game",
				"MessageMediaGeo": "geo",
				"MessageMediaGeoLive": "geo_live",
				"MessageMediaInvoice": "invoice",
				"MessageMediaPhoto": "photo",
				"MessageMediaPoll": "poll",
				"MessageMediaUnsupported": "unsupported",
				"MessageMediaVenue": "venue",
				"MessageMediaWebPage": "url"
			}[type(media).__name__]
		except KeyError:
			return ""

	def validate_query(query, request):
		"""
		Validate Telegram query

		:param dict query:  Query parameters, from client-side.
		:param request:  Flask request
		:return dict:  Safe query parameters
		"""
		# no query 4 u
		if not query.get("query", "").strip():
			raise QueryParametersException("You must provide a search query.")

		if not query.get("session", "").strip():
			raise QueryParametersException("You need to authenticate with the Telegram API first.")

		if not query.get("api_id", None) or not query.get("api_hash", None):
			raise QueryParametersException("You need to provide valid Telegram API credentials first.")

		if "api_phone" in query:
			del query["api_phone"]

		# 5000 is mostly arbitrary - may need tweaking
		max_posts = 50000
		if query.get("max_posts", ""):
			try:
				max_posts = min(abs(int(query.get("max_posts"))), max_posts)
			except TypeError:
				raise QueryParametersException("Provide a valid number of messages to query.")

		# reformat queries to be a comma-separated list with no wrapping
		# whitespace
		whitespace = re.compile(r"\s+")
		items = whitespace.sub("", query.get("query").replace("\n", ","))
		if len(items.split(",")) > 25:
			raise QueryParametersException("You cannot query more than 25 items at a time.")

		# eliminate empty queries
		items = ",".join([item for item in items.split(",") if item])

		# simple!
		return {
			"items": max_posts,
			"query": items,
			"board": "",  # needed for web interface
			"scrape-userinfo": bool(query.get("scrape-userinfo", False)),
			"session": query.get("session"),
			"api_id": query.get("api_id"),
			"api_hash": query.get("api_hash")
		}

	def fetch_posts(self, post_ids, where=None, replacements=None):
		"""
		Not used by Telegram scraper
		"""
		pass

	def fetch_threads(self, thread_ids):
		"""
		Not used by Telegram scraper
		"""
		pass

	def get_thread_sizes(self, thread_ids, min_length):
		"""
		Not used by Telegram scraper
		"""
		pass
