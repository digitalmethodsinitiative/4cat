"""
Twitter search within a DMI-TCAT bin v2
Direct database connection
"""
import datetime
import re
import ural
import io
import pymysql


from backend.abstract.search import Search
from common.lib.exceptions import QueryParametersException
from common.lib.user_input import UserInput
from common.lib.helpers import sniff_encoding
from backend.lib.database_mysql import MySQLDatabase
from common.lib.logger import Logger

import config


class SearchWithinTCATBinsV2(Search):
    """
    Get Tweets via DMI-TCAT

    This allows subsetting an existing query bin, similar to the 'Data
    Selection' panel in the DMI-TCAT analysis interface
    """
    type = "dmi-tcatv2-search"  # job ID
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
        "query_type": {
            "type": UserInput.OPTION_CHOICE,
            "help": "Basic or Advanced Query",
            "options": {
                "basic": "Basic query all bin tweets for specific text (Query) and date (Date range)",
                "advanced": "Select queries on any TCAT twitter tables"
            },
            "default": "basic",
            "tooltip": "Advanced queries do not provide scaffolding, so understanding TCAT database structure is necessary"
        },
        "query": {
            "type": UserInput.OPTION_TEXT,
            "help": "Query text",
            "tooltip": "Match all tweets containing this text."
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
        print('TCAT CALLING get_options', flush=True)

        # Collect Metadata from TCAT instances
        all_bins = cls.collect_tcat_metadata()

        options["bin"] = {
            "type": UserInput.OPTION_CHOICE,
            "options": {},
            "help": "Query bin"
        }

        for instance_name, bins in all_bins.items():
            for bin_name, bin in bins.items():
                bin_key = "%s@%s" % (bin_name, instance_name)
                display_text = f"{bin_name}: {bin.get('tweet_count')} tweets from {bin.get('first_tweet_datetime').strftime('%Y-%m-%d %H:%M:%S')} to {bin.get('last_tweet_datetime').strftime('%Y-%m-%d %H:%M:%S')}"
                options["bin"]["options"][bin_key] = display_text

        return options

    def get_items(self, query):
        """
        Use the DMI-TCAT tweet export to retrieve tweets

        :param query:
        :yield dict: mapped_tweet for any "basic" query else for "advanced" queries a dictionary with mysql result
        """
        bin = self.parameters.get("bin")
        bin_name = bin.split("@")[0]
        tcat_name = bin.split("@").pop()

        available_instances = config.DATASOURCES.get("dmi-tcatv2", {}).get("instances", [])
        instance = [instance for instance in available_instances if instance.get('tcat_name') == tcat_name][0]

        db = MySQLDatabase(logger=self.log,
                           dbname=instance.get('db_name'),
                           user=instance.get('db_user'),
                           password=instance.get('db_password'),
                           host=instance.get('db_host'),
                           port=instance.get('db_port'))

        self.dataset.update_status("Searching for tweets on %s" % bin_name)
        if self.parameters.get("query_type") == 'advanced':
            # Advanced query should be simple from our perspective...
            self.dataset.log('Query: %s' % self.parameters.get("query"))
            unbuffered_cursor = db.connection.cursor(pymysql.cursors.SSCursor)
            try:
                num_results = unbuffered_cursor.execute(self.parameters.get("query"))
            except pymysql.err.ProgrammingError as e:
                self.dataset.update_status("SQL query error: %s" % str(e), is_final=True)
                return
            # self.dataset.update_status("Retrieving %i results" % int(num_results)) # num_results is CLEARLY not what I thought
            # Get column names from cursor
            column_names = [description[0] for description in unbuffered_cursor.description]
            for result in unbuffered_cursor.fetchall_unbuffered():
                # Reformat result (which is a tuple with each column in the row) to dict
                new_result = {k: v for k, v in zip(column_names, result)}
                # 4CAT necessary fieldnames
                new_result['id'] = new_result.get('id', '')
                new_result['thread_id'] = new_result.get("in_reply_to_status_id") if new_result.get(
                    "in_reply_to_status_id") else new_result.get("quoted_status_id") if new_result.get(
                    "quoted_status_id") else new_result.get("id")
                new_result['body'] = new_result.get('text', '')
                new_result['timestamp'] = new_result.get('created_at', None)
                new_result['subject'] = ''
                new_result['author'] = new_result.get('from_user_name', '')
                yield new_result

        else:
            # "Basic" query
            text_query = self.parameters.get("query")

            where = []
            replacements = []
            # Find AND and OR
            placeholder = 0
            start_of_match = 0
            while start_of_match >= 0:
                match = None
                and_match = text_query[placeholder:].find(' AND ')
                or_match = text_query[placeholder:].find(' OR ')
                if and_match != -1 and or_match != -1:
                    # both found
                    if and_match < or_match:
                        # and match first
                        match = 'AND '
                        start_of_match = and_match
                    else:
                        # or match first
                        match ='OR '
                        start_of_match = or_match
                elif and_match != -1:
                    # and match only
                    match ='AND '
                    start_of_match = and_match
                elif or_match != -1:
                    # or match only
                    match = 'OR '
                    start_of_match = or_match
                else:
                    # neither
                    match = None
                    start_of_match = -1
                # Add partial query to where and replacements
                if match:
                    where.append('lower(text) LIKE %s ' + match)
                    replacements.append('%'+text_query[placeholder:placeholder+start_of_match].lower().strip()+'%')
                    # new start
                    placeholder = placeholder + start_of_match + len(match)
                else:
                    where.append('lower(text) LIKE %s')
                    replacements.append('%'+text_query[placeholder:].lower().strip()+'%')

            if query.get("min_date", None):
                try:
                    if int(query.get("min_date")) > 0:
                        where.append("AND created_at >= %s")
                        replacements.append(datetime.datetime.fromtimestamp(int(query.get("min_date"))))
                except ValueError:
                    pass

            if query.get("max_date", None):
                try:
                    if int(query.get("max_date")) > 0:
                        where.append("AND created_at < %s")
                        replacements.append(datetime.datetime.fromtimestamp(int(query.get("max_date"))))
                except ValueError:
                    pass

            where = " ".join(where)
            query = 'SELECT * FROM ' + bin_name + '_tweets WHERE ' + where
            self.dataset.log('Query: %s' % query)
            self.dataset.log('Replacements: %s' % ', '.join([str(i) for i in replacements]))
            unbuffered_cursor = db.connection.cursor(pymysql.cursors.SSCursor)
            num_results = unbuffered_cursor.execute(query, replacements)
            # self.dataset.update_status("Retrieving %i results" % int(num_results)) # num_results is CLEARLY not what I thought
            column_names = [description[0] for description in unbuffered_cursor.description]
            for result in unbuffered_cursor.fetchall_unbuffered():
                new_result = {k: v for k, v in zip(column_names, result)}
                # Map tweet to 4CAT fields
                new_result = self.tweet_mapping(new_result)
                yield new_result

    @staticmethod
    def tweet_mapping(tweet):
        """
        Takes TCAT output from specific tables and maps them to 4CAT expected fields. The expected fields attempt to
        mirror that mapped_tweet from twitterv2 datasource.

        :param dict tweet: TCAT dict returned from query; expected to be from bin tweets table
        :return dict:
        """
        mapped_tweet = {'id': tweet.get('id', ''),
                        # For thread_id, we use in_reply_to_status_id if tweet is reply, retweet_id if tweet is
                        # retweet, or its own ID
                        # Note: tweets can have BOTH in_reply_to_status_id and retweet_id as you can retweet a reply
                        # or reply to retweet.
                        # THIS IS DIFFERENT from Twitter APIv2 as there does not appear to be a quote ID (for retweets
                        # with added text)
                        'thread_id': tweet.get("in_reply_to_status_id") if tweet.get(
                                               "in_reply_to_status_id") else tweet.get("retweet_id") if tweet.get(
                                               "retweet_id") else tweet.get("id"),
                        'body': tweet.get('text', ''),
                        # 'created_at': tweet.get('created_at'),
                        'timestamp': int(datetime.datetime.timestamp(tweet.get('created_at'))) if type(
                                                tweet.get('created_at')) == datetime.datetime else None,
                        'subject': '',
                        'author': tweet.get('from_user_name', ''),
                        "author_fullname": tweet["from_user_realname"],
                        "author_id": tweet["from_user_id"],
                        "source": tweet["source"],
                        "language_guess": tweet.get("lang"),

                        "retweet_count": tweet["retweet_count"],
                        "like_count": tweet["favorite_count"],
                        "is_retweet": "yes" if tweet.get('retweet_id', False) else "no",
                        "is_reply": "yes" if tweet["in_reply_to_status_id"] else "no",
                        "in_reply_to_status_id": tweet["in_reply_to_status_id"] if tweet["in_reply_to_status_id"] else None,
                        "reply_to": tweet["to_user_name"],
                        "reply_to_id": tweet.get('to_user_id') if tweet.get('to_user_id') else None,

                        # 4CAT specifics
                        "hashtags": ",".join(re.findall(r"#([^\s!@#$%^&*()_+{}:\"|<>?\[\];'\,./`~]+)", tweet["text"])),
                        "urls": ",".join(ural.urls_from_text(tweet["text"])),
                        "images": ",".join(re.findall(r"https://t\.co/[a-zA-Z0-9]+$", tweet["text"])),
                        "mentions": ",".join(re.findall(r"@([^\s!@#$%^&*()+{}:\"|<>?\[\];'\,./`~]+)", tweet["text"])),

                        # Additional TCAT data (compared to twitterv2 map_item function)
                        "filter_level": tweet['filter_level'],
                        'location': tweet['location'],
                        'latitude': tweet['geo_lat'] if tweet['geo_lat'] else None,
                        'longitude': tweet['geo_lng'] if tweet['geo_lng'] else None,
                        'author_verified': tweet['from_user_verified'] if tweet['from_user_verified'] else None,
                        'author_description': tweet['from_user_description'],
                        'author_url': tweet['from_user_url'],
                        'author_profile_image': tweet['from_user_profile_image_url'],
                        'author_timezone_UTC_offset': int((int(tweet['from_user_utcoffset']) if
                                                           tweet['from_user_utcoffset'] else 0)/60/60),
                        'author_timezone_name': tweet['from_user_timezone'],
                        'author_language': tweet['from_user_lang'],
                        'author_tweet_count': tweet['from_user_tweetcount'],
                        'author_follower_count': tweet['from_user_followercount'],
                        'author_friend_following_count': tweet['from_user_friendcount'],
                        'author_favorite_count': tweet.get('from_user_favourites_count'), # NOT in tweets table?
                        'author_listed_count': tweet['from_user_listed'] if tweet['from_user_listed'] else None,
                        'author_withheld_scope': tweet.get('from_user_withheld_scope'), # NOT in tweets table?
                        'author_created_at': tweet.get('from_user_created_at'), # NOT in tweets table?

                        # TODO find in other TCAT tables or does not exist
                        # "possibly_sensitive": "yes" if tweet.get("possibly_sensitive") not in ("", "0") else "no",
                        # "is_quote_tweet": "yes" if tweet["quoted_status_id"] else "no",
                        # 'withheld_copyright': tweet['withheld_copyright'],  # TCAT may no collect this anymore
                        # 'withheld_scope': tweet['withheld_scope'], # TCAT may no collect this anymore
                        # 'truncated': tweet['truncated'], # Older tweets could be truncated meaning their text was cut off due to Twitter/TCAT db character limits

                        }

        # Ensure that any keys not specifically mapped to another field are added to the new mapped_tweet
        mapped_keys = ['id', 'text', 'created_at', 'from_user_name', 'from_user_realname', 'from_user_id',
                       'from_user_lang', 'from_user_tweetcount', 'from_user_followercount', 'from_user_friendcount',
                       'from_user_listed', 'from_user_utcoffset', 'from_user_timezone', 'from_user_description',
                       'from_user_url', 'from_user_verified', 'from_user_profile_image_url', 'source', 'lang',
                       'filter_level', 'location', 'to_user_name', 'to_user_id', 'geo_lat', 'geo_lng', 'retweet_count',
                       'in_reply_to_status_id']
        for key in tweet.keys():
            if key not in mapped_keys:
                index = ''
                while key + index in mapped_tweet.keys():
                    index += '_1'
                mapped_tweet[key + index] = tweet.get(key)

        return mapped_tweet


    @classmethod
    def collect_tcat_metadata(cls):
        """
        Collect specific metadata from TCAT instances listed in the configuration and return a dictionary containing
        this data. To be used to infor the user of available TCAT bins and create the options from which a user will
        select.

        :return dict: All of the available bins from accessible TCAT instances
        """

        # todo: cache this somehow! and check for the cache
        instances = config.DATASOURCES.get("dmi-tcatv2", {}).get("instances", [])

        all_bins = {}
        for instance in instances:
            # Query each instance for bins
            db = MySQLDatabase(logger=Logger(),
                               dbname=instance.get('db_name'),
                               user=instance.get('db_user'),
                               password=instance.get('db_password'),
                               host=instance.get('db_host'),
                               port=instance.get('db_port'))
            # try:
            instance_bins = db.fetchall('SELECT id, querybin, type from tcat_query_bins')
            # except:

            instance_bins_metadata = {}
            for instance_bin in instance_bins:
                bin_data = {
                    'instance': instance,
                    'querybin': instance_bin['querybin'],
                }

                # Query for number of tweets
                tweet_count = db.fetchone('SELECT COUNT(id) from ' + instance_bin['querybin'] + '_tweets')[
                    'COUNT(id)']
                bin_data['tweet_count'] = tweet_count

                # Collect first and last tweet datetimes
                first_tweet_datetime = db.fetchone('SELECT created_at from ' + instance_bin['querybin'] + '_tweets ORDER BY created_at ASC LIMIT 1')['created_at']
                last_tweet_datetime = db.fetchone('SELECT created_at from ' + instance_bin['querybin'] + '_tweets ORDER BY created_at DESC LIMIT 1')['created_at']
                bin_data['first_tweet_datetime'] = first_tweet_datetime
                bin_data['last_tweet_datetime'] = last_tweet_datetime

                # Could check if bin currently should be collecting
                # db.fetchall('SELECT EXISTS ( SELECT endtime from tcat_query_bins_periods WHERE querybin_id = ' + str(instance_bin['id']) + ' and endtime = "0000-00-00 00:00:00" ) as active')

                # Could collect phrases or usernames...
                # if instance_bin['type'] in []:
                # elif instance_bin['type'] in []:

                # Could collect all periods for nuanced metadata...
                #periods = db.fetchall('SELECT starttime, endtime from tcat_query_bins_periods WHERE query_bin_id = ' + instance_bin['id'])

                # Add bin_data to instance collection
                instance_bins_metadata[instance_bin['querybin']] = bin_data
            # Add bins to instance
            all_bins[instance['tcat_name']] = instance_bins_metadata

        return all_bins

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

        # the dates need to make sense as a range to search within
        # and a date range is needed, to not make it too easy to just get all tweets
        after, before = query.get("daterange")
        if (after and before) and not before <= after:
            raise QueryParametersException("A date range must start before it ends")

        query["min_date"], query["max_date"] = query.get("daterange")
        del query["daterange"]

        # simple!
        return query
