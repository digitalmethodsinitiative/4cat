"""
Twitter APIv2 hashtag statistics
"""
from common.lib.helpers import UserInput
from processors.twitter.base_twitter_stats import TwitterStatsBase

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class TwitterIdenticalTweets(TwitterStatsBase):
    """
    Collect Twitter statistics. Build to emulate TCAT statistic.
    """
    type = "twitter-identical-tweets"  # job type ID
    category = "Twitter Analysis"  # category
    title = "Identical Tweet Frequency"  # title displayed in UI
    description = "Groups tweets by text and counts the number of times they have been (re)tweeted indentically."  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    sorted = 'Number of Identical Tweets'

    options = {
        "timeframe": {
            "type": UserInput.OPTION_CHOICE,
            "default": "month",
            "options": {"all": "Overall", "year": "Year", "month": "Month", "week": "Week", "day": "Day",
                        "hour": "Hour", "minute": "Minute"},
            "help": "Produce counts per"
        },
    }

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Determine if processor is compatible with dataset

        :param module: Dataset or processor to determine compatibility with
        """
        return module.type in ["twitterv2-search", "dmi-tcat-search"]

    def map_data(self, post):
        """
        Maps a post to collect aggregate data. Returns a key for grouping data, a dictionary of aggregate data that can
        be summed when encountered again and a dictionary of static data that should be updated.

        E.g. number of tweets might be aggregated (summed over interval), but username of tweeter will be static.
        """
        group_by_key_bool = 'Tweet Text'

        tweet_text = post.get('text')
        # Expand tweet text if it is a retweet
        original_id = [post.get('id')]
        if any([ref.get("type") == "retweeted" for ref in post.get("referenced_tweets", [])]):
            retweeted_tweet = [t for t in post["referenced_tweets"] if t.get("type") == "retweeted"][0]
            retweeted_body = retweeted_tweet.get("text")
            original_id = [retweeted_tweet.get('id')]
            # Get user's username that was retweeted
            if retweeted_tweet.get('author_user') and retweeted_tweet.get('author_user').get('username'):
                tweet_text = "RT @" + retweeted_tweet.get("author_user", {}).get("username") + ": " + retweeted_body
            elif post.get('entities', {}).get('mentions', []):
                # Username may not always be in retweeted_tweet["author_user"]["username"] when user was removed/deleted
                # It will be in a mention and and the retweeted_tweet will still have an author id which we can use
                retweeting_users = [mention.get('username') for mention in post.get('entities', {}).get('mentions', [])
                                    if mention.get('id') == retweeted_tweet.get('author_id')]
                if retweeting_users:
                    # should only ever be one, but this verifies that there IS one and not NONE
                    tweet_text = "RT @" + retweeting_users[0] + ": " + retweeted_body

        # Quoted tweets text contains full retweeted text plus any additions... they also are "original" in that they add text
        # So I'm not touching them here, but that's open for discussion.

        sum_map = {
                    "Number of Identical Tweets": 1,
                }

        static_map = {}

        # This could be a static item, but there is an edge case of two or more tweets being identical and NOT sharing a
        list_map = {'Original (Re)Tweet ID': original_id}

        return group_by_key_bool, tweet_text, sum_map, static_map, list_map

    def modify_intervals(self, key, data):
        """
        Modify the intervals on a second loop once all the data has been collected. This is particularly useful for
        lists or sets of items that were collected.
        """
        data['Original (Re)Tweet ID'] = ', '.join(set(data['Original (Re)Tweet ID']))
        data.pop('Created at Timestamp')

        return data
