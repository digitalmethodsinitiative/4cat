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
    type = "twitter-source-stats"  # job type ID
    category = "Twitter Analysis"  # category
    title = "Source Statistics"  # title displayed in UI
    description = "Lists by source of tweet how many tweets contain hashtags, how many times those tweets have been retweeted/replied to/liked/quoted, and information about unique users and hashtags used alongside each hashtag.\nFor retweets and quotes, hashtags from the original tweet are included in the retweet/quote."  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    sorted = 'Number of Tweets from Source'

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
        group_by_key_bool = 'Source'

        # Use set as hashtag/mention is either in tweet or not AND adding it from the reference tweet should not duplicate
        hashtags = set([tag["tag"] for tag in post.get("entities", {}).get("hashtags", [])])
        mentions = set([tag["username"] for tag in post.get("entities", {}).get("mentions", [])])
        urls = set([tag["expanded_url"] for tag in post.get("entities", {}).get("urls", [])])

        # Update hashtags and mentions
        for ref_tweet in post.get('referenced_tweets', []):
            if ref_tweet.get('type') in ['retweeted', 'quoted']:
                hashtags.update([tag['tag'] for tag in ref_tweet.get('entities', {}).get('hashtags', [])])
                mentions.update([tag['username'] for tag in ref_tweet.get('entities', {}).get('mentions', [])])
                urls.update([tag["expanded_url"] for tag in post.get("entities", {}).get("urls", [])])

        sum_map = {
                    "Number of Tweets from Source": 1,
                    "Number of Retweets of Tweets": post.get('public_metrics').get('retweet_count'),
                    "Number of Replies to Tweets": post.get('public_metrics').get('reply_count'),
                    "Number of Likes of Tweets": post.get('public_metrics').get('like_count'),
                    "Number of Quotes of Tweets": post.get('public_metrics').get('quote_count'),
                    "Number of Tweets w/ Hashtags": 1 if len(hashtags) > 0 else 0,
                    "Number of Tweets w/ URLs": 1 if len(urls) > 0 else 0,
                    "Number of Tweets w/ Mentions": 1 if len(mentions) > 0 else 0,
                }

        static_map = {}

        list_map = {
            "Mentions": list(mentions),
            "Hashtags": list(hashtags),
            "URLs": list(urls),
        }

        return group_by_key_bool, post.get("source", "None"), sum_map, static_map, list_map

    def modify_intervals(self, key, data):
        """
        Modify the intervals on a second loop once all the data has been collected. This is particularly useful for
        lists or sets of items that were collected.
        """
        # Ensure that all lists are sets (i.e. contain only unique values)
        data['Mentions'] = set(data['Mentions'])
        data['Hashtags'] = set(data['Hashtags'])
        data['URLs'] = set(data['URLs'])

        # Collect Aggregate data
        data['Number of unique Mentions used in Tweets'] = len(data['Mentions'])
        data['Number of unique Hashtags used in Tweets'] = len(data['Hashtags'])
        data['Number of unique URLs used in Tweets'] = len(data['URLs'])

        # Delete unused fields
        data.pop('URLs')
        data.pop('Mentions')
        data.pop('Hashtags')
        data.pop('Created at Timestamp')

        return data
