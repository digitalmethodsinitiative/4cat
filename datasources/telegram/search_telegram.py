"""
Search Telegram via API
"""
import traceback
import datetime
import hashlib
import asyncio
import json
import time
import re

from pathlib import Path

from backend.lib.search import Search
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException, ProcessorException, \
    QueryNeedsFurtherInputException
from common.lib.helpers import convert_to_int, UserInput
from common.lib.item_mapping import MappedItem, MissingMappedField
from common.config_manager import config

from datetime import datetime
from telethon import TelegramClient
from telethon.errors.rpcerrorlist import UsernameInvalidError, TimeoutError, ChannelPrivateError, BadRequestError, \
    FloodWaitError, ApiIdInvalidError, PhoneNumberInvalidError, RPCError
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import User



class SearchTelegram(Search):
    """
    Search Telegram via API
    """
    type = "telegram-search"  # job ID
    category = "Search"  # category
    title = "Telegram API search"  # title displayed in UI
    description = "Scrapes messages from open Telegram groups via its API."  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    is_local = False  # Whether this datasource is locally scraped
    is_static = False  # Whether this datasource is still updated

    # cache
    details_cache = None
    failures_cache = None
    eventloop = None
    import_issues = 0
    end_if_rate_limited = 600  # break if Telegram requires wait time above number of seconds

    max_workers = 1
    max_retries = 3
    flawless = 0

    config = {
        "telegram-search.can_query_all_messages": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Remove message amount limit",
            "default": False,
            "tooltip": "Allows users to query unlimited messages from Telegram. This can lead to HUGE datasets!"
        },
        "telegram-search.max_entities": {
            "type": UserInput.OPTION_TEXT,
            "help": "Max entities to query",
            "coerce_type": int,
            "min": 0,
            "default": 25,
            "tooltip": "Amount of entities that can be queried at a time. Entities are groups or channels. 0 to "
                       "disable limit."
        },
        "telegram-search.max_crawl_depth": {
            "type": UserInput.OPTION_TEXT,
            "help": "Max crawl depth",
            "coerce_type": int,
            "min": 0,
            "default": 0,
            "tooltip": "If higher than 0, 4CAT can automatically add new entities to the query based on forwarded "
                       "messages. Recommended to leave at 0 for most users since this can exponentially increase "
                       "dataset sizes."
        }
    }

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        """
        Get processor options

        Just updates the description of the entities field based on the
        configured max entities.

        :param DataSet parent_dataset:  An object representing the dataset that
          the processor would be run on
        :param User user:  Flask user the options will be displayed for, in
          case they are requested for display in the 4CAT web interface. This can
          be used to show some options only to privileges users.
        """
        max_entities = config.get("telegram-search.max_entities", 25, user=user)
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
            "divider": {
                "type": UserInput.OPTION_DIVIDER
            },
            "query-intro": {
                "type": UserInput.OPTION_INFO,
                "help": "Separate with commas or line breaks."
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
            },
            "resolve-entities-intro": {
                "type": UserInput.OPTION_INFO,
                "help": "4CAT can resolve the references to channels and user and replace the numeric ID with the full "
                        "user, channel or group metadata. Doing so allows one to discover e.g. new relevant groups and "
                        "figure out where or who a message was forwarded from.\n\nHowever, this increases query time and "
                        "for large datasets, increases the chance you will be rate-limited and your dataset isn't able "
                        "to finish capturing. It will also dramatically increase the disk space needed to store the "
                        "data, so only enable this if you really need it!"
            },
            "resolve-entities": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Resolve references",
                "default": False,
            }
        }

        if max_entities:
            options["query-intro"]["help"] = (f"You can collect messages from up to **{max_entities:,}** entities "
                                              f"(channels or groups) at a time. Separate with line breaks or commas.")

        all_messages = config.get("telegram-search.can_query_all_messages", False, user=user)
        if all_messages:
            if "max" in options["max_posts"]:
                del options["max_posts"]["max"]
        else:
            options["max_posts"]["help"] = (f"Messages to collect per entity. You can query up to "
                                             f"{options['max_posts']['max']:,} messages per entity.")

        if config.get("telegram-search.max_crawl_depth", 0, user=user) > 0:
            options["crawl_intro"] = {
                "type": UserInput.OPTION_INFO,
                "help": "Optionally, 4CAT can 'discover' new entities via forwarded messages; for example, if a "
                        "channel X you are collecting data for contains a message forwarded from channel Y, 4CAT can "
                        "collect messages from both channel X and Y. **Use this feature with caution**, as datasets can "
                        "rapidly grow when adding newly discovered entities to the query this way. Note that dataset "
                        "progress cannot be accurately tracked when you use this feature."
            }
            options["crawl-depth"] = {
                "type": UserInput.OPTION_TEXT,
                "coerce_type": int,
                "min": 0,
                "max": config.get("telegram-search.max_crawl_depth"),
                "default": 0,
                "help": "Crawl depth",
                "tooltip": "How many 'hops' to make when crawling messages. This is the distance from an initial "
                           "query, i.e. at most this many hops can be needed to reach the entity from one of the "
                           "starting entities."
            }
            options["crawl-threshold"] = {
                "type": UserInput.OPTION_TEXT,
                "coerce_type": int,
                "min": 0,
                "default": 5,
                "help": "Crawl threshold",
                "tooltip": "Entities need to be references at least this many times to be added to the query. Only "
                           "references discovered below the max crawl depth are taken into account."
            }

        return options


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

        if self.flawless:
            self.dataset.update_status(f"Dataset completed, but {self.flawless} requested entities were unavailable (they may have "
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
        self.dataset.log(f'Telegram session id: {session_id}')
        session_path = Path(config.get("PATH_ROOT")).joinpath(config.get("PATH_SESSIONS"), session_id + ".session")

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
            self.log.error(f"Telegram: {e}\n{traceback.format_exc()}")
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
            self.log.error(f"Telegram scraping error: {traceback.format_exc()}")
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

        # This is used for the 'crawl' feature so we know at which depth a
        # given entity was discovered
        depth_map = {
            entity: 0 for entity in queries
        }

        crawl_max_depth = self.parameters.get("crawl-depth", 0)
        crawl_msg_threshold = self.parameters.get("crawl-threshold", 10)

        self.dataset.log(f"Max crawl depth: {crawl_max_depth}")
        self.dataset.log(f"Crawl threshold: {crawl_msg_threshold}")

        # this keeps track of how often an entity not in the original query
        # has been mentioned. When crawling is enabled and this exceeds the
        # given threshold, the entity is added to the query
        crawl_references = {}
        queried_entities = list(queries)
        full_query = list(queries)

        # we may not always know the 'entity username' for an entity ID, so
        # keep a reference map as we go
        entity_id_map = {}

        # Collect queries
        # Use while instead of for so we can change queries during iteration
        # this is needed for the 'crawl' feature which can discover new
        # entities during crawl
        processed = 0
        total_messages = 0
        while queries:
            query = queries.pop(0)

            delay = 10
            retries = 0
            processed += 1
            self.dataset.update_progress(processed / len(full_query))

            if no_additional_queries:
                # Note that we are note completing this query
                self.dataset.update_status(f"Rate-limited by Telegram; not executing query {entity_id_map.get(query, query)}")
                continue

            while True:
                self.dataset.update_status(f"Retrieving messages for entity '{entity_id_map.get(query, query)}'")
                try:
                    entity_posts = 0
                    async for message in client.iter_messages(entity=query, offset_date=max_date):
                        entity_posts += 1
                        total_messages += 1
                        if self.interrupted:
                            raise ProcessorInterruptedException(
                                "Interrupted while fetching message data from the Telegram API")

                        if entity_posts % 100 == 0:
                            self.dataset.update_status(
                                f"Retrieved {entity_posts:,} posts for entity '{entity_id_map.get(query, query)}' ({total_messages:,} total)")

                        if message.action is not None:
                            # e.g. someone joins the channel - not an actual message
                            continue

                        # todo: possibly enrich object with e.g. the name of
                        # the channel a message was forwarded from (but that
                        # needs extra API requests...)
                        serialized_message = SearchTelegram.serialize_obj(message)
                        if "_chat" in serialized_message and query not in entity_id_map and serialized_message["_chat"]["id"] == query:
                            # once we know what a channel ID resolves to, use the username instead so it is easier to
                            # understand for the user
                            entity_id_map[query] = serialized_message["_chat"]["username"]
                            self.dataset.update_status(f"Fetching messages for entity '{entity_id_map[query]}' (channel ID {query})")

                        if resolve_refs:
                            serialized_message = await self.resolve_groups(client, serialized_message)

                        # Stop if we're below the min date
                        if min_date and serialized_message.get("date") < min_date:
                            break

                        # if crawling is enabled, see if we found something to add to the query
                        if crawl_max_depth and (not crawl_msg_threshold or depth_map.get(query) < crawl_msg_threshold):
                            message_fwd = serialized_message.get("fwd_from")
                            fwd_from = None
                            if message_fwd and message_fwd["from_id"] and message_fwd["from_id"].get("_type") == "PeerChannel":
                                # even if we haven't resolved the ID, we can feed the numeric ID
                                # to Telethon! this is nice because it means we don't have to
                                # resolve entities to crawl iteratively
                                fwd_from = int(message_fwd["from_id"]["channel_id"])

                            if fwd_from and fwd_from not in queried_entities and fwd_from not in queries:
                                # new entity discovered!
                                # might be discovered (before collection) multiple times, so retain lowest depth
                                depth_map[fwd_from] = min(depth_map.get(fwd_from, crawl_max_depth), depth_map[query] + 1)
                                if depth_map[query] < crawl_max_depth:
                                    if fwd_from not in crawl_references:
                                        crawl_references[fwd_from] = 0

                                    crawl_references[fwd_from] += 1
                                    if crawl_references[fwd_from] >= crawl_msg_threshold and fwd_from not in queries:
                                        queries.append(fwd_from)
                                        full_query.append(fwd_from)
                                        self.dataset.update_status(f"Discovered new entity {entity_id_map.get(fwd_from, fwd_from)} in {entity_id_map.get(query, query)} at crawl depth {depth_map[query]}, adding to query")

                        yield serialized_message

                        if entity_posts >= max_items:
                            break

                except ChannelPrivateError:
                    self.dataset.update_status(f"Entity {entity_id_map.get(query, query)} is private, skipping")
                    self.flawless += 1

                except (UsernameInvalidError,):
                    self.dataset.update_status(f"Could not scrape entity '{entity_id_map.get(query, query)}', does not seem to exist, skipping")
                    self.flawless += 1

                except FloodWaitError as e:
                    self.dataset.update_status(f"Rate-limited by Telegram: {e}; waiting")
                    if e.seconds < self.end_if_rate_limited:
                        time.sleep(e.seconds)
                        continue
                    else:
                        self.flawless += 1
                        no_additional_queries = True
                        self.dataset.update_status(
                            f"Telegram wait grown larger than {int(e.seconds / 60)} minutes, ending")
                        break

                except BadRequestError as e:
                    self.dataset.update_status(
                        f"Error '{e.__class__.__name__}' while collecting entity {entity_id_map.get(query, query)}, skipping")
                    self.flawless += 1

                except ValueError as e:
                    self.dataset.update_status(f"Error '{e}' while collecting entity {entity_id_map.get(query, query)}, skipping")
                    self.flawless += 1

                except ChannelPrivateError as e:
                    self.dataset.update_status(
                        f"QUERY '{entity_id_map.get(query, query)}' unable to complete due to error {e}. Skipping.")
                    break

                except TimeoutError:
                    if retries < 3:
                        self.dataset.update_status(
                            f"Tried to fetch messages for entity '{entity_id_map.get(query, query)}' but timed out {retries:,} times. Skipping.")
                        self.flawless += 1
                        break

                    self.dataset.update_status(
                        f"Got a timeout from Telegram while fetching messages for entity '{entity_id_map.get(query, query)}'. Trying again in {delay:,} seconds.")
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
                    resolved_message[key]["user_id"] = value["user_id"]
                else:
                    resolved_message[key] = await self.resolve_groups(client, value)

            except (TypeError, ChannelPrivateError, UsernameInvalidError) as e:
                self.failures_cache.add(value.get("channel_id", value.get("user_id")))
                if type(e) in (ChannelPrivateError, UsernameInvalidError):
                    self.dataset.log(f"Cannot resolve entity with ID {value.get('channel_id', value.get('user_id'))} of type {value['_type']} ({e.__class__.__name__}), leaving as-is")
                else:
                    self.dataset.log(f"Cannot resolve entity with ID {value.get('channel_id', value.get('user_id'))} of type {value['_type']}, leaving as-is")

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
        if message["_chat"]["username"]:
            # chats can apparently not have usernames???
            # truly telegram objects are way too lenient for their own good
            thread = message["_chat"]["username"]
        elif message["_chat"]["title"]:
            thread = re.sub(r"\s", "", message["_chat"]["title"])
        else:
            # just give up
            thread = "unknown"

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
            contact_data = ["phone_number", "first_name", "last_name", "vcard", "user_id"]
            if message["media"].get('contact', False):
                # Old datastructure
                attachment = message["media"]["contact"]
            elif all([property in message["media"].keys() for property in contact_data]):
                # New datastructure 2022/7/25
                attachment = message["media"]
            else:
                raise ProcessorException('Cannot find contact data; Telegram datastructure may have changed')
            attachment_data = json.dumps({property: attachment.get(property) for property in contact_data})

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

        # elif attachment_type in ("geo", "geo_live"):
        # untested whether geo_live is significantly different from geo
        #    attachment_data = "%s %s" % (message["geo"]["lat"], message["geo"]["long"])

        elif attachment_type == "photo" or attachment_type == "url" and message["media"]["webpage"].get("photo"):
            # we don't actually store any metadata about the photo, since very
            # little of the metadata attached is of interest. Instead, the
            # actual photos may be downloaded via a processor that is run on the
            # search results
            attachment = message["media"]["photo"] if attachment_type == "photo" else message["media"]["webpage"]["photo"]
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

        else:
            attachment_data = ""

        # was the message forwarded from somewhere and if so when?
        forwarded_timestamp = ""
        forwarded_name = ""
        forwarded_id = ""
        forwarded_username = ""
        if message.get("fwd_from") and "from_id" in message["fwd_from"] and not (
                type(message["fwd_from"]["from_id"]) is int):
            # forward information is spread out over a lot of places
            # we can identify, in order of usefulness: username, full name,
            # and ID. But not all of these are always available, and not
            # always in the same place either
            forwarded_timestamp = int(message["fwd_from"]["date"])
            from_data = message["fwd_from"]["from_id"]

            if from_data:
                forwarded_id = from_data.get("channel_id", from_data.get("user_id", ""))

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
                    channel_id = from_data.get("channel_id")
                    for chat in from_data["chats"]:
                        if chat["id"] == channel_id or channel_id is None:
                            forwarded_username = chat["username"]

        link_title = ""
        link_attached = ""
        link_description = ""
        reactions = ""

        if message.get("media") and message["media"].get("webpage"):
            link_title = message["media"]["webpage"].get("title")
            link_attached = message["media"]["webpage"].get("url")
            link_description = message["media"]["webpage"].get("description")

        if message.get("reactions") and message["reactions"].get("results"):
            for reaction in message["reactions"]["results"]:
                if type(reaction["reaction"]) is dict and "emoticon" in reaction["reaction"]:
                    # Updated to support new reaction datastructure
                    reactions += reaction["reaction"]["emoticon"] * reaction["count"]
                elif type(reaction["reaction"]) is str and "count" in reaction:
                    reactions += reaction["reaction"] * reaction["count"]
                else:
                    # Failsafe; can be updated to support formatting of new datastructures in the future
                    reactions += f"{reaction}, "

        return MappedItem({
            "id": f"{message['_chat']['username']}-{message['id']}",
            "thread_id": thread,
            "chat": message["_chat"]["username"],
            "author": user_id,
            "author_username": username,
            "author_name": fullname,
            "author_is_bot": "yes" if user_is_bot else "no",
            "body": message["message"],
            "reply_to": message.get("reply_to_msg_id", ""),
            "views": message["views"] if message["views"] else "",
            "forwards": message.get("forwards", MissingMappedField(0)),
            "reactions": reactions,
            "timestamp": datetime.fromtimestamp(message["date"]).strftime("%Y-%m-%d %H:%M:%S"),
            "unix_timestamp": int(message["date"]),
            "timestamp_edited": datetime.fromtimestamp(message["edit_date"]).strftime("%Y-%m-%d %H:%M:%S") if message[
                "edit_date"] else "",
            "unix_timestamp_edited": int(message["edit_date"]) if message["edit_date"] else "",
            "author_forwarded_from_name": forwarded_name,
            "author_forwarded_from_username": forwarded_username,
            "author_forwarded_from_id": forwarded_id,
            "timestamp_forwarded_from": datetime.fromtimestamp(forwarded_timestamp).strftime(
                "%Y-%m-%d %H:%M:%S") if forwarded_timestamp else "",
            "unix_timestamp_forwarded_from": forwarded_timestamp,
            "link_title": link_title,
            "link_description": link_description,
            "link_attached": link_attached,
            "attachment_type": attachment_type,
            "attachment_data": attachment_data,
            "attachment_filename": attachment_filename
        })

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
            elif type(value) is list:
                mapped_obj[item] = [SearchTelegram.serialize_obj(item) for item in value]
            elif type(value) is bytes:
                mapped_obj[item] = value.hex()
            elif type(value) not in scalars and value is not None:
                # type we can't make sense of here
                continue
            else:
                mapped_obj[item] = value

        # Add the _type if the original object was a telethon type
        if type(input_obj).__module__ in ("telethon.tl.types", "telethon.tl.custom.forward"):
            mapped_obj["_type"] = type(input_obj).__name__
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

        all_posts = config.get("telegram-search.can_query_all_messages", False, user=user)
        max_entities = config.get("telegram-search.max_entities", 25, user=user)

        num_items = query.get("max_posts") if all_posts else min(query.get("max_posts"), SearchTelegram.get_options()["max_posts"]["max"])

        # reformat queries to be a comma-separated list with no wrapping
        # whitespace
        whitespace = re.compile(r"\s+")
        items = whitespace.sub("", query.get("query").replace("\n", ","))
        if max_entities > 0 and len(items.split(",")) > max_entities:
            raise QueryParametersException(f"You cannot query more than {max_entities:,} items at a time.")

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

        # now check if there is an active API session
        if not user or not user.is_authenticated or user.is_anonymous:
            raise QueryParametersException("Telegram scraping is only available to logged-in users with personal "
                                           "accounts.")

        # check for the information we need
        session_id = SearchTelegram.create_session_id(query.get("api_phone"), query.get("api_id"),
                                                      query.get("api_hash"))
        user.set_value("telegram.session", session_id)
        session_path = Path(config.get('PATH_ROOT')).joinpath(config.get('PATH_SESSIONS'), session_id + ".session")

        client = None

        # API ID is always a number, if it's not, we can immediately fail
        try:
            api_id = int(query.get("api_id"))
        except ValueError:
            raise QueryParametersException("Invalid API ID.")

        # maybe we've entered a code already and submitted it with the request
        if "option-security-code" in request.form and request.form.get("option-security-code").strip():
            code_callback = lambda: request.form.get("option-security-code")
            max_attempts = 1
        else:
            code_callback = lambda: -1
            # max_attempts = 0 because authing will always fail: we can't wait for
            # the code to be entered interactively, we'll need to do a new request
            # but we can't just immediately return, we still need to call start()
            # to get telegram to send us a code
            max_attempts = 0

        # now try authenticating
        needs_code = False
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            client = TelegramClient(str(session_path), api_id, query.get("api_hash"), loop=loop)

            try:
                client.start(max_attempts=max_attempts, phone=query.get("api_phone"), code_callback=code_callback)

            except ValueError as e:
                # this happens if 2FA is required
                raise QueryParametersException("Your account requires two-factor authentication. 4CAT at this time "
                                               f"does not support this authentication mode for Telegram. ({e})")
            except RuntimeError as e:
                # A code was sent to the given phone number
                needs_code = True
        except FloodWaitError as e:
            # uh oh, we got rate-limited
            raise QueryParametersException("You were rate-limited and should wait a while before trying again. " +
                                           str(e).split("(")[0] + ".")
        except ApiIdInvalidError as e:
            # wrong credentials
            raise QueryParametersException("Your API credentials are invalid.")
        except PhoneNumberInvalidError as e:
            # wrong phone number
            raise QueryParametersException(
                "The phone number provided is not a valid phone number for these credentials.")
        except RPCError as e:
            # only seen this with an 'UPDATE_APP_TO_LOGIN' status
            raise QueryParametersException(f"Could not verify your authentication. You may need to update your "
                                           f"Telegram app(s) to the latest version to proceed ({e}).")
        except Exception as e:
            # ?
            raise QueryParametersException(
                f"An unexpected error ({e}) occurred and your authentication could not be verified.")
        finally:
            if client:
                client.disconnect()

        if needs_code:
            raise QueryNeedsFurtherInputException(config={
                "code-info": {
                    "type": UserInput.OPTION_INFO,
                    "help": "Please enter the security code that was sent to your Telegram app to continue."
                },
                "security-code": {
                    "type": UserInput.OPTION_TEXT,
                    "help": "Security code",
                    "sensitive": True
                }})

        # simple!
        return {
            "items": num_items,
            "query": ",".join(sanitized_items),
            "board": "",  # needed for web interface
            "api_id": query.get("api_id"),
            "api_hash": query.get("api_hash"),
            "api_phone": query.get("api_phone"),
            "save-session": query.get("save-session"),
            "resolve-entities": query.get("resolve-entities"),
            "min_date": min_date,
            "max_date": max_date,
            "crawl-depth": query.get("crawl-depth"),
            "crawl-threshold": query.get("crawl-threshold")
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
