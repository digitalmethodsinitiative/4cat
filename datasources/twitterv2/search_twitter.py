"""
Twitter keyword search via the Twitter API v2
"""
import requests
import datetime
import copy
import time
import json
import re

from backend.abstract.search import Search
from backend.lib.exceptions import QueryParametersException, ProcessorInterruptedException
from backend.lib.helpers import convert_to_int


class SearchWithTwitterAPIv2(Search):
    """
    Get Tweets via the Twitter API

    This only allows for historical search - use f.ex. TCAT for more advanced
    queries.
    """
    type = "twitterv2-search"  # job ID
    extension = "ndjson"

    previous_request = 0

    def get_posts_simple(self, query):
        """
        Use the Twitter v2 API historical search to get tweets

        :param query:
        :return:
        """
        # this is pretty sensitive so delete it immediately after storing in
        # memory
        bearer_token = self.parameters.get("api_bearer_token")
        self.dataset.delete_parameter("bearer_token")
        auth = {"Authorization": "Bearer %s" % bearer_token}

        endpoint = "https://api.twitter.com/2/tweets/search/all"

        # these are all expansions and fields available at the time of writing
        # since it does not cost anything extra in terms of rate limiting, go
        # for as much data per tweet as possible...
        tweet_fields = ("attachments", "author_id", "context_annotations", "conversation_id", "created_at", "entities", "geo", "id", "in_reply_to_user_id", "lang", "public_metrics", "possibly_sensitive", "referenced_tweets", "reply_settings", "source", "text", "withheld")
        user_fields = ("created_at", "description", "entities", "id", "location", "name", "pinned_tweet_id", "profile_image_url", "protected", "public_metrics", "url", "username", "verified", "withheld")
        place_fields = ("contained_within", "country", "country_code", "full_name", "geo", "id", "name", "place_type")
        poll_fields = ("duration_minutes", "end_datetime", "id", "options", "voting_status")
        expansions = ("attachments.poll_ids", "attachments.media_keys", "author_id", "entities.mentions.username", "geo.place_id", "in_reply_to_user_id", "referenced_tweets.id", "referenced_tweets.id.author_id")
        media_fields = ("duration_ms", "height", "media_key", "non_public_metrics", "organic_metrics", "preview_image_url", "promoted_metrics", "public_metrics", "type", "url", "width")
        amount = convert_to_int(self.parameters.get("amount"), 10)

        params = {
            "query": self.parameters.get("query", ""),
            "expansions": ",".join(expansions),
            "tweet.fields": ",".join(tweet_fields),
            "user.fields": ",".join(user_fields),
            "poll.fields": ",".join(poll_fields),
            "place.fields": ",".join(place_fields),
            "media.fields": ",".join(media_fields),
            "max_results": max(10, min(amount, 500)) if amount > 0 else 500,  # 500 = upper limit, 10 = lower
        }

        if self.parameters.get("min_date"):
            params["start_time"] = datetime.datetime.fromtimestamp(self.parameters["min_date"]).strftime("%Y-%m-%dT%H:%M:%SZ")

        if self.parameters.get("max_date"):
            params["end_time"] = datetime.datetime.fromtimestamp(self.parameters["max_date"]).strftime("%Y-%m-%dT%H:%M:%SZ")

        tweets = 0
        self.dataset.log("Search parameters: %s" % repr(params))
        while True:
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while getting tweets from the Twitter API")

            # there is a limit of one request per second, so stay on the safe side of this
            while self.previous_request == int(time.time()):
                time.sleep(0.1)
            time.sleep(0.05)
            self.previous_request = int(time.time())

            # now send the request, allowing for at least 5 replies if the connection seems unstable
            retries = 5
            api_response = None
            while retries > 0:
                try:
                    api_response = requests.get(endpoint, headers=auth, params=params)
                    break
                except (ConnectionError, requests.exceptions.RequestException) as e:
                    retries -= 1
                    wait_time = (5 - retries) * 10
                    self.dataset.update_status("Got %s, waiting %i seconds before retrying" % (str(e), wait_time))
                    time.sleep(wait_time)

            # rate limited - the limit at time of writing is 300 reqs per 15
            # minutes
            # usually you don't hit this when requesting batches of 500 at
            # 1/second
            if api_response.status_code == 429:
                resume_at = convert_to_int(api_response.headers["x-rate-limit-reset"]) + 1
                resume_at_str = datetime.datetime.fromtimestamp(int(resume_at)).strftime("%c")
                self.dataset.update_status("Hit Twitter rate limit - waiting until %s to continue." % resume_at_str)
                while time.time() <= resume_at:
                    time.sleep(0.5)
                continue

            # sometimes twitter says '503 service unavailable' for unclear
            # reasons - in that case just wait a while and try again
            elif api_response.status_code in (502, 503, 504):
                resume_at = time.time() + 60
                resume_at_str = datetime.datetime.fromtimestamp(int(resume_at)).strftime("%c")
                self.dataset.update_status("Twitter unavailable (status %i) - waiting until %s to continue." % (api_response.status_code, resume_at_str))
                while time.time() <= resume_at:
                    time.sleep(0.5)
                continue


            # this usually means the query is too long or otherwise contains
            # a syntax error
            elif api_response.status_code == 400:
                msg = "Response %i from the Twitter API; " % api_response.status_code
                try:
                    api_response = api_response.json()
                    msg += api_response.get("title", "")
                    if "detail" in api_response:
                        msg += ": " + api_response.get("detail", "")
                except (json.JSONDecodeError, TypeError):
                    msg += "Some of your parameters (e.g. date range) may be invalid."

                self.dataset.update_status(msg, is_final=True)
                return

            # invalid API key
            elif api_response.status_code == 401:
                self.dataset.update_status("Invalid API key - could not connect to Twitter API", is_final=True)
                return

            # haven't seen one yet, but they probably exist
            elif api_response.status_code != 200:
                self.dataset.update_status("Unexpected HTTP status %i. Halting tweet collection." % api_response.status_code, is_final=True)
                self.log.warning("Twitter API v2 responded with status code %i. Response body: %s" % (api_response.status_code, api_response.text))
                return

            elif not api_response:
                self.dataset.update_status("Could not connect to Twitter. Cancelling.", is_final=True)
                return

            api_response = api_response.json()

            # The API response contains tweets (of course) and 'includes',
            # objects that can be referenced in tweets. Later we will splice
            # this data into the tweets themselves to make them easier to
            # process. So extract them first...
            included_users = api_response.get("includes", {}).get("users", {})
            included_media = api_response.get("includes", {}).get("media", {})
            included_polls = api_response.get("includes", {}).get("polls", {})
            included_tweets = api_response.get("includes", {}).get("tweets", {})
            included_places = api_response.get("includes", {}).get("places", {})

            for tweet in api_response.get("data", []):
                if 0 < amount <= tweets:
                    break

                # splice referenced data back in
                # we use copy.deepcopy here because else we run into a
                # pass-by-reference quagmire
                tweet = self.enrich_tweet(tweet, included_users, included_media, included_polls, included_places, copy.deepcopy(included_tweets))

                tweets += 1
                if tweets % 500 == 0:
                    self.dataset.update_status("Received %i tweets from Twitter API" % tweets)

                yield tweet

            # paginate
            if (amount <= 0 or tweets < amount) and api_response.get("meta") and "next_token" in api_response["meta"]:
                params["next_token"] = api_response["meta"]["next_token"]
            else:
                break

    def enrich_tweet(self, tweet, users, media, polls, places, referenced_tweets):
        """
        Enrich tweet with user and attachment metadata

        Twitter API returns some of the tweet's metadata separately, as
        'includes' that can be cross-referenced with a user ID or media key.
        This makes sense to conserve bandwidth, but also means tweets are not
        'standalone' objects as originally returned.

        However, for processing, making them standalone greatly reduces
        complexity, as we can simply read one single tweet object and process
        that data without worrying about having to get other data from
        elsewhere. So this method takes the metadata and the original tweet,
        splices the metadata into it where appropriate, and returns the
        enriched object.

        /!\ This is not an efficient way to store things /!\ but it is more
        convenient.

        :param dict tweet:  The tweet object
        :param list users:  User metadata, as a list of user objects
        :param list media:  Media metadata, as a list of media objects
        :param list polls:  Poll metadata, as a list of poll objects
        :param list places:  Place metadata, as a list of place objects
        :param list referenced_tweets:  Tweets referenced in the tweet, as a
        list of tweet objects. These will be enriched in turn.

        :return dict:  Enriched tweet object
        """
        # first create temporary mappings so we can easily find the relevant
        # object later
        users_by_id = {user["id"]: user for user in users}
        users_by_name = {user["username"]: user for user in users}
        media_by_key = {item["media_key"]: item for item in media}
        polls_by_id = {poll["id"]: poll for poll in polls}
        places_by_id = {place["id"]: place for place in places}
        tweets_by_id = {ref["id"]: ref.copy() for ref in referenced_tweets}

        # add tweet author metadata
        tweet["author_user"] = users_by_id.get(tweet["author_id"])

        # add place to geo metadata
        # referenced_tweets also contain place_id, but these places may not included in the place objects
        if 'place_id' in tweet.get('geo', {}) and tweet.get("geo").get("place_id") in places_by_id.keys():
            tweet["geo"]["place"] = places_by_id[tweet.get("geo").get("place_id")]

        # add user metadata for mentioned users
        for index, mention in enumerate(tweet.get("entities", {}).get("mentions", [])):
            tweet["entities"]["mentions"][index] = {**tweet["entities"]["mentions"][index], **users_by_name.get(mention["username"], {})}

        # add poll metadata
        for index, poll_id in enumerate(tweet.get("attachments", {}).get("poll_ids", [])):
            tweet["attachments"]["poll_ids"][index] = polls_by_id[poll_id] if poll_id in polls_by_id else poll_id

        # add media metadata - seems to be just the media type, the media URL
        # etc is stored in the 'entities' attribute instead
        for index, media_key in enumerate(tweet.get("attachments", {}).get("media_keys", [])):
            tweet["attachments"]["media_keys"][index] = media_by_key[media_key] if media_key in media_by_key else media_key

        # replied-to user metadata
        if "in_reply_to_user_id" in tweet:
            tweet["in_reply_to_user"] = users_by_id[tweet["in_reply_to_user_id"]] if tweet["in_reply_to_user_id"] in users_by_id else {}

        # enrich referenced tweets. Even though there should be no recursion -
        # since tweets cannot be edited - we do not recursively enrich
        # referenced tweets (should we?)
        for index, reference in enumerate(tweet.get("referenced_tweets", [])):
            if reference["id"] in tweets_by_id:
                tweet["referenced_tweets"][index] = {**reference, **self.enrich_tweet(tweets_by_id[reference["id"]], users, media, polls, places, [])}

        return tweet

    def get_search_mode(self, query):
        """
        Twitter searches are always simple

        :return str:
        """
        return "simple"

    def get_posts_complex(self, query):
        """
        Complex post fetching is not used by the Twitter datasource

        :param query:
        :return:
        """
        pass

    def fetch_posts(self, post_ids, where=None, replacements=None):
        """
        Posts are fetched via TCAT for this datasource
        :param post_ids:
        :param where:
        :param replacements:
        :return:
        """
        pass

    def fetch_threads(self, thread_ids):
        """
        Thread filtering is not a toggle for Twitter datasets

        :param thread_ids:
        :return:
        """
        pass

    def get_thread_sizes(self, thread_ids, min_length):
        """
        Thread filtering is not a toggle for Twitter datasets

        :param tuple thread_ids:
        :param int min_length:
        results
        :return dict:
        """
        pass

    @staticmethod
    def validate_query(query, request, user):
        """
        Validate input for a dataset query on the Twitter data source.

        Will raise a QueryParametersException if invalid parameters are
        encountered. Parameters are additionally sanitised.

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param User user:  User object of user who has submitted the query
        :return dict:  Safe query parameters
        """

        # this is the bare minimum, else we can't narrow down the full data set
        if not query.get("query", None):
            raise QueryParametersException("Please provide a query.")

        if not query.get("api_bearer_token", None):
            raise QueryParametersException("Please provide a valid bearer token.")

        if len(query.get("query")) > 1024:
            raise QueryParametersException("Twitter API queries cannot be longer than 1024 characters.")

        # the dates need to make sense as a range to search within
        # but, on Twitter, you can also specify before *or* after only
        before = None
        after = None
        if query.get("min_date", None):
            try:
                after = int(query.get("min_date", ""))
                query["min_date"] = after
            except ValueError:
                raise QueryParametersException("Please provide valid dates for the date range.")

        if query.get("max_date", None):
            try:
                before = int(query.get("max_date", ""))
                query["max_date"] = after
            except ValueError:
                raise QueryParametersException("Please provide valid dates for the date range.")

        if before and after and before < after:
            raise QueryParametersException("Date range must start before it ends")

        is_placeholder = re.compile("_proxy$")
        filtered_query = {}
        for field in query:
            if not is_placeholder.search(field):
                filtered_query[field] = query[field]

        # if we made it this far, the query can be executed
        return {
            "query": query.get("query"),
            "api_bearer_token": query.get("api_bearer_token"),
            "min_date": after,
            "max_date": before,
            "amount": max(0, convert_to_int(query.get("amount"), 10))
        }

    @staticmethod
    def map_item(tweet):
        """
        Map a nested Tweet object to a flat dictionary

        Tweet objects are quite rich but 4CAT expects flat dictionaries per
        item in many cases. Since it would be a shame to not store the data
        retrieved from Twitter that cannot be stored in a flat file, we store
        the full objects and only map them to a flat dictionary when needed.
        This has a speed (and disk space) penalty, but makes sure we don't
        throw away valuable data and allows for later changes that e.g. store
        the tweets more efficiently as a MongoDB collection.

        :param tweet:  Tweet object as originally returned by the Twitter API
        :return dict:  Dictionary in the format expected by 4CAT
        """
        return {
            "id": tweet["id"],
            "thread_id": tweet.get("conversation_id", tweet["id"]),
            "timestamp": tweet["created_at"].replace("T", " ").replace(".000Z", ""),
            "unix_timestamp": int(datetime.datetime.strptime(tweet["created_at"], "%Y-%m-%dT%H:%M:%S.000Z").timestamp()),
            "subject": "",
            "body": tweet["text"],
            "author": tweet["author_user"]["username"],
            "author_fullname": tweet["author_user"]["name"],
            "author_id": tweet["author_id"],
            "source": tweet.get("source"),
            "language_guess": tweet.get("lang"),
            "possibly_sensitive": "yes" if tweet.get("possibly_sensitive") else "no",
            **tweet["public_metrics"],
            "is_retweet": "yes" if any(
                [ref["type"] == "retweeted" for ref in tweet.get("referenced_tweets", [])]) else "no",
            "is_quote_tweet": "yes" if any(
                [ref["type"] == "quoted" for ref in tweet.get("referenced_tweets", [])]) else "no",
            "is_reply": "yes" if any(
                [ref["type"] == "replied_to" for ref in tweet.get("referenced_tweets", [])]) else "no",
            "hashtags": ",".join([tag["tag"] for tag in tweet.get("entities", {}).get("hashtags", [])]),
            "urls": ",".join([tag["expanded_url"] for tag in tweet.get("entities", {}).get("urls", [])]),
            "images": ",".join(item["url"] for item in tweet.get("attachments", {}).get("media_keys", []) if type(item) is dict and item["type"] == "photo"),
            "mentions": ",".join([tag["username"] for tag in tweet.get("entities", {}).get("mentions", [])]),
            "reply_to": "".join(
                [mention["username"] for mention in tweet.get("entities", {}).get("mentions", [])[:1]]) if any(
                [ref["type"] == "replied_to" for ref in tweet.get("referenced_tweets", [])]) else ""
        }
