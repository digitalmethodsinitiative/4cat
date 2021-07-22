"""
Search Telegram via API
"""
import traceback
import hashlib
import asyncio
import json
import time
import re

from pathlib import Path

from backend.abstract.search import Search
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException
from common.lib.helpers import convert_to_int, UserInput

from telethon import TelegramClient
from telethon.errors.rpcerrorlist import UsernameInvalidError, BadRequestError, TimeoutError
from telethon.tl.types import User, PeerChannel, PeerChat, PeerUser

import config


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

    options = {
        "intro": {
            "type": UserInput.OPTION_INFO,
            "help": "Messages are scraped in reverse chronological order: the most recent message for a given entity "
                    "(e.g. a group) will be scraped first.\n\nTo query the Telegram API, you need to supply your [API "
                    "credentials](https://my.telegram.org/apps). These **will be sent to the 4CAT server** and will be "
                    "stored there while data is fetched. After the dataset has been created your credentials will be "
                    "deleted from the server. 4CAT at this time does not support two-factor authentication for "
                    "Telegram."
        },
        "api_id": {
            "type": UserInput.OPTION_TEXT,
            "help": "API ID",
            "sensitive": True,
            "cache": True,
        },
        "api_hash": {
            "type": UserInput.OPTION_TEXT,
            "help": "API Hash",
            "sensitive": True,
            "cache": True,
        },
        "api_phone": {
            "type": UserInput.OPTION_TEXT,
            "help": "Phone number",
            "sensitive": True,
            "cache": True,
            "default": "+xxxxxxxxxx"
        },
        "security-code": {
            "type": UserInput.OPTION_TEXT,
            "help": "Security code",
            "sensitive": True
        },
        "divider": {
            "type": UserInput.OPTION_DIVIDER
        },
        "query-intro": {
            "type": UserInput.OPTION_INFO,
            "help": "You can scrape up to **25** items at a time. Separate the items with commas or line breaks."
        },
        "query": {
            "type": UserInput.OPTION_TEXT_LARGE,
            "help": "Entities to scrape",
            "tooltip": "Separate with commas or line breaks."
        },
        "max_posts": {
            "type": UserInput.OPTION_TEXT,
            "help": "Messages per group",
            "min": 1,
            "max": 50000,
            "default": 10
        }
    }

    def get_items(self, query):
        """
        Execute a query; get messages for given parameters

        Basically a wrapper around execute_queries() to call it with asyncio.

        :param dict query:  Query parameters, as part of the DataSet object
        :return list:  Posts, sorted by thread and post ID, in ascending order
        """
        if "api_phone" not in query or "api_hash" not in query or "api_id" not in query:
            self.dataset.update_status("Could not create dataset since the Telegram API Hash and ID are missing. Try "
                                       "creating it again from scratch.", is_final=True)
            return None

        results = asyncio.run(self.execute_queries())
        return results

    async def execute_queries(self):
        """
        Get messages for queries

        This is basically what would be done in get_items(), except due to
        Telethon's architecture this needs to be called in an async method,
        which is this one.
        """
        # session file has been created earlier, and we can re-use it here in
        # order to avoid having to re-enter the security code
        query = self.parameters

        hash_base = query["api_phone"].replace("+", "") + query["api_id"] + query["api_hash"]
        session_id = hashlib.blake2b(hash_base.encode("ascii")).hexdigest()
        session_path = Path(config.PATH_ROOT).joinpath(config.PATH_SESSIONS, session_id + ".session")

        client = None

        def cancel_start():
            """
            Replace interactive phone number input in Telethon

            By default, if Telethon cannot use the given session file to
            authenticate, it will interactively prompt the user for a phone
            number on the command line. That is not useful here, so instead
            raise a RuntimeError. This will be caught below and the user will
            be told they need to re-authenticate via 4CAT.
            """
            raise RuntimeError("Connection cancelled")

        try:
            client = TelegramClient(str(session_path), int(query.get("api_id")), query.get("api_hash"),
                                    loop=self.eventloop)
            await client.start(phone=cancel_start)
        except RuntimeError:
            # session is no longer useable, delete file so user will be asked
            # for security code again
            self.dataset.update_status(
                "Session is not authenticated: login security code may have expired. You need to re-enter the security code.",
                is_final=True)
            session_path.unlink(missing_ok=True)
            if client and hasattr(client, "disconnect"):
                await client.disconnect()
            return None
        except Exception as e:
            self.dataset.update_status("Error connecting to the Telegram API with provided credentials.", is_final=True)
            if client and hasattr(client, "disconnect"):
                await client.disconnect()
            return None

        # ready our parameters
        parameters = self.dataset.get_parameters()
        queries = [query.strip() for query in parameters.get("query", "").split(",")]
        max_items = convert_to_int(parameters.get("items", 10), 10)

        try:
            posts = await self.gather_posts(client, queries, max_items)
        except Exception as e:
            self.dataset.update_status("Error scraping posts from Telegram")
            self.log.error("Telegram scraping error: %s" % traceback.format_exc())
            posts = None
        finally:
            await client.disconnect()

        return posts

    async def gather_posts(self, client, queries, max_items):
        """
        Gather messages for each entity for which messages are requested

        :param TelegramClient client:  Telegram Client
        :param list queries:  List of entities to query (as string)
        :param int max_items:  Messages to scrape per entity
        :return list:  List of messages, each message a dictionary.
        """
        posts = []

        for query in queries:
            delay = 10
            retries = 0

            while True:
                self.dataset.update_status("Fetching messages for entity '%s'" % query)
                query_posts = []
                i = 0
                try:
                    async for message in client.iter_messages(entity=query):
                        if self.interrupted:
                            raise ProcessorInterruptedException(
                                "Interrupted while fetching message data from the Telegram API")

                        if i % 500 == 0:
                            self.dataset.update_status(
                                "Retrieved %i posts for entity '%s'" % (len(query_posts) + len(posts), query))

                        if message.action is not None:
                            # e.g. someone joins the channel - not an actual message
                            continue

                        parsed_message = self.import_message(message, query)
                        query_posts.append(parsed_message)

                        i += 1
                        if i > max_items:
                            break
                except (ValueError, UsernameInvalidError) as e:
                    self.dataset.update_status("Could not scrape entity '%s'" % query)

                except TimeoutError:
                    if retries < 3:
                        self.dataset.update_status(
                            "Tried to fetch messages for entity '%s' but timed out %i times. Skipping." % (
                            query, retries))
                        break

                    self.dataset.update_status(
                        "Got a timeout from Telegram while fetching messages for entity '%s'. Trying again in %i seconds." % (
                        query, delay))
                    time.sleep(delay)
                    delay *= 2
                    continue

                posts += list(reversed(query_posts))
                break

        return posts

    def import_message(self, message, entity):
        """
        Convert Message object to 4CAT-ready data object

        :param Message message:  Message to parse
        :param str entity:  Entity this message was imported from
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
        fullname = ""
        if hasattr(message, "sender") and hasattr(message.sender, "username"):
            username = message.sender.username if message.sender.username else ""
            fullname = message.sender.first_name if hasattr(message.sender,
                                                            "first_name") and message.sender.first_name else ""
            if hasattr(message.sender, "last_name") and message.sender.last_name:
                fullname += " " + message.sender.last_name
            user_id = message.sender.id
            user_is_bot = message.sender.bot if hasattr(message.sender, "bot") else False
        elif message.from_id:
            user_id = message.from_id
            username = None
            user_is_bot = None
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
            attachment_data = json.dumps({property: getattr(attachment, property) for property in
                                          ("phone_number", "first_name", "last_name", "vcard", "user_id")})

        elif attachment_type == "document":
            # videos, etc
            # This could add a separate routine for videos to make them a
            # separate type, which could then be scraped later, etc
            attachment_type = message.media.document.mime_type.split("/")[0]
            if attachment_type == "video":
                attachment = message.document
                attachment_data = json.dumps({
                    "id": attachment.id,
                    "dc_id": attachment.dc_id,
                    "file_reference": attachment.file_reference.hex(),
                })
            else:
                attachment_data = ""

        elif attachment_type in ("geo", "geo_live"):
            # untested whether geo_live is significantly different from geo
            attachment_data = "%s %s" % (message.geo.lat, message.geo.long)

        elif attachment_type == "photo":
            # we don't actually store any metadata about the photo, since very
            # little of the metadata attached is of interest. Instead, the
            # actual photos may be downloaded via a processor that is run on the
            # search results
            attachment = message.photo
            attachment_data = json.dumps({
                "id": attachment.id,
                "dc_id": attachment.dc_id,
                "file_reference": attachment.file_reference.hex(),
            })

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
            "author_username": username,
            "author_name": fullname,
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

        # if not get_full_userinfo:
        #	del msg["author_name"]
        #	del msg["author_is_bot"]

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

    def validate_query(query, request, user):
        """
        Validate Telegram query

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param User user:  User object of user who has submitted the query
        :return dict:  Safe query parameters
        """
        # no query 4 u
        if not query.get("query", "").strip():
            raise QueryParametersException("You must provide a search query.")

        if not query.get("api_id", None) or not query.get("api_hash", None) or not query.get("api_phone", None):
            raise QueryParametersException("You need to provide valid Telegram API credentials first.")

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
            "items": query.get("max_posts"),
            "query": items,
            "board": "",  # needed for web interface
            "api_id": query.get("api_id"),
            "api_hash": query.get("api_hash"),
            "api_phone": query.get("api_phone")
        }

    @classmethod
    def get_options(cls=None, parent_dataset=None, user=None):
        """
        Get processor options

        This method by default returns the class's "options" attribute, but
        will lift the limit on the amount of messages scraped per group if the
        user requesting the options has been configured as such.

        :param DataSet parent_dataset:  An object representing the dataset that
        the processor would be run on
        :param User user:  Flask user the options will be displayed for, in
        case they are requested for display in the 4CAT web interface. This can
        be used to show some options only to privileges users.
        """
        options = cls.options.copy()

        if user and user.get_value("telegram.can_query_all_messages", False) and "max" in options["max_posts"]:
            del options["max_posts"]["max"]

        return options
