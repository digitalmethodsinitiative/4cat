"""
Collect Bluesky posts
"""
import hashlib
import time
from datetime import datetime
from pathlib import Path

from dateutil import parser

from atproto import Client, Session, SessionEvent
from atproto_client.exceptions import UnauthorizedError, BadRequestError, InvokeTimeoutError, RequestException, \
    ModelError, NetworkError

from backend.lib.search import Search
from common.lib.exceptions import QueryParametersException, QueryNeedsExplicitConfirmationException, \
    ProcessorInterruptedException
from common.lib.helpers import timify_long
from common.lib.user_input import UserInput
from common.config_manager import config
from common.lib.item_mapping import MappedItem, MissingMappedField

class SearchBluesky(Search):
    """
    Search for posts in Bluesky
    """
    type = "bsky-search"  # job ID
    category = "Search"  # category
    title = "Bluesky Search"  # title displayed in UI
    description = "Collects Bluesky posts via its API."  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    is_local = False  # Whether this datasource is locally scraped
    is_static = False  # Whether this datasource is still updated

    config = {
        "bsky-search.max_results": {
            "type": UserInput.OPTION_TEXT,
            "help": "Maximum results per query",
            "coerce_type": int,
            "min": 0,
            "default": 50000,
            "tooltip": "Amount of results (e.g., posts) per query. '0' will allow unlimited."
        }
    }

    handle_lookup_error_messages = ['account is deactivated', "profile not found", "account has been suspended"]

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
        options = {
            "intro": {
                "type": UserInput.OPTION_INFO,
                "help": "Collects Bluesky posts via its API.\n\nYour login credentials will be sent to the 4CAT server "
                        "and stored there while data is fetched. After the dataset has been created your credentials "
                        "will be deleted from the server. \n[See tips and tricks on how to query Bluesky](https://bsky.social/about/blog/05-31-2024-search)."
            },
            "username": {
                "type": UserInput.OPTION_TEXT,
                "help": "Bluesky Username",
                "cache": True,
                "sensitive": True,
                "tooltip": "If no server is specified, .bsky.social is used."
            },
            "password": {
                "type": UserInput.OPTION_TEXT,
                "help": "Bluesky Password",
                "cache": True, # tells the frontend to cache this value
                "sensitive": True, # tells the backend to delete this value after use
                "password": True, # tells the frontend this is a password type
            },
            "divider": {
                "type": UserInput.OPTION_DIVIDER
            },
            "query": {
                "type": UserInput.OPTION_TEXT_LARGE,
                "help": "Search Queries",
                "tooltip": "Separate with commas or line breaks."
            },
            "max_posts": {
                "type": UserInput.OPTION_TEXT,
                "help": "Max posts per query",
                "min": 1,
                "default": 100
            },
            "daterange": {
                "type": UserInput.OPTION_DATERANGE,
                "help": "Date range",
                "tooltip": "The date range for the search. No date range will search all posts."
            },
        }

        # Update the max_posts setting from config
        max_posts = int(config.get('bsky-search.max_results', 100, user=user))
        if max_posts == 0:
            # This is potentially madness
            options["max_posts"]["tooltip"] = "Set to 0 to collect all posts."
            options['max_posts']['min'] = 0
        else:
            options["max_posts"]["max"] = max_posts
            options['max_posts']['default'] = options['max_posts']['default'] if options['max_posts']['default'] <= max_posts else max_posts

        return options

    @staticmethod
    def validate_query(query, request, user):
        """
        Validate Bluesky query

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param User user:  User object of user who has submitted the query
        :return dict:  Safe query parameters
        """
        # no query 4 u
        if not query.get("query", "").strip():
            raise QueryParametersException("You must provide a search query.")

        if not query.get("username", None) or not query.get("password", None) :
            raise QueryParametersException("You need to provide valid Bluesky login credentials first.")

        # If no server is specified, default to .bsky.social
        if "." not in query.get("username"):
            query["username"] += ".bsky.social"
        # Remove @ at the start
        if query.get("username").startswith("@"):
            query["username"] = query["username"][1:]

        # Test login credentials
        session_id = SearchBluesky.create_session_id(query["username"], query["password"])
        try:
            SearchBluesky.bsky_login(username=query["username"], password=query["password"], session_id=session_id)
        except UnauthorizedError as e:
            raise QueryParametersException("Invalid Bluesky login credentials.")
        except RequestException as e:
            if e.response.content.message == 'Rate Limit Exceeded':
                lifted_at = datetime.fromtimestamp(int(e.response.headers["ratelimit-reset"]))
                raise QueryParametersException(f"Bluesky rate limit exceeded. Try again after {lifted_at.strftime('%Y-%m-%d %H:%M:%S')}.")
            else:
                raise QueryParametersException(f"Bluesky login failed. {e.response.content.message}")

        # sanitize query
        sanitized_query = [q.strip() for q in query.get("query").replace("\n", ",").split(",") if q.strip()]

        # the dates need to make sense as a range to search within
        min_date, max_date = query.get("daterange")
        if min_date and max_date and min_date > max_date:
            raise QueryParametersException("The start date must be before the end date.")

        # Only check this if not already confirmed by the frontend
        posts_per_second = 55 # gathered from simply checking start/end times of logs
        if not query.get("frontend-confirm"):
            # Estimate is not returned; use max_posts as a rough estimate
            max_posts = query.get("max_posts", 100)
            expected_tweets = query.get("max_posts", 100) * len(sanitized_query)
            # Warn if process may take more than ~1 hours
            if expected_tweets > (posts_per_second * 3600):
                expected_time = timify_long(expected_tweets / posts_per_second)
                raise QueryNeedsExplicitConfirmationException(f"This query matches approximately {expected_tweets} tweets and may take {expected_time} to complete. Do you want to continue?")
            elif max_posts == 0 and not min_date:
                raise QueryNeedsExplicitConfirmationException(f"No maximum number of posts set! This query has no minimum date and thus may take a very, very long time to complete. Do you want to continue?")
            elif max_posts == 0:
                raise QueryNeedsExplicitConfirmationException(f"No maximum number of posts set! This query may take a long time to complete. Do you want to continue?")

        return {
            "max_posts": query.get("max_posts"),
            "query": ",".join(sanitized_query),
            "username": query.get("username"),
            "password": query.get("password"),
            "session_id": session_id,
            "min_date": min_date,
            "max_date": max_date,
        }

    def get_items(self, query):
        """
        Execute a query; get messages for given parameters

        Basically a wrapper around execute_queries() to call it with asyncio.

        :param dict query:  Query parameters, as part of the DataSet object
        :return list:  Posts, sorted by thread and post ID, in ascending order
        """
        if not query.get("session_id") and (not query.get("username") or not query.get("password")):
            return self.dataset.finish_with_error("Your Bluesky login credentials are no longer available in 4CAT; please re-create this datasource.")

        session_id = SearchBluesky.create_session_id(query.get("username"), query.get("password")) if not query.get("session_id") else query["session_id"]
        try:
            client = SearchBluesky.bsky_login(username=query.get("username"), password=query.get("password"), session_id=session_id)
        except (UnauthorizedError, RequestException, BadRequestError) as e:
            self.dataset.log(f"Bluesky login failed: {e}")
            return self.dataset.finish_with_error("Bluesky login failed; please re-create this datasource.")

        self.dataset.update_status(f"Collecting posts from Bluesky as {client.me.handle}")

        max_posts = query.get("max_posts", 100)
        limit = 100 if (max_posts > 100 or max_posts == 0) else max_posts

        # Handle reference mapping; user references use did instead of dynamic handle
        did_to_handle = {}

        query_parameters = {
            "limit": limit,
        }

        # Add start and end dates if provided
        if self.parameters.get("min_date"):
            query_parameters['since'] = datetime.fromtimestamp(self.parameters.get("min_date")).strftime('%Y-%m-%dT%H:%M:%SZ')
        if self.parameters.get("max_date"):
            query_parameters['until'] = datetime.fromtimestamp(self.parameters.get("max_date")).strftime('%Y-%m-%dT%H:%M:%SZ')

        queries = query.get("query").split(",")
        num_queries = len(queries)
        total_posts = 0
        i = 0
        last_query = None
        last_date = None
        while queries:
            query = queries.pop(0)
            if query == last_query:
                # Check if there are continued posts from the last query
                query_parameters['until'] = last_date.strftime('%Y-%m-%dT%H:%M:%SZ')
                self.dataset.log(f"Continuing query ({i} of {num_queries}): {query} from {last_date.strftime('%Y-%m-%dT%H:%M:%SZ')}")
            else:
                # New query
                query_post_ids = set()
                i += 1
                rank = 0
                last_query = query
                last_date = None
                self.dataset.update_status(f"Collecting query ({i} of {num_queries}): {query}")
                query_requests = 0

            query_parameters["q"] = query
            cursor = None  # Start with no cursor (first page)
            search_for_invalid_post = False
            invalid_post_counter = 0
            while True:
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while getting posts from the Bluesky API")
                # Query posts, including pagination (cursor for next page)
                tries = 0
                response = None
                while tries < 3:
                    query_parameters["cursor"] = cursor
                    try:
                        response = client.app.bsky.feed.search_posts(params=query_parameters)
                        break
                    except ModelError as e:
                        # Post validation error; one post is unable to be read
                        # Pattern: some invalid post raises error, we switch from higher limit (usually 100) to 1 in
                        # order to collect post by post, invalid post is identified again, we switch back to higher
                        # limit and continue as normal, at the "end" of a cursor/query life (~10k posts) a NetworkError
                        # is raised with detail refering to a server error 502 InternalServerError, we catch that and
                        # add the query back to the queue with a new "until" date to continue the query
                        # https://github.com/bluesky-social/atproto/issues/3446
                        if not search_for_invalid_post:
                            # New invalid post, search and skip
                            self.dataset.log(f"Invalid post detected; searching post by post: {e}")
                            search_for_invalid_post = True
                            # Currently we must search post by post to find the invalid post
                            query_parameters["limit"] = 1
                        else:
                            # Found invalid post, skip, reset counters
                            self.dataset.log(
                                f"Invalid post identified; skipping and continue with query as normal: {e}")
                            search_for_invalid_post = False
                            # Reset limit to normal
                            query_parameters["limit"] = limit
                            invalid_post_counter = 0
                            cursor = str(int(cursor) + 1) if cursor else None
                        # Re-query with new cursor & limit
                        continue

                    except InvokeTimeoutError as e:
                        # Timeout error, but can occur for odd queries with no results
                        self.dataset.log(f"Bluesky request error for query {query}: {e}")
                        time.sleep(1)
                        tries += 2
                        continue
                    except NetworkError as e:
                        # 502 InternalServerError: occurs if switch limits in a "set" (i.e. the vague 10k posts cursor limit), I seem to get this error around the 10k mark instead of just a missing cursor as normal
                        self.dataset.log(f"Bluesky network error for query {query}; retrying: {e}")
                        time.sleep(1 + (tries * 10))
                        queries.insert(0, query)
                        break

                if not response:
                    # Expected from NetworkError, but the query will have been added back to the queue
                    # If not, then there was a problem with the query
                    if len(queries) == 0:
                        self.dataset.update_status(f"Error collecting posts from Bluesky; see log for details", is_final=True)
                    if query not in queries:
                        # Query was not added back; there was an unexpected issue with the query itself
                        self.dataset.update_status(f"Error continuing {query} from Bluesky (see log for details); continuing to next query")
                    break

                query_requests += 1
                items = response['posts'] if hasattr(response, 'posts') else []

                if search_for_invalid_post:
                    invalid_post_counter += 1
                    if invalid_post_counter >= 100:
                        #  Max limit is 100; this should not occur, but we do not want to continue searching post by post indefinitely
                        self.dataset.log(f"Unable to identify invalid post; discontinuing search")
                        query_parameters["limit"] = limit
                        search_for_invalid_post = False
                        invalid_post_counter = 0

                    if not items:
                        # Sometimes no post is returned, but there still may be posts following
                        self.dataset.log(f"Query {query} w/ params {query_parameters} returned no posts: {response}")
                        # TODO: this is odd; no information is returned as to why that one item is not returned and no error is raised
                        cursor = str(int(cursor) + 1) if cursor else None
                        continue

                new_posts = 0
                # Handle the posts
                for item in items:
                    if 0 < max_posts <= rank:
                        break

                    if self.interrupted:
                        raise ProcessorInterruptedException("Interrupted while getting posts from the Bluesky API")

                    post = item.model_dump()
                    post_id = post["uri"]
                    # Queries use the indexed_at date for time-based pagination (as opposed to created_at); used to continue query if needed
                    last_date = SearchBluesky.bsky_convert_datetime_string(post.get("indexed_at"))
                    if post_id in query_post_ids:
                        # Skip duplicate posts
                        continue

                    new_posts += 1
                    query_post_ids.add(post_id)

                    # Add user handles from references
                    did_to_handle[post["author"]["did"]] = post["author"]["handle"]
                    # Mentions
                    mentions = []
                    if post["record"].get("facets"):
                        for facet in post["record"]["facets"]:
                            for feature in facet.get("features", {}):
                                if feature.get("did"):
                                    if feature["did"] in did_to_handle:
                                        mentions.append({"did": feature["did"], "handle": did_to_handle[feature["did"]]})
                                    else:
                                        handle = SearchBluesky.bsky_get_handle_from_did(client, feature["did"])
                                        if handle:
                                            if handle.lower() in self.handle_lookup_error_messages:
                                                self.dataset.log(f"Bluesky: user ({feature['did']}) {handle}")
                                            mentions.append({"did": feature["did"], "handle": handle})
                                            did_to_handle[feature["did"]] = handle
                                        else:
                                            mentions.append({"did": feature["did"], "handle": None})
                                            self.dataset.log(f"Bluesky: could not lookup the handle for {feature['did']}")
                    # Reply to
                    reply_to_handle = None
                    if post["record"].get("reply"):
                        reply_to_did = post["record"]["reply"]["parent"]["uri"].split("/")[2]
                        if reply_to_did in did_to_handle:
                            reply_to_handle = did_to_handle[reply_to_did]
                        else:
                            handle = SearchBluesky.bsky_get_handle_from_did(client, reply_to_did)
                            if handle:
                                if handle.lower() in self.handle_lookup_error_messages:
                                    self.dataset.log(f"Bluesky: user ({reply_to_did}) {handle}")
                                reply_to_handle = handle
                                did_to_handle[reply_to_did] = handle
                            else:
                                self.dataset.log(f"Bluesky: could not find handle for {reply_to_did}")


                    post.update({"4CAT_metadata": {
                        "collected_at": datetime.now().timestamp(),
                        "query": query,
                        "rank": rank,
                        "mentions": mentions,
                        "reply_to": reply_to_handle if reply_to_handle else None,
                    }})
                    rank += 1
                    yield post
                    total_posts += 1

                # Check if there is a cursor for the next page
                cursor = response['cursor']                
                if max_posts != 0 and rank % (max_posts // 10) == 0:
                    self.dataset.update_status(f"Progress query {query}: {rank} posts collected out of {max_posts}")
                    self.dataset.update_progress(total_posts / (max_posts * num_queries))
                elif max_posts == 0 and rank % 1000 == 0:
                    self.dataset.update_status(f"Progress query {query}: {rank} posts collected")

                if 0 < max_posts <= rank:
                    self.dataset.update_status(
                        f"Collected {rank} posts {'of ' + str(max_posts) if max_posts != 0 else ''} for query {query}")
                    break

                if not cursor:
                    if new_posts:
                        # Bluesky API seems to stop around 10000 posts and not return a cursor
                        # Re-query with the same query to get the next set of posts using last_date (set above)
                        self.dataset.log(f"Query {query}: {query_requests} requests")
                        queries.insert(0, query)
                    else:
                        # No new posts; if we have not hit the max_posts, but no new posts are being returned, then we are done
                        self.dataset.log(f"Query {query}: {query_requests} requests; no additional posts returned")

                    if rank:
                        self.dataset.update_status(f"Collected {rank} posts {'of ' + str(max_posts) if max_posts != 0 else ''} for query {query}")
                    break  # No more pages, stop the loop
                elif not items:
                    self.dataset.log(f"Query {query}: {query_requests} requests; no additional posts returned")
                    break

    @staticmethod
    def map_item(item):
        """
        Convert item object to 4CAT-ready data object

        :param dict item:  item to parse
        :return dict:  4CAT-compatible item object
        """
        unmapped_data = []

        # Add link to post; this is a Bluesky-specific URL and may not always be accurate
        link = SearchBluesky.get_bsky_link(item['author']['handle'], item['uri'].split('/')[-1])
        author_profile = f"https://bsky.app/profile/{item['author']['handle']}"

        created_at = SearchBluesky.bsky_convert_datetime_string(item["record"].get("created_at",item["record"].get("createdAt")))

        # Tags
        tags = set()
        links = set()
        mentions_did = set()
        has_poll = False
        if item["record"].get("facets"):
            for facet in item["record"].get("facets"):
                for feature in facet.get("features"):
                    if feature.get("tag"):
                        tags.add(feature.get("tag"))
                    elif feature.get("uri"):
                        links.add(feature.get("uri"))
                    elif feature.get("did"):
                        mentions_did.add(feature.get("did"))
                    elif feature.get("number"):
                        has_poll = True
                    else:
                        unmapped_data.append({"loc": "record.facets.features", "obj": feature})
                if "features" not in facet:
                    unmapped_data.append({"loc": "record.facets", "obj": facet})

        # Embeds are in both the item and the record; so far these always contain same item
        embeded_links = set()
        embeded_images = set()
        image_references = set()
        quoted_link = None
        quoted_user = None
        quoted_ref = None
        possible_embeds = [item.get("embed", {}), item["record"].get("embed", {})]
        while possible_embeds:
            embed = possible_embeds.pop(0)
            if not embed:
                continue

            py_type = embed.pop("py_type") if "py_type" in embed else (embed.pop("$type") if "$type" in embed else None)
            if py_type in ["app.bsky.embed.recordWithMedia#view", "app.bsky.embed.recordWithMedia"]:
                # contains post plus additional media
                for key, media_ob in embed.items():
                    possible_embeds.append(media_ob)

            elif "images" in embed: # py_type in ["app.bsky.embed.images#view", "app.bsky.embed.images", "app.bsky.embed.images#main"]
                for img_ob in embed["images"]:
                    img_link = img_ob.get("fullsize", img_ob.get("thumb"))
                    if img_link:
                        embeded_images.add(img_link)
                    elif img_ob.get("image", {}).get("ref", {}).get("link", img_ob.get("image", {}).get("ref", {}).get("$link")):
                        # ob.get("image").get("ref").get("link") will have a reference that could be linked via API
                        # BUT ref has already been obtained in other embeds...
                        image_references.add(img_ob.get("image", {}).get("ref", {}).get("link", img_ob.get("image", {}).get("ref", {}).get("$link")))
                    else:
                        unmapped_data.append({"loc": "embed.images", "obj": img_ob})
            elif py_type in ["app.bsky.embed.video#view", "app.bsky.embed.video"]:
                # Does not appear to be direct video links, just thumbnail (Bluesky API may be able to get more)
                if embed.get("thumbnail"):
                    embeded_images.add(embed.get("thumbnail"))
                elif embed.get("video", {}).get("ref", {}).get("link"):
                    image_references.add(embed.get("video", {}).get("ref", {}).get("link"))
                else:
                    # No thumb for video
                    pass
            elif "record" in embed: # py_type in ["app.bsky.embed.record#view", "app.bsky.embed.record"]
                # Quoted post
                # Note: these may also contain images that would be seen, but are not part of the original post
                if embed["record"].get("author", embed["record"].get("creator")):
                    if "handle" not in embed["record"].get("author", embed["record"].get("creator")):
                        # User may not be able to see original post
                        if "app.bsky.feed.defs#blockedAuthor" == embed["record"].get("author", embed["record"].get("creator"))["py_type"]:
                            quoted_link = "VIEWER BLOCKED BY AUTHOR"
                        else:
                            # New unknown
                            unmapped_data.append({"loc": "embed.record.author", "obj": embed["record"].get("author", embed["record"].get("creator"))})
                    else:
                        # author seems to be a quoted post while creator a quoted "list"
                        quoted_user = embed["record"].get("author", embed["record"].get("creator"))["handle"]
                        quoted_link = SearchBluesky.get_bsky_link(quoted_user, embed['record']['uri'].split('/')[-1])
                elif embed["record"].get("not_found"):
                    quoted_link = "DELETED"
                    # We do have the DID, but this information is not normally displayed
                    # quoted_user = embed["record"]['uri'].split("/")[2]
                elif embed["record"].get("detached"):
                    quoted_link = "REMOVED BY AUTHOR"
                else:
                    quoted_ref = embed["record"]['uri']
            elif "external" in embed: # py_type in ["app.bsky.embed.external#view", "app.bsky.embed.external"]
                if embed["external"].get("uri"):
                    embeded_links.add(embed["external"].get("uri"))
                if embed["external"].get("thumb"):
                    if isinstance(embed["external"]["thumb"], str):
                        embeded_images.add(embed["external"]["thumb"])
                    else:
                        image_references.add(embed["external"]["thumb"].get("ref", {}).get("link", ""))
                else:
                    # No thumb for link
                    pass
            else:
                unmapped_data.append({"loc": f"embed.{py_type}",
                                      "obj": embed})

        # Replies allowed
        # https://docs.bsky.app/docs/tutorials/thread-gates
        # threadgate object does not appear to differentiate between the types of replies allowed
        replies_allowed = True if not item["threadgate"] else False

        # Labels (content moderation)
        labels = set() if not item["labels"] else set([label.get("val") for label in item["labels"]])
        if item["record"].get("labels"):
            labels = labels | set([label.get("val") for label in item["record"]["labels"].get("values",[])])

        # Language
        languages = "N/A" if not item["record"].get("langs") else ",".join(item["record"].get("langs"))

        # Missing references
        if any([ref for ref in image_references if ref not in "".join(embeded_images)]):
            unmapped_data.append({"loc": "missing_image_refs", "obj": [ref for ref in image_references if ref not in "".join(embeded_images)]})
        if quoted_ref:
            if not quoted_link or (quoted_link not in ["DELETED", "REMOVED BY AUTHOR", "VIEWER BLOCKED BY AUTHOR"] and quoted_ref.split('/')[-1] not in quoted_link):
                unmapped_data.append({"loc": "missing_quote_ref", "obj": quoted_ref})

        # Reference Posts (expanded to include handles during collection)
        # None: handles may change; true DID from original object stored item["record"]["facets"]["features"] w/ "did"
        # Mentions
        mentions = [(mention.get("handle") if (mention.get("handle") and mention["handle"].lower() not in SearchBluesky.handle_lookup_error_messages) else mention.get("did")) for mention in item.get("4CAT_metadata", {}).get("mentions", [])]
        # Reply to
        replied_to_post = None
        replied_to_user = None
        if item["record"].get("reply"):
            if item["4CAT_metadata"]["reply_to"] and item["4CAT_metadata"]["reply_to"].lower() not in SearchBluesky.handle_lookup_error_messages:
                replied_to_user = item["4CAT_metadata"]["reply_to"]
            else:
                # Use DID, though this will not create a working link
                replied_to_user = item["record"]["reply"]["parent"]["uri"].split("/")[2]
            replied_to_post = SearchBluesky.get_bsky_link(replied_to_user, item["record"]["reply"]["parent"]["uri"].split("/")[-1])

        # These refer to slices of the text, but are also contained in the text or as an embed. If they are NOT also in the text and/or embed fields, then they are NOT displayed in bsky.app UI and thus only metadata
        # if item["record"].get("entities"):
        #     unmapped_data.append({"loc": "record.entities", "obj": item["record"]["entities"]})

        # Author tags, not hashtags, not seen, very rarely used
        # if item["record"].get("tags"):
        #     unmapped_data.append({"loc": "record.tags", "obj": item["record"].get("tags")})

        if unmapped_data:
            # TODO: Use MappedItem message; currently it is not called...
            config.with_db()
            config.db.log.warning(f"Bluesky new mappings ({item['uri']}): {unmapped_data}")

        return MappedItem({
            "collected_at": datetime.fromtimestamp(item["4CAT_metadata"]["collected_at"]).isoformat(),
            "query": item["4CAT_metadata"]["query"],
            "rank": item["4CAT_metadata"]["rank"],
            "id": item["uri"],
            "thread_id": item["record"]["reply"]["root"]["uri"] if item["record"].get("reply") else item["uri"],
            "created_at": created_at.isoformat(),
            "author": item["author"]["handle"],
            "author_id": item["author"]["did"],
            "body": item["record"]["text"],
            "link": link,
            "tags": ",".join(tags),
            "like_count": item["like_count"],
            "quote_count": item["quote_count"],
            "reply_count": item["reply_count"],
            "repost_count": item["repost_count"],
            "quoted_post": quoted_link if quoted_link else "",
            "quoted_user": quoted_user if quoted_user else "",
            "replied_to_post": replied_to_post if replied_to_post else "",
            "replied_to_user": replied_to_user if replied_to_user else "",
            "replies_allowed": replies_allowed,
            "mentions": ",".join(mentions),
            "links": ",".join(embeded_links | links),
            "images": ",".join(embeded_images),
            "labels": ",".join(labels),
            "has_poll": has_poll,
            "languages": languages,

            "author_display_name": item["author"]["display_name"],
            "author_profile": author_profile,
            "author_avatar": item["author"]["avatar"],
            "author_created_at": SearchBluesky.bsky_convert_datetime_string(item["author"]["created_at"], mode="iso_string", raise_error=False),

            "timestamp": int(created_at.timestamp()),
        }, message=f"Bluesky new mappings: {unmapped_data}")

    @staticmethod
    def bsky_convert_datetime_string(datetime_string, mode="datetime", raise_error=True):
        """
        Bluesky datetime string to datetime object.

        Mode "datetime" returns a datetime object, while "iso_string" returns an ISO formatted string.

        :param str datetime_string:  The datetime string to convert
        :param str mode:  The mode to return the datetime object in [datetime, iso_string]
        :param bool raise_error:  Raise error if unable to parse else return datetime_string
        :return datetime/str:  The converted datetime object
        """
        try:
            datetime_object = parser.isoparse(datetime_string)
        except ValueError as e:
            if raise_error:
                raise e
            return datetime_string
        
        if mode == "datetime":
            return datetime_object
        elif mode == "iso_string":
            return datetime_object.isoformat()


    @staticmethod
    def get_bsky_link(handle, post_id):
        """
        Get link to Bluesky post
        """
        return f"https://bsky.app/profile/{handle}/post/{post_id}"

    @staticmethod
    def bsky_get_handle_from_did(client, did):
        """
        Get handle from DID
        """
        tries = 0
        while True:
            try:
                user_profile = client.app.bsky.actor.get_profile({"actor": did})
                if user_profile:
                    return user_profile.handle
                else:
                    return None
            except (NetworkError, InvokeTimeoutError) as e:
                # Network error; try again
                tries += 1
                time.sleep(1)
                if tries > 3:
                    return None
                continue
            except BadRequestError as e:
                if e.response.content.message:
                    return e.response.content.message
                return None

    @staticmethod
    def bsky_login(username, password, session_id):
        """
        Login to Bluesky

        :param str username:  Username for Bluesky
        :param str password:  Password for Bluesky
        :param str session_id:  Session ID to use for login
        :return Client:  Client object with login credentials
        """
        if not session_id:
            session_id = SearchBluesky.create_session_id(username, password)
        elif (not username or not password) and not session_id:
            raise ValueError("Must provide both username and password or else session_id.")

        session_path = Path(config.get('PATH_ROOT')).joinpath(config.get('PATH_SESSIONS'), "bsky_" + session_id + ".session")

        def on_session_change(event: SessionEvent, session: Session) -> None:
            """
            Save session to file; atproto session change event handler should keep the session up to date

            https://atproto.blue/en/latest/atproto_client/auth.html
            """
            print('Session changed:', event, repr(session))
            if event in (SessionEvent.CREATE, SessionEvent.REFRESH):
                print('Saving changed session')
                with session_path.open("w") as session_file:
                    session_file.write(session.export())

        client = Client()
        client.on_session_change(on_session_change)
        if session_path.exists():
            with session_path.open() as session_file:
                session_string = session_file.read()
                try:
                    client.login(session_string=session_string)
                except BadRequestError as e:
                    if e.response.content.message == 'Token has expired':
                        # Token has expired; try to refresh
                        if username and password:
                            client.login(login=username, password=password)
                        else:
                            raise ValueError("Session token has expired; please re-login with username and password.")
        else:
            # Were not able to log in via session string; login with username and password
            client.login(login=username, password=password)
        return client

    @staticmethod
    def create_session_id(username, password):
        """
        Generate a filename for the session file

        This is a combination of username and password, but hashed
        so that one cannot actually derive someone's information.

        :param str username:  Username for Bluesky
        :param str password:  Password for Bluesky
        :return str: A hash value derived from the input
        """
        hash_base = username.strip() + str(password).strip()
        return hashlib.blake2b(hash_base.encode("ascii")).hexdigest()