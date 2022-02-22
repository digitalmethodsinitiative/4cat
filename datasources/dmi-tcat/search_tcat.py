"""
Twitter search within a DMI-TCAT bin
"""
import requests
import datetime
import csv
import json
import re
import io

import ural

from backend.abstract.search import Search
from common.lib.exceptions import QueryParametersException
from common.lib.user_input import UserInput
from common.lib.helpers import sniff_encoding

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
            "help": "Query text",
            "tooltip": "Match all tweets containing this text."
        },
        "query-exclude": {
            "type": UserInput.OPTION_TEXT,
            "help": "Exclude text",
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
        "exclude-replies": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Exclude 'reply' tweets",
            "default": False,
            "tooltip": "Enabling this will remove all replies from the data"
        },
        "daterange": {
            "type": UserInput.OPTION_DATERANGE,
            "help": "Date range"
        },
        # Advanced Options Section
        "divider-2": {
            "type": UserInput.OPTION_DIVIDER
        },
        "advanced_options_info": {
            "type": UserInput.OPTION_INFO,
            "help": "Advanced Query Options can further refine your query"
        },
        "user-bio": {
            "type": UserInput.OPTION_TEXT,
            "help": "User bio",
            "tooltip": "Match all tweets from users with biographies containing this text."
        },
        "user-language": {
            "type": UserInput.OPTION_TEXT,
            "help": "User language",
            "tooltip": "Match all tweets from users using this language (as detected by Twitter)."
        },
        "tweet-language": {
            "type": UserInput.OPTION_TEXT,
            "help": "Tweet language",
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
            for bin_name, bin in bins.items():
                bin_key = "%s@%s" % (bin_name, host)
                display_text = f"{bin_name}: {bin.get('tweets_approximate')} tweets from {bin.get('range').get('first_tweet')} to {bin.get('range').get('last_tweet')}"
                options["bin"]["options"][bin_key] = display_text

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
        # given parameters, letting TCAT handle the full text search and so
        # on
        self.dataset.update_status("Searching for tweets on %s" % bin_host)
        response = requests.get(request_url, params=parameters, stream=True)
        if response.status_code != 200:
            return self.dataset.finish_with_error("Query bin not available: received HTTP Error %i" % response.status_code)

        # process the file in 1kB chunks, buffer as we go
        # If a newline is encountered, the buffer is processed as a row of csv
        # data. This works as long as there are no newlines in the csv itself,
        # which is the case for TCAT exports. Processing as a stream is needed
        # to avoid having to load the full file in memory
        buffer = bytearray()
        fieldnames = None
        items = 0
        encoding = None
        for chunk in response.iter_content(chunk_size=1024):
            # see if this chunk contains a newline, in which case we have a
            # full line to process (e.g. as a tweet)
            lines = []
            buffer += bytearray(chunk)

            if not encoding and len(buffer) > 3:
                # response.encoding is not correct sometimes, since it does not
                # indicate that the file uses a BOM, so sniff it instead once
                # we have some bytes
                encoding = sniff_encoding(buffer)

            # split buffer by newlines and process each full line
            # the last line is always carried over, since it may be incomplete
            if b"\n" in buffer:
                buffered_lines = buffer.split(b"\n")
                lines = buffered_lines[:-1]
                buffer = buffered_lines.pop()
            elif not chunk:
                # eof, process left-over data
                lines = buffer.split(b"\n")

            # and finally we can process the data
            for line in lines:
                # use a dummy csv reader to abstract away the annoying csv parsing
                # this is quite a bit of overhead, but beats implementing csv parsing
                # manually, and it's still reasonably fast (about 10k/second)
                dummy_file = io.TextIOWrapper(io.BytesIO(line.replace(b"\0", b"")), encoding=encoding)
                reader = csv.reader(dummy_file,
                                    delimiter=",",
                                    quotechar='"',
                                    doublequote=True,
                                    quoting=csv.QUOTE_MINIMAL)
                row_data = next(reader)

                if row_data and not fieldnames:
                    # first line in file
                    fieldnames = row_data.copy()
                elif row_data:
                    tweet = dict(zip(fieldnames, row_data))
                    items += 1

                    if items % 250 == 0:
                        self.dataset.update_status("Loaded %i tweets from bin %s@%s" % (items, bin_name, bin_host))

                    # there is more data in the downloaded csv file than this; the
                    # format here is identical to that of the Twitter v2 data source's
                    # `map_item()` output.
                    # todo: do something with the other data
                    yield {
                        "id": tweet["id"],
                        "thread_id": tweet["in_reply_to_status_id"] if tweet["in_reply_to_status_id"] else tweet["id"],
                        "timestamp": int(tweet["created_at"]),
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
                        "urls": ",".join(ural.urls_from_text(tweet["text"])),
                        "images": ",".join(re.findall(r"https://t\.co/[a-zA-Z0-9]+$", tweet["text"])),
                        "mentions": ",".join(re.findall(r"@([^\s!@#$%^&*()+{}:\"|<>?\[\];'\,./`~]+)", tweet["text"])),
                        "reply_to": tweet["to_user_name"]
                    }

            if not chunk:
                # end of file
                break


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
