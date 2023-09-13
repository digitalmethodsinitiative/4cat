"""
Twitter APIv2 hashtag statistics
"""
from common.lib.helpers import UserInput
from processors.twitter.base_twitter_stats import TwitterStatsBase

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class TwitterHashtagStats(TwitterStatsBase):
    """
    Collect Twitter statistics. Build to emulate TCAT statistic.
    """
    type = "twitter-hashtag-stats"  # job type ID
    category = "Twitter Analysis"  # category
    title = "Hashtag Statistics"  # title displayed in UI
    description = "Lists by hashtag how many tweets contain hashtags, how many times those tweets have been retweeted/replied to/liked/quoted, and information about unique users and hashtags used alongside each hashtag.\nFor retweets and quotes, hashtags from the original tweet are included in the retweet/quote."  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    sorted = 'Number of Tweets containing Hashtag'

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
        group_by_key_bool = 'hashtag'

        # Use set as hashtag/mention is either in tweet or not AND adding it from the reference tweet should not duplicate
        hashtags = set([tag["tag"] for tag in post.get("entities", {}).get("hashtags", [])])
        mentions = set([tag["username"] for tag in post.get("entities", {}).get("mentions", [])])

        # Update hashtags and mentions
        for ref_tweet in post.get('referenced_tweets', []):
            if ref_tweet.get('type') in ['retweeted', 'quoted']:
                hashtags.update([tag['tag'] for tag in ref_tweet.get('entities', {}).get('hashtags', [])])
                mentions.update([tag['username'] for tag in ref_tweet.get('entities', {}).get('mentions', [])])

        sum_map = {
                    "Number of Tweets containing Hashtag": 1,
                    "Number of Retweets of Tweets w/ Hashtag": post.get('public_metrics').get('retweet_count'),
                    "Number of Replies to Tweets w/ Hashtag": post.get('public_metrics').get('reply_count'),
                    "Number of Likes of Tweets w/ Hashtag": post.get('public_metrics').get('like_count'),
                    "Number of Quotes of Tweets w/ Hashtag": post.get('public_metrics').get('quote_count'),
                }

        static_map = {}

        list_map = {
            'Users of Hashtag': [post["author_user"]["username"]],
            "Mentions": list(mentions),
            "Hashtags": list(hashtags),
        }

        return group_by_key_bool, hashtags, sum_map, static_map, list_map

    def modify_intervals(self, key, data):
        """
        Modify the intervals on a second loop once all the data has been collected. This is particularly useful for
        lists or sets of items that were collected.
        """
        # Ensure that all lists are sets (i.e. contain only unique values)
        data['Users of Hashtag'] = set(data['Users of Hashtag'])
        data['Mentions'] = set(data['Mentions'])
        data['Hashtags'] = set(data['Hashtags'])
        # Remove key (i.e. this particular hashtag) from set of hashtags in a given tweet
        data['Hashtags'].remove(key)

        # Collect Aggregate data
        data['Number of Unique Users w/ Tweets using Hashtag'] = len(data['Users of Hashtag'])
        data['Number of Unique Mentions used in Tweets w/ Hashtag'] = len(data['Mentions'])
        data['Number of Other Unique Hashtags used in Tweets w/ Hashtag'] = len(data['Hashtags'])

        # Rename and format lists
        data['Users w/ Tweets containing Hashtag'] = ', '.join(data.pop('Users of Hashtag'))
        data['Mentions in Tweets containing Hashtag'] = ', '.join(data.pop('Mentions'))
        data['Other Hashtags in Tweets containing Hashtag'] = ', '.join(data.pop('Hashtags'))

        data.pop('Created at Timestamp')

        return data
