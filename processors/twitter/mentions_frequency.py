"""
Twitter APIv2 hashtag statistics
"""
from common.lib.helpers import UserInput
from processors.twitter.base_twitter_stats import TwitterStatsBase

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class TwitterMentionFrequency(TwitterStatsBase):
    """
    Collect Twitter statistics. Build to emulate TCAT statistic.
    """
    type = "twitter-mention-frequency"  # job type ID
    category = "Twitter Analysis"  # category
    title = "Mention Frequency"  # title displayed in UI
    description = "Calculates the number of times a user is mentioned by others in a given interval. \nFor retweets and quotes, hashtags from the original tweet are included in the retweet/quote."  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    sorted = "Number of Tweets mentioning user"

    options = {
        "timeframe": {
            "type": UserInput.OPTION_CHOICE,
            "default": "month",
            "options": {"all": "Overall", "year": "Year", "month": "Month", "week": "Week", "day": "Day",
                        "hour": "Hour", "minute": "Minute"},
            "help": "Produce counts per"
        },

        # Padding would require padding for all authors/users to make any sense! That's a bit more complex that existing code allows
        # Disabling for now
        # "pad": {
        #     "type": UserInput.OPTION_TOGGLE,
        #     "default": True,
        #     "help": "Include dates where the count is zero",
        #     "tooltip": "Makes the counts continuous. For example, if there are posts in May and July but not June, June will be included with 0 posts."
        # }
    }

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Determine if processor is compatible with dataset

        :param module: Dataset or processor to determine compatibility with
        """
        return module.type == "twitterv2-search"

    def map_data(self, post):
        """
        Maps a post to collect aggregate data. Returns a key for grouping data, a dictionary of aggregate data that can
        be summed when encountered again and a dictionary of static data that should be updated.

        E.g. number of tweets might be aggregated (summed over interval), but username of tweeter will be static.
        """
        group_by_key_bool = 'username'

        mentions = set([tag["username"] for tag in post.get("entities", {}).get("mentions", [])])

        # Add referenced tweet data to the collected information
        for ref_tweet in post.get('referenced_tweets', []):
            if ref_tweet.get('type') in ['retweeted', 'quoted']:
                mentions.update([tag['username'] for tag in ref_tweet.get('entities', {}).get('mentions', [])])

        sum_map = {
                    "Number of Tweets mentioning user": 1,
                }

        static_map = {}

        list_map = {}

        return group_by_key_bool, mentions, sum_map, static_map, list_map

    def modify_intervals(self, key, data):
        """
        Modify the intervals on a second loop once all the data has been collected. This is particularly useful for
        lists or sets of items that were collected.
        """
        data.pop('Created at Timestamp')

        return data
