"""
Twitter keyword search via collections on a DMI server
"""
import requests
import datetime
import copy
import json

from backend.abstract.search import Search
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException, QueryNeedsExplicitConfirmationException
from common.lib.helpers import convert_to_int, UserInput, timify_long
import common.config_manager as config
from datasources.twitterv2.search_twitter import SearchWithTwitterAPIv2


class SearchWithTwitterDMI(Search):
    """
    Get Tweets from DMI's Twitter collector
    """
    type = "twitter_dmi_stream-search"  # job ID
    title = "Twitter DMI Collections"
    extension = "ndjson"
    is_local = False    # Whether this datasource is locally scraped
    is_static = False   # Whether this datasource is still updated

    previous_request = 0
    flawless = True

    references = [
        "[DMI Twitter Collection server documentation]()",
        "[Twitter Streaming APIs documentation]()",
    ]

    config = {
        "twitter_dmi-search.server": {
            "type": UserInput.OPTION_TEXT,
            "help": "URL for DMI Twitter Collection Server",
            "tooltip": "",
            "default": "",
        }
    }

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        """
        :param parent_dataset:  Should always be None
        :param user:  User to provide options for
        :return dict:  Data source options
        """
        intro_text = ("Query ongoing or previously collected tweets from a DMI Tweet Collection server.")

        options = {
            "intro-1": {
                "type": UserInput.OPTION_INFO,
                "help": intro_text
            },
            "query": {
                "type": UserInput.OPTION_TEXT_LARGE,
                "help": "Query"
            },
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "help": "Tweets to retrieve",
                "tooltip": "0 = unlimited (be careful!)",
                "min": 0,
                "default": 10
            },
            "divider-2": {
                "type": UserInput.OPTION_DIVIDER
            },
            "daterange-info": {
                "type": UserInput.OPTION_INFO,
                "help": "By default, Twitter returns tweets up til 30 days ago. If you want to go back further, you "
                        "need to explicitly set a date range."
            },
            "daterange": {
                "type": UserInput.OPTION_DATERANGE,
                "help": "Date range"
            },
        }

        return options

    def collect_twitter_rules(self):
        """
        Collect the rule sets used to filter the tweets stored on the DMI server
        """
        dmi_twitter_server = config.get("twitter_dmi-search.server", False)
        if not dmi_twitter_server:
            return False
        # TODO: there is no API to directly talk to Mongo alone...
        return False


    def get_items(self, query):
        """
        :param query:
        :return:
        """
        dmi_twitter_server = config.get("twitter_dmi-search.server", False)
        if not dmi_twitter_server:
            self.dataset.update_status("A DMI Twitter Collection server has not been configured.", is_final=True)
            return
        dmi_twitter_server = dmi_twitter_server.rstrip("/") + "/api/tweets/search/"  # Other collections may exist; TODO this will need to be abstracted further

        # Collect parameters
        query_string = json.dumps(self.parameters.get("query"))
        min_date = self.parameters.get("min_date", False)
        max_date = self.parameters.get("max_date", False)
        amount = self.parameters.get("amount")

        query = {"query_string": {"query": query_string, "default_field": "text"}}
        if min_date or max_date:
            query.update({
                "range": {
                    "created_at": {
                        "gte": datetime.datetime.fromtimestamp(min_date).strftime("%Y-%m-%dT%H:%M:%SZ") if min_date else "",
                        "lt": datetime.datetime.fromtimestamp(max_date).strftime("%Y-%m-%dT%H:%M:%SZ") if max_date else ""
                    }
                }
            })

        request_data = {
            "query": json.dumps(query),
            "mongo_index": "data.id",
            "sort": json.dumps({"created_at": {"order": "desc"}}),  # This forces returning most recent tweets first
            "object_id_bool": "no",  # "yes" would use the Mongo DB `_id` which Twitter does not use
        }

        cursor = False
        collected_tweets = 0
        keep_searching = True
        while keep_searching:
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while getting tweets from the Twitter API")

            # Add a curser if it exists
            if cursor:
                request_data.update({"cursor": cursor})

            response = requests.post(dmi_twitter_server, data=request_data)

            if response.status_code == 400:
                self.dataset.update_status(f"Query appears to contain an error({response.status_code}): {response.reason}", is_final=True)
                return
            elif response.status_code != 200:
                # 500 something is wrong with the server (possibly the query returned something unexpected)
                self.dataset.update_status(f"DMI server mad ({response.status_code}): {response.reason}", is_final=True)
                return

            if len(response.json()["results"]) <= 0:
                self.dataset.update("No additional results returned")
                keep_searching = False

            for tweet in response.json()["results"]:
                # Convert DMI tweet to 4CAT structure
                updated_tweet = SearchWithTwitterDMI.dmi_tweet_to_4cat_map(tweet)

                yield updated_tweet
                collected_tweets += 1

                if amount != 0 and collected_tweets >= amount:
                    keep_searching = False
                    break

            self.dataset.update_status(f"Received {collected_tweets} of {amount} tweets from the Twitter API" )
            if amount > 0:
                self.dataset.update_progress(collected_tweets / amount)

            # Check if there are more tweets
            cursor = response.json().get("cursor", False)
            if not cursor:
                self.dataset.update_status(f"Collected {collected_tweets} tweets.")
                keep_searching = False
                break

    @staticmethod
    def dmi_tweet_to_4cat_map(tweet):
        """
        DMI collected tweets store some additional data and are not identical to 4CAT collected tweets (though
        structurally they are identical when retrieved from Twitter). This "fills out" the tweet.
        """
        # Enhance the tweet per 4CAT Twitter API v2 datasource
        included_users = tweet.get("includes", {}).get("users", [])
        included_media = tweet.get("includes", {}).get("media", [])
        included_polls = tweet.get("includes", {}).get("polls", [])
        included_tweets = tweet.get("includes", {}).get("tweets", [])
        included_places = tweet.get("includes", {}).get("places", [])

        # First enhance included tweets/reference tweets (shame we have to do this every time...)
        enriched_included_tweets = [
            SearchWithTwitterAPIv2.enrich_tweet(included_tweet, included_users, included_media, included_polls,
                                                included_places,
                                                copy.deepcopy(included_tweets), missing_objects={}) for included_tweet
            in included_tweets]

        # Then update the tweet itself
        updated_tweet = SearchWithTwitterAPIv2.enrich_tweet(tweet.get("data"),
                                                            included_users,
                                                            included_media,
                                                            included_polls,
                                                            included_places,
                                                            copy.deepcopy(enriched_included_tweets),
                                                            missing_objects={})
        return updated_tweet

    @staticmethod
    def validate_query(query, request, user):
        """
        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param User user:  User object of user who has submitted the query
        :return dict:  Safe query parameters
        """
        # this is the bare minimum, else we can't narrow down the full data set
        if not query.get("query", None):
            raise QueryParametersException("Please provide a query.")
        twitter_query = query.get("query")

        # the dates need to make sense as a range to search within
        # but, on Twitter, you can also specify before *or* after only
        after, before = query.get("daterange")
        if before and after and before < after:
            raise QueryParametersException("Date range must start before it ends")

        # if we made it this far, the query can be executed
        params = {
            "query": twitter_query,
            "min_date": after,
            "max_date": before,
            "amount": query.get("amount")
        }

        return params

    @staticmethod
    def map_item(tweet):
        """
        Use Twitter APIv2 map_item
        """
        return SearchWithTwitterAPIv2.map_item(tweet)
