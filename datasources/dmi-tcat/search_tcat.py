"""
Twitter search within a DMI-TCAT bin; connect via TCAT frontend
"""
import requests
import datetime
import csv
import json
import re
import io

from backend.lib.search import Search
from common.lib.exceptions import QueryParametersException
from common.lib.user_input import UserInput
from common.lib.helpers import sniff_encoding
from common.config_manager import config

from datasources.twitterv2.search_twitter import SearchWithTwitterAPIv2


class SearchWithinTCATBins(Search):
    """
    Get Tweets via DMI-TCAT

    This allows subsetting an existing query bin, similar to the 'Data
    Selection' panel in the DMI-TCAT analysis interface
    """
    type = "dmi-tcat-search"  # job ID
    extension = "ndjson"
    title = "TCAT Search (HTTP)"

    # TCAT has a few fields that do not exist in APIv2
    additional_TCAT_fields = ["to_user_name", "filter_level", "favorite_count", "truncated", "from_user_favourites_count", "from_user_lang", "from_user_utcoffset",
                              "from_user_timezone"]

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
            "type": UserInput.OPTION_CHOICE,
            "options": {
                "exclude": "Exclude replies",
                "include": "Include replies"
            },
            "help": "Reply tweets",
            "default": "include",
            "tooltip": "Choose to exclude or include tweets that are replies from the data"
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
            "help": "User bio text",
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

    config = {
        "dmi-tcat-search.instances": {
            "type": UserInput.OPTION_TEXT_JSON,
            "help": "DMI-TCAT instances",
            "tooltip": 'List of DMI-TCAT instance URLs, e.g. ["http://username:password@tcat.instance.webpage.net"]. '
                       'This  needs to be formatted as a JSON list of strings.',
            "default": {}
        }
    }

    bin_data = {
        "all_bins": {},
        "last_collected": {},
    }

    @classmethod
    def collect_all_bins(cls, force_update=False):
        """
        Requests bin information from TCAT instances
        """
        instances = config.get("dmi-tcat-search.instances", [])
        for instance in instances:
            # query each configured TCAT instance for a list of bins that can
            # be subsetted
            instance = instance.rstrip("/")
            api_url = instance + "/api/bin-stats.php"

            if force_update or instance not in cls.bin_data["last_collected"] or datetime.datetime.now()-datetime.timedelta(days=1) >= cls.bin_data["last_collected"][instance]:
                # Collect Instance data
                try:
                    api_request = requests.get(api_url, timeout=5)
                    instance_bins = json.loads(api_request.content)
                    cls.bin_data["all_bins"][instance] = {k: instance_bins[k] for k in sorted(instance_bins)}
                    cls.bin_data["last_collected"][instance] = datetime.datetime.now()
                except (requests.RequestException, json.JSONDecodeError):
                    cls.bin_data["all_bins"][instance] = {"failed": True}
                    # TODO: No logger here as nothing has been initialized
                    # print(f"WARNING, unable to collect TCAT bins from instance {instance}")
                    pass

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

        cls.collect_all_bins()
        if all([data.get("failed", False) for instance, data in cls.bin_data["all_bins"].items()]):
            options["bin"] = {
                "type": UserInput.OPTION_INFO,
                "help": "Could not connect to DMI-TCAT instance(s)."
            }
            return options

        options["bin"] = {
            "type": UserInput.OPTION_CHOICE,
            "options": {},
            "help": "Query bin"
        }

        for instance, bins in cls.bin_data["all_bins"].items():
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
        available_instances = config.get("dmi-tcat-search.instances", [])
        instance_url = ""
        instance = None
        for available_instance in available_instances:
            hostname = re.sub(r"https?://", "", available_instance).split("@").pop().rstrip("/")
            if hostname == bin_host:
                instance_url = available_instance
                instance = available_instance.rstrip("/")
                break

        if not instance_url:
            return self.dataset.finish_with_error("Invalid DMI-TCAT instance name '%s'" % bin_host)

        # Collect the bins again (ensure we have updated info in case bin is still active)
        self.collect_all_bins(force_update=True)
        # Add metadata to parameters
        try:
            current_bin = self.bin_data["all_bins"][instance][bin_name]
        except KeyError:
            return self.dataset.finish_with_error(f"Lost connection to TCAT instance {bin_host}")
        # Add TCAT metadata to dataset
        self.dataset.tcat_bin_data = current_bin
        if current_bin.get("type") in ["follow", "track", "timeline", "geotrack"] and ("phrase_times" not in current_bin or not "user_times" not in current_bin):
            self.dataset.update_status("Warning: TCAT not updated to send phrase and user time ranges; consider updating if you would like to retain this BIN metadata.")

        # now get the parameters...
        request_url = instance_url.rstrip("/") + "/analysis/mod.export_tweets.php"

        # Allow for blank dates
        if self.parameters.get("min_date"):
            start_date = datetime.datetime.fromtimestamp(self.parameters.get("min_date")).strftime("%Y-%m-%d")
        else:
            first_tweet_timestamp = current_bin.get('range').get('first_tweet')
            start_date = datetime.datetime.strptime(first_tweet_timestamp, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")

        end_date = datetime.datetime.fromtimestamp(self.parameters.get("max_date")).strftime("%Y-%m-%d") if self.parameters.get("max_date") else (datetime.datetime.now() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
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
            "startdate": start_date,
            "enddate": end_date,
            "replyto": "yes" if self.parameters.get("exclude-replies") == "exclude" else "no",
            "whattodo": "",
            "exportSettings": "urls,mentions,hashtags,media,",
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

                    yield self.tcat_to_APIv2(tweet)

            if not chunk:
                # end of file
                break

    @ staticmethod
    def tcat_to_4cat_time(tcat_time):
        """
        Twitter APIv2 time is in format "%Y-%m-%dT%H:%M:%S.000Z" while TCAT uses "%Y-%m-%d %H:%M:%S" and a timestamp.

        :return datetime:
        """
        try:
            tcat_time = int(tcat_time)
            return datetime.datetime.fromtimestamp(tcat_time).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        except ValueError:
            return datetime.datetime.strptime(tcat_time, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%dT%H:%M:%S.000Z")

    @staticmethod
    def tcat_to_APIv2(tcat_tweet):
        """
        Attempt to construct a 4CAT tweet gathered from APIv2 to allow for use of Twitter specific processors!

        A great deal of information is missing so there may result in some issues. Notes are kept for the expected
        type and, if the data is missing in TCAT, None is used. Therefor it should be possible to refactor processors
        to handle None if necessary.
        """
        # We're missing lots of data here...

        urls = [url.strip() for url in (tcat_tweet["urls_expanded"].split(";") if tcat_tweet["urls_expanded"] else tcat_tweet["urls_followed"].split(";") if tcat_tweet["urls_followed"] else tcat_tweet["urls_followed"].split(";")) if url]
        # TCAT media_id: 7 = video, 3 = photo, 16 = animated_gif
        media_type = "video" if tcat_tweet["media_id"] == "7" else "photo" if tcat_tweet["media_id"] == "3" else "animated_gif" if tcat_tweet["media_id"] == "16" else tcat_tweet["media_id"]

        # 4CAT Twitter APIv2 result data structure
        APIv2_tweet = {
            "lang": tcat_tweet["lang"],  # str
            "source": tcat_tweet["source"],  # REMOVED FROM TWITTER API v2
            "possibly_sensitive": True if tcat_tweet["possibly_sensitive"] == 1 else False if tcat_tweet["possibly_sensitive"] == 0 else None,  # bool
            "text": tcat_tweet["text"],  # str
            "edit_history_tweet_ids": None,  # list; Missing in TCAT data
            "public_metrics": {
                "retweet_count": tcat_tweet["retweet_count"],  # int
                "reply_count": None,  # int; Missing in TCAT data
                "like_count": tcat_tweet["favorite_count"],  # int
                "quote_count": None,  # int; Missing in TCAT data
                "impression_count": None,  # int; Missing in TCAT data
                # TCAT has also favorite_count
            },
            "entities": {
                "mentions": [{
                    "id": None,  # str; Missing in TCAT data
                    "username": mention.strip(),  # str
                    # Twitter v2 API has additional user fields
                } for mention in tcat_tweet["mentions"].split(";") if mention],
                "annotations": None,  # list; Missing in TCAT data
                "urls": [{
                    "url": url,  # str
                    "expanded_url": url,  # str
                    # Twitter v2 API has additional URL fields
                } for url in urls],
                "hashtags": [{
                    "tag": hashtag.strip(),  # str
                    "start": None,  # int; Missing in TCAT data
                    "end": None,  # int; Missing in TCAT data
                } for hashtag in tcat_tweet["hashtags"].split(";") if hashtag],
                "cashtags": None,  # list; Missing in TCAT data
            },
            "created_at": SearchWithinTCATBins.tcat_to_4cat_time(tcat_tweet["time"]),  # str
            "id": tcat_tweet["id"],  # str
            "author_id": tcat_tweet["from_user_id"],  # str
            "context_annotations": None,  # list; Missing in TCAT data
            "reply_settings": None,  # str; Missing in TCAT data
            "conversation_id": None,  # str; TCAT has a in_reply_to_status_id but this is not necessarily the original Tweet that started the conversation
            "author_user": {
                "protected": None,  # bool; Missing in TCAT data
                "verified": True if tcat_tweet["from_user_verified"] == 1 else False if tcat_tweet["from_user_verified"] == 0 else None,  # bool
                "created_at": SearchWithinTCATBins.tcat_to_4cat_time(tcat_tweet["from_user_created_at"]),  # str
                "name": tcat_tweet["from_user_realname"],  # str
                "entities": {
                    "description": None,  # dict; contains entities from author description such as mentions, URLs, etc.; Missing in TCAT data
                    "url": None,  # dict; containers entities from author url e.g. URL data; Missing in TCAT data
                },
                "description": tcat_tweet["from_user_description"],  # str
                "pinned_tweet_id": None,  # str; Missing in TCAT data
                "profile_image_url": tcat_tweet["from_user_profile_image_url"],  # str
                "url": tcat_tweet["from_user_url"],  # str
                "username": tcat_tweet["from_user_name"],  # str
                "id": tcat_tweet["from_user_id"],  # str
                "location": None,  # str; Missing in TCAT data
                "public_metrics": {
                    "followers_count": tcat_tweet["from_user_followercount"],  # int
                    "following_count": tcat_tweet["from_user_friendcount"],  # int
                    "tweet_count": tcat_tweet["from_user_tweetcount"],  # int
                    "listed_count": tcat_tweet["from_user_listed"],  # int
                    # TCAT has also from_user_favourites_count
                },
                "withheld": {
                    "country_codes": tcat_tweet["from_user_withheld_scope"].split(";"),  # list; TODO TCAT has column, but have not seen it populated in testing... This is guess
                },
                # TCAT has also from_user_lang, from_user_utcoffset, from_user_timezone
            },
            "attachments": {
                # TCAT has some media data, but not the URLs listed
                "media_keys": [{
                    "type": media_type,
                    "url": ",".join([url for url in urls if (url.split("/")[-2] if len(url.split("/")) > 1 else "") in ["photo"]]),  # str; TCAT does not have the URL though it may be in the list of URLs
                    "variants": [{"url": ",".join([url for url in urls if (url.split("/")[-2] if len(url.split("/")) > 1 else "") in ["video"]]), "bit_rate":0}]  # list; This is not the expected direct link to video, but it is a URL to the video
                    # Twitter API v2 has additional data
                }],  # list; TCAT seems to only have one type of media per tweet
                "poll_ids": None,  # list; Missing from TCAT data
            },
            "geo": {
                "place_id": None,  # str; Missing from TCAT data
                "place": {
                    "country": None,  # str; Missing from TCAT data
                    "id": None,  # str; Missing from TCAT data
                    "geo": {

                    },
                    "country_code": None,  # str; Missing from TCAT data
                    "name": tcat_tweet["location"],  # str
                    "place_type": None,  # str; Missing from TCAT data
                    "full_name": tcat_tweet["location"],  # str
                },
                "coordindates": {
                    "type": None,  # str; Missing from TCAT data
                    "coordinates": [tcat_tweet["lng"], tcat_tweet["lat"]],  # list i.e. [longitude, latitude]
                },
            },
            "withheld": {
                "copyright": True if tcat_tweet["withheld_copyright"] == 1 else False if tcat_tweet["withheld_copyright"] == 0 else None,  # bool; TODO TCAT has column, but have not seen it populated in testing... This is guess
                "country_codes": tcat_tweet["withheld_scope"].split(";"),  # list; TODO TCAT has column, but have not seen it populated in testing... This is guess
            },
        }

        # Referenced Tweets; Twitter API v2 has entire tweet data here which we will be missing
        referenced_tweets = []
        if tcat_tweet["text"][:4] == "RT @":
            # Retweet
            referenced_tweets.append({
                "type": "retweeted",
                "id": None,  # str; Missing in TCAT data
            })
        if tcat_tweet["quoted_status_id"]:
            # Quote
            referenced_tweets.append({
                "type": "quoted",
                "id": tcat_tweet["quoted_status_id"],  # str; Missing in TCAT data
            })
        if tcat_tweet["in_reply_to_status_id"]:
            # Reply
            referenced_tweets.append({
                "type": "replied_to",
                "id": tcat_tweet["in_reply_to_status_id"],  # str; Missing in TCAT data
            })
            # These should NOT be None in case a processor/user attempts to identify a reply using these
            APIv2_tweet["in_reply_to_user_id"] = "UNKNOWN"  # str; Missing from TCAT data
            APIv2_tweet["in_reply_to_user"] = {"username": "UNKNOWN"}  # dict; Missing from TCAT data

        APIv2_tweet["referenced_tweets"] = referenced_tweets  # list

        # Append any extra TCAT data
        additional_TCAT_data = {}
        for field in SearchWithinTCATBins.additional_TCAT_fields:
            additional_TCAT_data["TCAT_"+field] = tcat_tweet[field]
        APIv2_tweet.update(additional_TCAT_data)

        return APIv2_tweet

    @staticmethod
    def validate_query(query, request, user):
        """
        Validate DMI-TCAT query input

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param User user:  User object of user who has submitted the query
        :return dict:  Safe query parameters
        """
        # no query 4 u
        if not query.get("bin", "").strip():
            raise QueryParametersException("You must choose a query bin to get tweets from.")

        # Dates need to make sense as a range to search within
        after, before = query.get("daterange")
        if (after and before) and before <= after:
            raise QueryParametersException("A date range must start before it ends")

        query["min_date"], query["max_date"] = query.get("daterange")
        del query["daterange"]

        # simple!
        return query

    @staticmethod
    def map_item(tweet):
        """
        Use Twitter APIv2 map_item
        """
        mapped_tweet = SearchWithTwitterAPIv2.map_item(tweet)

        # Add TCAT extra data
        for field in SearchWithinTCATBins.additional_TCAT_fields:
            mapped_tweet["TCAT_" + field] = tweet.get("TCAT_" + field)

        return mapped_tweet
