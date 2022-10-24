"""
Twitter user search via the Twitter API v2
"""
import requests
import datetime
import time
import json

from backend.abstract.search import Search
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException, QueryNeedsExplicitConfirmationException
from common.lib.helpers import convert_to_int, UserInput, timify_long
import common.config_manager as config


class SearchUsersWithTwitterAPIv2(Search):
    """
    Get Twitter User Info via the Twitter API
    """
    type = "twitterv2-user-search"  # job ID
    title = "Twitter API (v2) User Lookup"
    extension = "ndjson"
    is_local = False    # Whether this datasource is locally scraped
    is_static = False   # Whether this datasource is still updated

    references = [
        "[Twitter API documentation](https://developer.twitter.com/en/docs/twitter-api)"
    ]

    config = {
        "twitterv2-search-user.api_key": {
            "type": UserInput.OPTION_TEXT,
            "default": "",
            "help": "Academic API Key",
            "tooltip": "An API key for the Twitter v2 API. If provided, the "
                       "user will not need to enter their own key to retrieve "
                       "user data."
        },
        "twitterv2-search-user.max_users": {
            "type": UserInput.OPTION_TEXT,
            "default": 0,
            "min": 0,
            "max": 10_000_000,
            "help": "Max users per dataset",
            "tooltip": "4CAT will never retrieve more than this amount of "
                       "user profiles per dataset. Enter '0' for unlimited."
        }
    }

    def get_items(self, query):
        """
        Get Twitter user profiles

        The actual retrieval code is also used by the 'get followers' and 'get
        following' processors, so it is put in a separate static method.

        :param dict query:
        :return:
        """
        for item in self.fetch_users(self, self.parameters, "https://api.twitter.com/2/users/by", "usernames"):
            yield item

    @staticmethod
    def fetch_users(processor, parameters, endpoint, search_param):
        """
        Use the Twitter v2 API to get user data

        This is a static method, so it can be used elsewhere to get e.g. a list
        of followers.

        :param processor:  Processor that is fetching data
        :return:
        """
        have_api_key = config.get("twitterv2-search-user.api_key")
        bearer_token = parameters.get("api_bearer_token") if not have_api_key else have_api_key
        auth = {"Authorization": "Bearer %s" % bearer_token}

        # these are all expansions and fields available at the time of writing
        # since it does not cost anything extra in terms of rate limiting, go
        # for as much data per tweet as possible...
        tweet_fields = ()
        user_fields = (
        "created_at", "description", "entities", "id", "location", "name", "pinned_tweet_id", "profile_image_url",
        "protected", "public_metrics", "url", "username", "verified", "withheld")

        params = {
            "tweet.fields": ",".join(tweet_fields),
            "user.fields": ",".join(user_fields)
        }

        if "followers" in endpoint or "following" in endpoint:
            # some parameters are only valid for the follower endpoints
            params["max_results"] = 1000  # max

        users = parameters.get("users").split(",")
        done = 0
        previous_request = 0
        missing = []
        expected = len(users)

        while users:
            chunk = users[:100]
            if search_param:
                # follower/following endpoints don't require providing
                # usernames this way
                params[search_param] = ",".join(chunk)

            if processor.interrupted:
                raise ProcessorInterruptedException("Interrupted while getting user data from the Twitter API")

            if "pagination_token" in params:
                # start at page one
                del params["pagination_token"]

            # there is a limit of one request per second, so stay on the safe side of this
            while True:
                # loop in case we have multiple pages of results
                while previous_request == int(time.time()):
                    time.sleep(0.1)
                time.sleep(0.05)
                previous_request = int(time.time())

                # now send the request, allowing for at least 5 retries if the connection seems unstable
                retries = 5
                api_response = None
                while retries > 0:
                    try:
                        api_response = requests.get(endpoint, headers=auth, params=params, timeout=30)
                        break
                    except (ConnectionError, requests.exceptions.RequestException) as e:
                        retries -= 1
                        wait_time = (5 - retries) * 10
                        processor.dataset.update_status("Got %s, waiting %i seconds before retrying" % (str(e), wait_time))
                        time.sleep(wait_time)

                # rate limited - the limit at time of writing is 15 reqs per 15
                # minutes
                if api_response.status_code == 429:
                    resume_at = convert_to_int(api_response.headers["x-rate-limit-reset"]) + 1
                    resume_at_str = datetime.datetime.fromtimestamp(int(resume_at)).strftime("%c")
                    processor.dataset.update_status("Hit Twitter rate limit - waiting until %s to continue." % resume_at_str)
                    while time.time() <= resume_at:
                        if processor.interrupted:
                            raise ProcessorInterruptedException("Interrupted while waiting for rate limit to reset")
                        time.sleep(0.5)
                    continue

                # API keys that are valid but don't have access or haven't been
                # activated properly get a 403
                elif api_response.status_code == 403:
                    try:
                        structured_response = api_response.json()
                        processor.dataset.update_status(
                            "'Forbidden' error from the Twitter API. Could not connect to Twitter API "
                            "with this API key. %s" % structured_response.get("detail", ""), is_final=True)
                    except (json.JSONDecodeError, ValueError):
                        processor.dataset.update_status(
                            "'Forbidden' error from the Twitter API. Your key may not have access to "
                            "the user data endpoints.", is_final=True)
                    finally:
                        return

                # sometimes twitter says '503 service unavailable' for unclear
                # reasons - in that case just wait a while and try again
                elif api_response.status_code in (502, 503, 504):
                    resume_at = time.time() + 60
                    resume_at_str = datetime.datetime.fromtimestamp(int(resume_at)).strftime("%c")
                    processor.dataset.update_status("Twitter unavailable (status %i) - waiting until %s to continue." % (
                        api_response.status_code, resume_at_str))
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
                        msg += "Some of your parameters may be invalid, or the query may be too long. Check that all " \
                               "usernames are, in fact, usernames."

                    processor.dataset.update_status(msg, is_final=True)
                    return

                # invalid API key
                elif api_response.status_code == 401:
                    processor.dataset.update_status("Invalid API key - could not connect to Twitter API", is_final=True)
                    return

                # haven't seen one yet, but they probably exist
                elif api_response.status_code != 200:
                    processor.dataset.update_status(
                        "Unexpected HTTP status %i. Halting user collection." % api_response.status_code, is_final=True)
                    processor.log.warning("Twitter API v2 responded with status code %i. Response body: %s" % (
                        api_response.status_code, api_response.text))
                    return

                elif not api_response:
                    processor.dataset.update_status("Could not connect to Twitter. Cancelling.", is_final=True)
                    return

                api_response = api_response.json()
                users = users[100:]

                print(api_response)

                if "errors" in api_response:
                    for error in api_response["errors"]:
                        if "detail" in error:
                            processor.dataset.log("Received an error from the Twitter API: " + error["detail"])
                        if "resource_id" in error:
                            missing.append(error["resource_id"])

                if "data" not in api_response:
                    continue

                done += len(api_response["data"])
                processor.dataset.update_status("Received %s of ~%s user profiles from the Twitter API" % ("{:,}".format(done), "{:,}".format(expected)))
                processor.dataset.update_progress(done / expected)

                for user in api_response["data"]:
                    if user["username"] in chunk:
                        chunk.remove(user["username"])
                    yield user

                # paginate (when querying followers or followees)
                if api_response.get("meta", {}).get("next_token"):
                    params["pagination_token"] = api_response["meta"]["next_token"]
                else:
                    break

            if chunk:
                missing.extend(chunk)

        if missing and search_param:
            msg = "users were" if len(missing) != 0 else "user was"
            processor.dataset.log("The following user profile(s) were not retrieved (the accounts may no longer exist): " + ", ".join(missing))
            processor.dataset.update_status("Dataset completed, but %s %s missing (check dataset log for details)." % (msg, "{:,}".format(len(missing))), is_final=True)

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        """
        Get Twitter data source options

        These are somewhat dynamic, because depending on settings users may or
        may not need to provide their own API key. Hence the method.

        :param parent_dataset:  Should always be None
        :param user:  User to provide options for
        :return dict:  Data source options
        """
        have_api_key = config.get("twitterv2-search-user.api_key")
        max_users = config.get("twitterv2-search-user.max_users")

        intro_text = ("This data source uses the user lookup endpoint of the Twitter API (v2) to retrieve "
                          "details for a given list of Twitter usernames.")

        if not have_api_key:
            intro_text += ("\n\nA valid [bearer "
                          "token](https://developer.twitter.com/en/docs/authentication/oauth-2-0) for either the "
                          "Standard or Academic API track. The bearer token **will be sent to the 4CAT server**, where "
                          "it will be deleted after data collection has started.")

        if max_users:
            intro_text += "\n\nUp to %s user profiles can be retrieved at a time." % "{:,}".format(max_users)

        options = {
            "intro": {
                "type": UserInput.OPTION_INFO,
                "help": intro_text
            },
        }

        if not have_api_key:
            options.update({
                "api_bearer_token": {
                    "type": UserInput.OPTION_TEXT,
                    "sensitive": True,
                    "cache": True,
                    "help": "API Bearer Token"
                },
            })

        options.update({
            "query": {
                "type": UserInput.OPTION_TEXT_LARGE,
                "help": "Usernames",
                "tooltip": "Separate with commas or new lines."
            }
        })

        return options

    @staticmethod
    def validate_query(query, request, user):
        """
        Validate input for a dataset query on the Twitter data source.

        Will raise a QueryParametersException if invalid parameters are
        encountered. Parameters are additionally sanitised.

        Will also raise a QueryNeedsExplicitConfirmation if the 'counts'
        endpoint of the Twitter API indicates that it will take more than
        30 minutes to collect the dataset. In the front-end, this will
        trigger a warning and confirmation request.

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param User user:  User object of user who has submitted the query
        :return dict:  Safe query parameters
        """
        have_api_key = config.get("twitterv2-search-user.api_key")
        max_users = config.get("twitterv2-search-user.max_users", 10_000_000)

        # this is the bare minimum, else we can't narrow down the full data set
        if not query.get("query", None):
            raise QueryParametersException("Please provide a query.")

        users = [v.strip() for v in query.get("query").replace(",", "\n").split("\n")]

        if not have_api_key:
            if not query.get("api_bearer_token", None):
                raise QueryParametersException("Please provide a valid bearer token.")

        # never query more users than allowed
        if max_users and len(users) > max_users:
            raise QueryParametersException("You cannot query more than %s users (%s were provided)"
                                           % ("{:,}".format(max_users), "{:,}".format(len(users))))

        expected_seconds = len(users) / 83
        if expected_seconds > 900 and not query.get("frontend-confirm"):
            raise QueryNeedsExplicitConfirmationException(
                "Querying %s users will take approximately %s. Do you want to continue?" % (
                "{:,}".format(len(users)), "{:,}".format(timify_long(expected_seconds))))

        return {
            "users": ",".join(users),
            "api_bearer_token": query.get("api_bearer_token", None)
        }

    @staticmethod
    def map_item(user):
        """
        Map a nested Twitter User object to a flat dictionary

        :param user:  User object as originally returned by the Twitter API
        :return dict:  Dictionary in the format expected by 4CAT
        """

        timestamp = datetime.datetime.strptime(user["created_at"], "%Y-%m-%dT%H:%M:%S.000Z")

        mapped_user = {
            "item_id": user["id"],
            "thread_id": user["id"],
            "author": user["username"],
            "author_name": user["name"],
            "author_avatar": user["profile_image_url"],
            "body": user["description"],
            "is_protected": "yes" if user["protected"] else "no",
            "is_verified": "yes" if user["verified"] else "no",
            "timestamp": datetime.datetime.strftime(timestamp, "%Y-%m-%d %H:%M:%S"),
            "num_followers": user["public_metrics"]["followers_count"],
            "num_following": user["public_metrics"]["following_count"],
            "num_tweets": user["public_metrics"]["tweet_count"],
            "num_listed": user["public_metrics"]["listed_count"],
            "unix_timestamp": int(timestamp.timestamp())
        }

        if "follows" in user:
            mapped_user["follows"] = user["follows"]

        if "following" in user:
            mapped_user["following"] = user["following"]

        return mapped_user
