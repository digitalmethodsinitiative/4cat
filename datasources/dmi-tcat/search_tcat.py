"""
Twitter search within a DMI-TCAT bin
"""
import requests
import datetime
import csv
import json
import re
import io

from backend.abstract.search import Search
from common.lib.exceptions import QueryParametersException
from common.lib.helpers import UserInput
import config


class SearchWithinTCATBins(Search):
    """
    Get Tweets via DMI-TCAT

    This allows subsetting an existing query bin, similar to the 'Data
    Selection' panel in the DMI-TCAT analysis interface
    """
    type = "dmi-tcat-search"  # job ID
    extension = "csv"

    options = {
        "intro-1": {
            "type": UserInput.OPTION_INFO,
            "help": "This data source interfaces with a DMI-TCAT instance to allow subsetting of tweets from a tweet "
                    "bin in that instance."
        },
        "divider-1": {
            "type": UserInput.OPTION_DIVIDER
        },
        "bin": {
            "type": UserInput.OPTION_INFO,
            "help": "Query bin"
        },
        "query": {
            "type": UserInput.OPTION_TEXT,
            "help": "Query",
            "tooltip": "Match all tweets containing this text."
        },
        "query-exclude": {
            "type": UserInput.OPTION_TEXT,
            "help": "Exclude",
            "tooltip": "Match all tweets that do NOT contain this text."
        },
        "user-name": {
            "type": UserInput.OPTION_TEXT,
            "help": "From user",
            "tooltip": "Match all tweets from this username."
        },
        "user-exclude": {
            "type": UserInput.OPTION_TEXT,
            "help": "Exclude user",
            "tooltip": "Match all tweets NOT from this username."
        },
        "user-bio": {
            "type": UserInput.OPTION_TEXT,
            "help": "User bio",
            "tooltip": "Match all tweets from users with biographies containing this text."
        },
        "user-language": {
            "type": UserInput.OPTION_TEXT,
            "help": "User bio",
            "tooltip": "Match all tweets from users using this language (as detected by Twitter)."
        },
        "tweet-language": {
            "type": UserInput.OPTION_TEXT,
            "help": "User bio",
            "tooltip": "Match all tweets from users with this language (as detected by Twitter)."
        },
        "tweet-client": {
            "type": UserInput.OPTION_TEXT,
            "help": "Twitter client URL/descr",
            "tooltip": "Match all tweets from clients that match this text."
        },
        "url": {
            "type": UserInput.OPTION_TEXT,
            "help": "(Part of) URL",
            "tooltip": "Match all tweets containing this (partial) URL."
        },
        "url-media": {
            "type": UserInput.OPTION_TEXT,
            "help": "(Part of) media URL",
            "tooltip": "Match all tweets containing this (partial) media URL."
        },
        "exclude-replies": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Exclude 'in reply to' Tweets",
            "default": False,
            "tooltip": "Enabling this will filter all replies from the data"
        },
        "daterange": {
            "type": UserInput.OPTION_DATERANGE,
            "help": "Date range"
        }
    }

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        """
        Get data source options

        This method takes the pre-defined options, but fills the 'bins' options
        with bins currently available from the configured TCAT instances.

        :param DataSet parent_dataset:  An object representing the dataset that
        the processor would be run on
        :param User user:  Flask user the options will be displayed for, in
        case they are requested for display in the 4CAT web interface. This can
        be used to show some options only to privileges users.
        """
        options = cls.options

        instances = config.DATASOURCES.get("dmi-tcat", {}).get("instances")
        all_bins = {}
        for instance in instances:
            # query each configured TCAT instance for a list of bins that can
            # be subsetted
            instance = instance.rstrip("/")
            api_url = instance + "/api/bin-stats.php"
            try:
                # todo: cache this somehow!
                api_request = requests.get(api_url, timeout=5)
                instance_bins = json.loads(api_request.content)
                all_bins[instance] = {k: instance_bins[k] for k in sorted(instance_bins)}
            except (requests.RequestException, json.JSONDecodeError):
                options["bin"] = {
                    "type": UserInput.OPTION_INFO,
                    "help": "Could not connect to DMI-TCAT instance %s. Check the 4CAT configuration." % instance
                }
                return options

        options["bin"] = {
            "type": UserInput.OPTION_CHOICE,
            "options": {},
            "help": "Query bin"
        }

        for instance, bins in all_bins.items():
            # make the host somewhat human-readable
            # also strip out embedded HTTP auths
            host = re.sub(r"^https?://", "", instance).split("@").pop()
            for bin_name in bins:
                bin_key = "%s@%s" % (bin_name, host)
                options["bin"]["options"][bin_key] = "%s: %s" % (host, bin_name)

        return options

    def get_items(self, query):
        """
        Use the DMI-TCAT tweet export to retrieve tweets

        :param query:
        :return:
        """
        bin = self.parameters.get("bin")
        bin_name = bin.split("@")[0]
        bin_host = bin.split("@").pop()

        # we cannot store the full instance URL as a parameter, because it may
        # contain sensitive information (e.g. HTTP auth) - so we find the full
        # instance URL again here
        # while the parameter could be marked 'sensitive', the values would
        # still show up in e.g. the HTML of the 'create dataset' form
        available_instances = config.DATASOURCES.get("dmi-tcat", {}).get("instances", [])
        instance_url = ""
        for available_instance in available_instances:
            hostname = re.sub(r"https?://", "", available_instance).split("@").pop().rstrip("/")
            if hostname == bin_host:
                instance_url = available_instance
                break

        if not instance_url:
            return self.dataset.finish_with_error("Invalid DMI-TCAT instance name '%s'" % bin_host)

        # now get the parameters...
        request_url = instance_url.rstrip("/") + "/analysis/mod.export_tweets.php"
        parameters = {
            "dataset": bin_name,
            "query": self.parameters.get("query"),
            "url_query": self.parameters.get("url"),
            "media_url_query": self.parameters.get("url-media"),
            "exclude": self.parameters.get("query-exclude"),
            "from_user_name": self.parameters.get("user-name"),
            "from_user_lang": self.parameters.get("user-language"),
            "lang": self.parameters.get("tweet-language"),
            "exclude_from_user_name": self.parameters.get("user-exclude"),
            "from_source": re.sub(r"<[^>]+>", "", self.parameters.get("tweet-client")),
            "startdate": datetime.datetime.fromtimestamp(self.parameters.get("min_date")).strftime("%Y-%m-%d"),
            "enddate": datetime.datetime.fromtimestamp(self.parameters.get("max_date")).strftime("%Y-%m-%d"),
            "replyto": "yes" if self.parameters.get("exclude-replies") else "no",
            "whattodo": "",
            "graph_resolution": "day",
            "outputformat": "csv"
        }

        # for now we simply request the full CSV export of the bin with the
        # given parameters. To account for large exports, it would be better
        # to chunk the download and parse it item by item
        # todo: chunk the download
        self.dataset.update_status("Searching for tweets on %s" % bin_host)
        response = requests.get(request_url, params=parameters)

        # this is terrible and should be done better
        # the issue is that the downloaded csv file has a BOM which we want to ignore
        # there has to be a better way than this
        # todo: do something less dumb here
        wrapped_export = io.TextIOWrapper(io.BytesIO(), encoding="utf-8-sig", line_buffering=True)
        wrapped_export.write(response.text.encode("utf-8").decode("utf-8-sig"))
        wrapped_export.seek(0)
        reader = csv.DictReader(wrapped_export, delimiter=",")

        items = 0
        for tweet in reader:
            if items % 500 == 0:
                self.dataset.update_status("Loaded %i tweets from bin %s@%s" % (items, bin_name, bin_host))
                items += 1

            # there is more data in the downloaded csv file than this; the
            # format here is identical to that of the Twitter v2 data source's
            # `map_item()` output.
            # todo: do something with the other data
            yield {
                "id": tweet["id"],
                "thread_id": tweet["in_reply_to_status_id"] if tweet["in_reply_to_status_id"] else tweet["id"],
                "timestamp": tweet["created_at"],
                "unix_timestamp": tweet["time"],
                "subject": "",
                "body": tweet["text"],
                "author": tweet["from_user_name"],
                "author_fullname": tweet["from_user_realname"],
                "author_id": tweet["from_user_id"],
                "source": tweet["source"],
                "language_guess": tweet.get("lang"),
                "possibly_sensitive": "yes" if tweet.get("possibly_sensitive") not in ("", "0") else "no",
                "retweet_count": tweet["retweet_count"],
                "reply_count": -1,
                "like_count": tweet["favorite_count"],
                "quote_count": -1,
                "is_retweet": "yes" if tweet["text"][:4] == "RT @" else "no",
                "is_quote_tweet": "yes" if tweet["quoted_status_id"] else "no",
                "is_reply": "yes" if "in_repy_to_status_id" else "no",
                "hashtags": ",".join(re.findall(r"#([^\s!@#$%^&*()_+{}:\"|<>?\[\];'\,./`~]+)", tweet["text"])),
                "urls": ",".join(re.findall(r"https?://[^\s\]()]+", tweet["text"])),
                "images": ",".join(re.findall(r"https://t\.co/[a-zA-Z0-9]+$", tweet["text"])),
                "mentions": ",".join(re.findall(r"@([^\s!@#$%^&*()+{}:\"|<>?\[\];'\,./`~]+)", tweet["text"])),
                "reply_to": tweet["to_user_name"]
            }

    @staticmethod
    def validate_query(query, request, user):
        """
        Validate BitChute query input

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param User user:  User object of user who has submitted the query
        :return dict:  Safe query parameters
        """
        # no query 4 u
        if not query.get("bin", "").strip():
            raise QueryParametersException("You must choose a query bin to get tweets from.")

        # the dates need to make sense as a range to search within
        # and a date range is needed, to not make it too easy to just get all tweets
        after, before = query.get("daterange")
        if (not after or not before) or before <= after:
            raise QueryParametersException("A date range is required and must start before it ends")

        query["min_date"], query["max_date"] = query.get("daterange")
        del query["daterange"]

        # simple!
        return query
