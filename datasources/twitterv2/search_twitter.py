"""
Twitter keyword search via the Twitter API v2
"""
import requests
import datetime
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
        amount = convert_to_int(self.parameters.get("amount"), 10)

        params = {
            "query": self.parameters.get("query", ""),
            "expansions": ",".join(expansions),
            "tweet.fields": ",".join(tweet_fields),
            "user.fields": ",".join(user_fields),
            "poll.fields": ",".join(poll_fields),
            "place.fields": ",".join(place_fields),
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
                    self.dataset.update_status("Got %s, waiting %i seconds before retrying" % (e.__name__, wait_time))
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

            # this usually means the query is too long or otherwise contains
            # a syntax error
            elif api_response.status_code == 400:
                msg = "Response 400 from the Twitter API;"
                try:
                    api_response = api_response.json()
                    msg += api_response.get("title", "")
                    if "detail" in api_response:
                        msg += api_response.get("detail", "")
                except (json.JSONDecodeError, TypeError):
                    msg += "Some of your parameters (e.g. date range) may be invalid."

                self.dataset.update_status(msg, is_final=True)
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

            # only the user ID is given per tweet - usernames etc are returned
            # separately, presumably to save space when there are many tweets
            # by the same author. Here we add the relevant data per tweet, so
            # we don't need anything else than the tweet object later
            users = {user["id"]: user for user in api_response.get("includes", {}).get("users", {})}
            for tweet in api_response.get("data", []):
                if amount >= 0 and tweets >= amount:
                    break

                tweet["author_username"] = users.get(tweet["author_id"])["username"]
                tweet["author_fullname"] = users.get(tweet["author_id"])["name"]
                tweet["author_verified"] = users.get(tweet["author_id"])["verified"]

                tweets += 1
                yield tweet

            # paginate
            if (amount <= 0 or tweets < amount) and api_response.get("meta") and "next_token" in api_response["meta"]:
                params["next_token"] = api_response["meta"]["next_token"]
            else:
                break

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
        Validate input for a dataset query on the 4chan data source.

        Will raise a QueryParametersException if invalid parameters are
        encountered. Mutually exclusive parameters may also be sanitised by
        ignoring either of the mutually exclusive options.

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

        # both dates need to be set, or none
        if query.get("min_date", None) and not query.get("max_date", None):
            raise QueryParametersException(
                "When setting a date range, please provide both an upper and lower limit.")

        # the dates need to make sense as a range to search within
        if query.get("min_date", None) and query.get("max_date", None):
            try:
                before = int(query.get("max_date", ""))
                after = int(query.get("min_date", ""))
            except ValueError:
                raise QueryParametersException("Please provide valid dates for the date range.")

            if before < after:
                raise QueryParametersException(
                    "Please provide a valid date range where the start is before the end of the range.")

            query["min_date"] = after
            query["max_date"] = before

        is_placeholder = re.compile("_proxy$")
        filtered_query = {}
        for field in query:
            if not is_placeholder.search(field):
                filtered_query[field] = query[field]

        # if we made it this far, the query can be executed
        return {
            "query": query.get("query"),
            "api_bearer_token": query.get("api_bearer_token"),
            "min_date": query.get("min_date"),
            "max_date": query.get("max_date"),
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
            "timestamp": int(datetime.datetime.strptime(tweet["created_at"], "%Y-%m-%dT%H:%M:%S.000Z").timestamp()),
            "subject": "",
            "body": tweet["text"],
            "author": tweet["author_username"],
            "author_fullname": tweet["author_fullname"],
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
            "mentions": ",".join([tag["username"] for tag in tweet.get("entities", {}).get("mentions", [])]),
            "reply_to": "".join(
                [mention["username"] for mention in tweet.get("entities", {}).get("mentions", [])[:1]]) if any(
                [ref["type"] == "replied_to" for ref in tweet.get("referenced_tweets", [])]) else ""
        }