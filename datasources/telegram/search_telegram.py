"""
Search Telegram via API
"""
import traceback
import binascii
import datetime
import hashlib
import asyncio
import json
import time
import re

from pathlib import Path

from backend.abstract.search import Search
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException
from common.lib.helpers import convert_to_int, UserInput

from datetime import datetime
from telethon import TelegramClient
from telethon.errors.rpcerrorlist import UsernameInvalidError, TimeoutError, ChannelPrivateError, BadRequestError, FloodWaitError
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import User

import config


class SearchTelegram(Search):
    """
    Search Telegram via API
    """
    type = "telegram-search"  # job ID
    category = "Search"  # category
    title = "Telegram API search"  # title displayed in UI
    description = "Scrapes messages from open Telegram groups via its API."  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    is_local = False    # Whether this datasource is locally scraped
    is_static = False   # Whether this datasource is still updated

    # cache
    details_cache = None
    failures_cache = None
    eventloop = None
    flawless = True
    end_if_rate_limited = 600 # break if Telegram requires wait time above number of seconds

    max_workers = 1
    max_retries = 3

    options = {
        "intro": {
            "type": UserInput.OPTION_INFO,
            "help": "Messages are scraped in reverse chronological order: the most recent message for a given entity "
                    "(e.g. a group) will be scraped first.\n\nTo query the Telegram API, you need to supply your [API "
                    "credentials](https://my.telegram.org/apps). 4CAT at this time does not support two-factor "
                    "authentication for Telegram."
        },
        "api_id": {
            "type": UserInput.OPTION_TEXT,
            "help": "API ID",
            "cache": True,
        },
        "api_hash": {
            "type": UserInput.OPTION_TEXT,
            "help": "API Hash",
            "cache": True,
        },
        "api_phone": {
            "type": UserInput.OPTION_TEXT,
            "help": "Phone number",
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
            "help": "You can collect messages from up to **25** entities (channels or groups) at a time. Separate with "
                    "commas or line breaks."
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
        },
        "daterange": {
            "type": UserInput.OPTION_DATERANGE,
            "help": "Date range"
        },
        "divider-2": {
            "type": UserInput.OPTION_DIVIDER
        },
        "info-sensitive": {
            "type": UserInput.OPTION_INFO,
            "help": "Your API credentials and phone number **will be sent to the 4CAT server** and will be stored "
                    "there while data is fetched. After the dataset has been created your credentials will be "
                    "deleted from the server, unless you enable the option below. If you want to download images "
                    "attached to the messages in your collected data, you need to enable this option. Your "
                    "credentials will never be visible to other users and can be erased later via the result page."
        },
        "save-session": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Save session:",
            "default": False
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

        self.details_cache = {}
        self.failures_cache = set()
        results = asyncio.run(self.execute_queries())

        if not query.get("save-session"):
            self.dataset.delete_parameter("api_hash", instant=True)
            self.dataset.delete_parameter("api_phone", instant=True)
            self.dataset.delete_parameter("api_id", instant=True)

        if not self.flawless:
            self.dataset.update_status("Dataset completed, but some requested entities were unavailable (they may have"
                                       "been private). View the log file for details.", is_final=True)

        return results

    async def execute_queries(self):
        """
        Get messages for queries

        This is basically what would be done in get_items(), except due to
        Telethon's architecture this needs to be called in an async method,
        which is this one.

        :return list:  Collected messages
        """
        # session file has been created earlier, and we can re-use it here in
        # order to avoid having to re-enter the security code
        query = self.parameters

        session_id = SearchTelegram.create_session_id(query["api_phone"], query["api_id"], query["api_hash"])
        self.dataset.log('Telegram session id: %s' % session_id)
        session_path = Path(config.PATH_ROOT).joinpath(config.PATH_SESSIONS, session_id + ".session")

        client = None

        try:
            client = TelegramClient(str(session_path), int(query.get("api_id")), query.get("api_hash"),
                                    loop=self.eventloop)
            await client.start(phone=SearchTelegram.cancel_start)
        except RuntimeError:
            # session is no longer useable, delete file so user will be asked
            # for security code again. The RuntimeError is raised by
            # `cancel_start()`
            self.dataset.update_status(
                "Session is not authenticated: login security code may have expired. You need to re-enter the security code.",
                is_final=True)

            if client and hasattr(client, "disconnect"):
                await client.disconnect()

            if session_path.exists():
                session_path.unlink()

            return []
        except Exception as e:
            # not sure what exception specifically is triggered here, but it
            # always means the connection failed
            self.log.error("Telegram: %s\n%s" % (str(e), traceback.format_exc()))
            self.dataset.update_status("Error connecting to the Telegram API with provided credentials.", is_final=True)
            if client and hasattr(client, "disconnect"):
                await client.disconnect()
            return []

        # ready our parameters
        parameters = self.dataset.get_parameters()
        queries = [query.strip() for query in parameters.get("query", "").split(",")]
        max_items = convert_to_int(parameters.get("items", 10), 10)

        # Telethon requires the offset date to be a datetime date
        max_date = parameters.get("max_date")
        if max_date:
            try:
                max_date = datetime.fromtimestamp(int(max_date))
            except ValueError:
                max_date = None

        # min_date can remain an integer
        min_date = parameters.get("min_date")
        if min_date:
            try:
                min_date = int(min_date)
            except ValueError:
                min_date = None

        posts = []
        try:
            async for post in self.gather_posts(client, queries, max_items, min_date, max_date):
                posts.append(post)
            return posts
        except ProcessorInterruptedException as e:
            raise e
        except Exception as e:
            # catch-all so we can disconnect properly
            # ...should we?
            self.dataset.update_status("Error scraping posts from Telegram")
            self.log.error("Telegram scraping error: %s" % traceback.format_exc())
            return []
        finally:
            await client.disconnect()

    async def gather_posts(self, client, queries, max_items, min_date, max_date):
        """
        Gather messages for each entity for which messages are requested

        :param TelegramClient client:  Telegram Client
        :param list queries:  List of entities to query (as string)
        :param int max_items:  Messages to scrape per entity
        :param int min_date:  Datetime date to get posts after
        :param int max_date:  Datetime date to get posts before
        :return list:  List of messages, each message a dictionary.
        """
        resolve_refs = self.parameters.get("resolve-entities")

        # Adding flag to stop; using for rate limits
        no_additional_queries = False

        # Collect queries
        for query in queries:
            delay = 10
            retries = 0

            if no_additional_queries:
                # Note that we are note completing this query
                self.dataset.update_status("Rate-limited by Telegram; not executing query %s" % query)
                continue

            while True:
                self.dataset.update_status("Fetching messages for entity '%s'" % query)
                i = 0
                try:
                    entity_posts = 0
                    async for message in client.iter_messages(entity=query, offset_date=max_date):
                        entity_posts += 1
                        i += 1
                        if self.interrupted:
                            raise ProcessorInterruptedException(
                                "Interrupted while fetching message data from the Telegram API")

                        if entity_posts % 100 == 0:
                            self.dataset.update_status(
                                "Retrieved %i posts for entity '%s' (%i total)" % (entity_posts, query, i))

                        if message.action is not None:
                            # e.g. someone joins the channel - not an actual message
                            continue

                        # todo: possibly enrich object with e.g. the name of
                        # the channel a message was forwarded from (but that
                        # needs extra API requests...)
                        serialized_message = SearchTelegram.serialize_obj(message)
                        if resolve_refs:
                            serialized_message = await self.resolve_groups(client, serialized_message)

                        # Stop if we're below the min date
                        if min_date and serialized_message.get("date") < min_date:
                            break

                        yield serialized_message

                        if entity_posts >= max_items:
                            break

                except ChannelPrivateError:
                    self.dataset.update_status("Entity %s is private, skipping" % query)
                    self.flawless = False

                except (UsernameInvalidError,):
                    self.dataset.update_status("Could not scrape entity '%s', does not seem to exist, skipping" % query)
                    self.flawless = False

                except FloodWaitError as e:
                    self.dataset.update_status("Rate-limited by Telegram: %s; waiting" % str(e))
                    if e.seconds < self.end_if_rate_limited:
                        time.sleep(e.seconds)
                        continue
                    else:
                        self.flawless = False
                        no_additional_queries = True
                        self.dataset.update_status("Telegram wait grown large than %i minutes, ending" % int(e.seconds/60))
                        break

                except BadRequestError as e:
                    self.dataset.update_status("Error '%s' while collecting entity %s, skipping" % (e.__class__.__name__, query))
                    self.flawless = False

                except ValueError as e:
                    self.dataset.update_status("Error '%s' while collecting entity %s, skipping" % (str(e), query))
                    self.flawless = False

                except ChannelPrivateError as e:
                    self.dataset.update_status(
                        "QUERY '%s' unable to complete due to error %s. Skipping." % (
                        query, str(e)))
                    break

                except TimeoutError:
                    if retries < 3:
                        self.dataset.update_status(
                            "Tried to fetch messages for entity '%s' but timed out %i times. Skipping." % (
                            query, retries))
                        self.flawless = False
                        break

                    self.dataset.update_status(
                        "Got a timeout from Telegram while fetching messages for entity '%s'. Trying again in %i seconds." % (
                        query, delay))
                    time.sleep(delay)
                    delay *= 2
                    continue

                break

    async def resolve_groups(self, client, message):
        """
        Recursively resolve references to groups and users

        :param client:  Telethon client instance
        :param dict message:  Message, as already mapped by serialize_obj
        :return:  Resolved dictionary
        """
        resolved_message = message.copy()
        for key, value in message.items():
            try:
                if type(value) is not dict:
                    # if it's not a dict, we never have to resolve it, as it
                    # does not represent an entity
                    continue

                elif "_type" in value and value["_type"] in ("InputPeerChannel", "PeerChannel"):
                    # forwarded from a channel!
                    if value["channel_id"] in self.failures_cache:
                        continue

                    if value["channel_id"] not in self.details_cache:
                        channel = await client(GetFullChannelRequest(value["channel_id"]))
                        self.details_cache[value["channel_id"]] = SearchTelegram.serialize_obj(channel)

                    resolved_message[key] = self.details_cache[value["channel_id"]]
                    resolved_message[key]["channel_id"] = value["channel_id"]

                elif "_type" in value and value["_type"] == "PeerUser":
                    # a user!
                    if value["user_id"] in self.failures_cache:
                        continue

                    if value["user_id"] not in self.details_cache:
                        user = await client(GetFullUserRequest(value["user_id"]))
                        self.details_cache[value["user_id"]] = SearchTelegram.serialize_obj(user)

                    resolved_message[key] = self.details_cache[value["user_id"]]
                else:
                    resolved_message[key] = await self.resolve_groups(client, value)

            except (TypeError, ChannelPrivateError, UsernameInvalidError) as e:
                self.failures_cache.add(value.get("channel_id", value.get("user_id")))
                if type(e) in (ChannelPrivateError, UsernameInvalidError):
                    self.dataset.log("Cannot resolve entity with ID %s of type %s (%s), leaving as-is" % (
                    str(value.get("channel_id", value.get("user_id"))), value["_type"], e.__class__.__name__))
                else:
                    self.dataset.log("Cannot resolve entity with ID %s of type %s, leaving as-is" % (str(value.get("channel_id", value.get("user_id"))), value["_type"]))

        return resolved_message

    @staticmethod
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

    @staticmethod
    def map_item(message):
        """
        Convert Message object to 4CAT-ready data object

        :param Message message:  Message to parse
        :return dict:  4CAT-compatible item object
        """
        thread = message["_chat"]["username"]

        # determine username
        # API responses only include the user *ID*, not the username, and to
        # complicate things further not everyone is a user and not everyone
        # has a username. If no username is available, try the first and
        # last name someone has supplied
        fullname = ""
        username = ""
        user_id = message["_sender"]["id"] if message.get("_sender") else ""
        user_is_bot = message["_sender"].get("bot", False) if message.get("_sender") else ""

        if message.get("_sender") and message["_sender"].get("username"):
            username = message["_sender"]["username"]

        if message.get("_sender") and message["_sender"].get("first_name"):
            fullname += message["_sender"]["first_name"]

        if message.get("_sender") and message["_sender"].get("last_name"):
            fullname += " " + message["_sender"]["last_name"]

        fullname = fullname.strip()

        # determine media type
        # these store some extra information of the attachment in
        # attachment_data. Since the final result will be serialised as a csv
        # file, we can only store text content. As such some media data is
        # serialised as JSON.
        attachment_type = SearchTelegram.get_media_type(message["media"])
        attachment_filename = ""

        if attachment_type == "contact":
            attachment = message["media"]["contact"]
            attachment_data = json.dumps({property: attachment.get(property) for property in
                                          ("phone_number", "first_name", "last_name", "vcard", "user_id")})

        elif attachment_type == "document":
            # videos, etc
            # This could add a separate routine for videos to make them a
            # separate type, which could then be scraped later, etc
            attachment_type = message["media"]["document"]["mime_type"].split("/")[0]
            if attachment_type == "video":
                attachment = message["media"]["document"]
                attachment_data = json.dumps({
                    "id": attachment["id"],
                    "dc_id": attachment["dc_id"],
                    "file_reference": attachment["file_reference"],
                })
            else:
                attachment_data = ""

        #elif attachment_type in ("geo", "geo_live"):
            # untested whether geo_live is significantly different from geo
        #    attachment_data = "%s %s" % (message["geo"]["lat"], message["geo"]["long"])

        elif attachment_type == "photo":
            # we don't actually store any metadata about the photo, since very
            # little of the metadata attached is of interest. Instead, the
            # actual photos may be downloaded via a processor that is run on the
            # search results
            attachment = message["media"]["photo"]
            attachment_data = json.dumps({
                "id": attachment["id"],
                "dc_id": attachment["dc_id"],
                "file_reference": attachment["file_reference"],
            })
            attachment_filename = thread + "-" + str(message["id"]) + ".jpeg"

        elif attachment_type == "poll":
            # unfortunately poll results are only available when someone has
            # actually voted on the poll - that will usually not be the case,
            # so we store -1 as the vote count
            attachment = message["media"]
            options = {option["option"]: option["text"] for option in attachment["poll"]["answers"]}
            attachment_data = json.dumps({
                "question": attachment["poll"]["question"],
                "voters": attachment["results"]["total_voters"],
                "answers": [{
                    "answer": options[answer["option"]],
                    "votes": answer["voters"]
                } for answer in attachment["results"]["results"]] if attachment["results"]["results"] else [{
                    "answer": options[option],
                    "votes": -1
                } for option in options]
            })

        elif attachment_type == "url":
            # easy!
            attachment_data = message["media"].get("web_preview", {}).get("url", "")

        else:
            attachment_data = ""

        # was the message forwarded from somewhere and if so when?
        forwarded_timestamp = ""
        forwarded_name = ""
        forwarded_username = ""
        if message.get("fwd_from") and "from_id" in message["fwd_from"]:
            # forward information is spread out over a lot of places
            # we can identify, in order of usefulness: username, full name,
            # and ID. But not all of these are always available, and not
            # always in the same place either
            forwarded_timestamp = int(message["fwd_from"]["date"])
            from_data = message["fwd_from"]["from_id"]

            if from_data:
                forwarded_from_id = from_data.get("channel_id", from_data.get("user_id", ""))

            if message["fwd_from"].get("from_name"):
                forwarded_name = message["fwd_from"].get("from_name")

            if from_data and from_data.get("from_name"):
                forwarded_name = message["fwd_from"]["from_name"]

            if from_data and ("user" in from_data or "chats" in from_data):
                # 'resolve entities' was enabled for this dataset
                if "user" in from_data:
                    if from_data["user"].get("username"):
                        forwarded_username = from_data["user"]["username"]

                    if from_data["user"].get("first_name"):
                        forwarded_name = from_data["user"]["first_name"]
                    if message["fwd_from"].get("last_name"):
                        forwarded_name += "  " + from_data["user"]["last_name"]

                    forwarded_name = forwarded_name.strip()

                elif "chats" in from_data:
                    channel_id = from_data["channel_id"]
                    for chat in from_data["chats"]:
                        if chat["id"] == channel_id:
                            forwarded_username = chat["username"]

        msg = {
            "id": message["id"],
            "thread_id": thread,
            "chat": message["_chat"]["username"],
            "author": user_id,
            "author_username": username,
            "author_name": fullname,
            "author_is_bot": user_is_bot,
            "body": message["message"],
            "reply_to": message.get("reply_to_msg_id", ""),
            "views": message["views"] if message["views"] else "",
            "timestamp": datetime.fromtimestamp(message["date"]).strftime("%Y-%m-%d %H:%M:%S"),
            "unix_timestamp": int(message["date"]),
            "timestamp_edited": datetime.fromtimestamp(message["edit_date"]).strftime("%Y-%m-%d %H:%M:%S") if message["edit_date"] else "",
            "unix_timestamp_edited": int(message["edit_date"]) if message["edit_date"] else "",
            "author_forwarded_from_name": forwarded_name,
            "author_forwarded_from_username": forwarded_username,
            "timestamp_forwarded_from": datetime.fromtimestamp(forwarded_timestamp).strftime("%Y-%m-%d %H:%M:%S") if forwarded_timestamp else "",
            "unix_timestamp_forwarded_from": forwarded_timestamp,
            "attachment_type": attachment_type,
            "attachment_data": attachment_data,
            "attachment_filename": attachment_filename
        }

        return msg

    @staticmethod
    def get_media_type(media):
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
            }[media.get("_type", None)]
        except (AttributeError, KeyError):
            return ""

    @staticmethod
    def serialize_obj(input_obj):
        """
        Serialize an object as a dictionary

        Telethon message objects are not serializable by themselves, but most
        relevant attributes are simply struct classes. This function replaces
        those that are not with placeholders and then returns a dictionary that
        can be serialized as JSON.

        :param obj:  Object to serialize
        :return:  Serialized object
        """
        scalars = (int, str, float, list, tuple, set, bool)

        if type(input_obj) in scalars or input_obj is None:
            return input_obj

        if type(input_obj) is not dict:
            obj = input_obj.__dict__
        else:
            obj = input_obj.copy()

        mapped_obj = {}
        for item, value in obj.items():
            if type(value) is datetime:
                mapped_obj[item] = value.timestamp()
            elif type(value).__module__ in ("telethon.tl.types", "telethon.tl.custom.forward"):
                mapped_obj[item] = SearchTelegram.serialize_obj(value)
                if type(obj[item]) is not dict:
                    mapped_obj[item]["_type"] = type(value).__name__
            elif type(value) is list:
                mapped_obj[item] = [SearchTelegram.serialize_obj(item) for item in value]
            elif type(value).__module__[0:8] == "telethon":
                # some type of internal telethon struct
                continue
            elif type(value) is bytes:
                mapped_obj[item] = value.hex()
            elif type(value) not in scalars and value is not None:
                # type we can't make sense of here
                continue
            elif type(value) is dict:
                for key, vvalue in value:
                    mapped_obj[item][key] = SearchTelegram.serialize_obj(vvalue)
            else:
                mapped_obj[item] = value

        return mapped_obj

    @staticmethod
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

        privileged = user.get_value("telegram.can_query_all_messages", False)

        # reformat queries to be a comma-separated list with no wrapping
        # whitespace
        whitespace = re.compile(r"\s+")
        items = whitespace.sub("", query.get("query").replace("\n", ","))
        if len(items.split(",")) > 25 and not privileged:
            raise QueryParametersException("You cannot query more than 25 items at a time.")

        sanitized_items = []
        # handle telegram URLs
        for item in items.split(","):
            if not item.strip():
                continue
            item = re.sub(r"^https?://t\.me/", "", item)
            item = re.sub(r"^/?s/", "", item)
            item = re.sub(r"[/]*$", "", item)
            sanitized_items.append(item)

        # the dates need to make sense as a range to search within
        min_date, max_date = query.get("daterange")

        # simple!
        return {
            "items": query.get("max_posts"),
            "query": ",".join(sanitized_items),
            "board": "",  # needed for web interface
            "api_id": query.get("api_id"),
            "api_hash": query.get("api_hash"),
            "api_phone": query.get("api_phone"),
            "save-session": query.get("save-session"),
            "resolve-entities": query.get("resolve-entities") if privileged else False,
            "min_date": min_date,
            "max_date": max_date
        }

    @staticmethod
    def create_session_id(api_phone, api_id, api_hash):
        """
        Generate a filename for the session file

        This is a combination of phone number and API credentials, but hashed
        so that one cannot actually derive someone's phone number from it.

        :param str api_phone:  Phone number for API ID
        :param int api_id:  Telegram API ID
        :param str api_hash:  Telegram API Hash
        :return str: A hash value derived from the input
        """
        hash_base = api_phone.strip().replace("+", "") + str(api_id).strip() + api_hash.strip()
        return hashlib.blake2b(hash_base.encode("ascii")).hexdigest()

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

        if user and user.get_value("telegram.can_query_all_messages", False):
            if "max" in options["max_posts"]:
                del options["max_posts"]["max"]

            options["query-intro"]["help"] = "You can collect messages from multiple entities (channels or groups). Separate with commas or line breaks."

            options["resolve-entities-intro"] = {
                "type": UserInput.OPTION_INFO,
                "help": "4CAT can resolve the references to channels and user and replace the numeric ID with the full "
                        "user, channel or group metadata. Doing so allows one to discover e.g. new relevant groups and "
                        "figure out where or who a message was forwarded from. However, this increases query time and "
                        "for large datasets, increases the chance you will be rate-limited and your dataset isn't able "
                        "to finish capturing. It will also dramatically increase the disk space needed to store the "
                        "data, so only enable this if you really need it!"
            }

            options["resolve-entities"] = {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Resolve references",
                "default": False,
            }

        return options
