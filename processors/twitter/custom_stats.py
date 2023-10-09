"""
Twitter APIv2 custom statistics
"""
from common.lib.exceptions import ProcessorException
from common.lib.helpers import UserInput
from processors.twitter.base_twitter_stats import TwitterStatsBase

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class TwitterCustomStats(TwitterStatsBase):
    """
    Collect Twitter statistics. Build to emulate TCAT statistic.
    """
    type = "twitter-1-custom-stats"  # job type ID
    category = "Twitter Analysis"  # category
    title = "Custom Statistics"  # title displayed in UI
    description = "Group tweets by category and count tweets per timeframe to collect aggregate group statistics.\nFor retweets and quotes, hashtags, mentions, URLs, and images from the original tweet are included in the retweet/quote. Data on public metrics (e.g., number of retweets or likes of tweets) are as of the time the data was collected."  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    sorted = 'Number of Tweets'

    options = {
        "category": {
            "type": UserInput.OPTION_CHOICE,
            "default": "user",
            "options": {
                "user": "Tweet Author",
                "type": "Tweet type (tweet, quote, retweet, reply)",
                "source": "Source of Tweet",
                "place": "Place Name (if known)",
                "language": "Language (Twitter's guess)",
            },
            "help": "Group by"
        },
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
        # Resolve category
        category = self.parameters.get("category")
        if category == 'user':
            group_by_key_bool = 'Tweet Author'
            post_category = post.get("author_user").get("username")
            if post_category == 'REDACTED':
                raise ProcessorException("Author information has been removed; cannot calculate user stats")
        elif category == 'type':
            group_by_key_bool = 'Tweet type'
            # Identify tweet type(s)
            tweet_types = [ref.get("type") for ref in post.get("referenced_tweets", [])]
            type_results = ['retweet' if "retweeted" in tweet_types else '',
                            'quote' if "quoted" in tweet_types else '',
                            'reply' if "replied_to" in tweet_types else '']
            type_results.sort()
            post_category = '-'.join([r for r in type_results if r]) if any(type_results) else 'tweet'
        elif category == 'source':
            group_by_key_bool = 'Source of Tweet'
            post_category = post.get("source", 'Unknown')
        elif category == 'place':
            group_by_key_bool = 'Place Name'
            post_category = post.get('geo', {}).get('place', {}).get('full_name', 'Unknown')
        elif category == 'language':
            group_by_key_bool = 'Language'
            post_category = post.get("lang", "Unknown")
        else:
            raise ProcessorException("Category '%s' not yet implemented" % category)

        # Use set as hashtag/mention is either in tweet or not AND adding it from the reference tweet should not duplicate
        hashtags = set([tag["tag"] for tag in post.get("entities", {}).get("hashtags", [])])
        mentions = set([tag["username"] for tag in post.get("entities", {}).get("mentions", [])])
        urls = set([tag["expanded_url"] for tag in post.get("entities", {}).get("urls", [])])
        images = set([item["url"] for item in post.get("attachments", {}).get("media_keys", []) if
                         type(item) is dict and item.get("type") == "photo"])

        # Update hashtags and mentions
        for ref_tweet in post.get('referenced_tweets', []):
            if ref_tweet.get('type') in ['retweeted', 'quoted']:
                hashtags.update([tag['tag'] for tag in ref_tweet.get('entities', {}).get('hashtags', [])])
                mentions.update([tag['username'] for tag in ref_tweet.get('entities', {}).get('mentions', [])])
                urls.update([tag["expanded_url"] for tag in post.get("entities", {}).get("urls", [])])
                images.update([item["url"] for item in post.get("attachments", {}).get("media_keys", []) if
                         type(item) is dict and item.get("type") == "photo"])

        sum_map = {
                    "Number of Tweets per %s" % group_by_key_bool: 1,
                    "Number of Retweets": 1 if any(
                        [ref.get("type") == "retweeted" for ref in post.get("referenced_tweets", [])]) else 0,
                    "Number of Replies": 1 if any(
                        [ref.get("type") == "replied_to" for ref in post.get("referenced_tweets", [])]) else 0,
                    "Number of Quotes": 1 if any(
                        [ref.get("type") == "quoted" for ref in post.get("referenced_tweets", [])]) else 0,
                    "Total Retweets of grouped Tweets (public metrics)": post.get('public_metrics').get('retweet_count'),
                    "Total Replies to grouped Tweets (public metrics)": post.get('public_metrics').get('reply_count'),
                    "Total Likes of grouped Tweets (public metrics)": post.get('public_metrics').get('like_count'),
                    "Total Quotes of grouped Tweets (public metrics)": post.get('public_metrics').get('quote_count'),
                    "Number of Tweets w/ Hashtags": 1 if len(hashtags) > 0 else 0,
                    "Number of Tweets w/ Mentions": 1 if len(mentions) > 0 else 0,
                    "Number of Tweets w/ URLs": 1 if len(urls) > 0 else 0,
                    "Number of Tweets w/ Images": 1 if len(images) > 0 else 0,
                }

        static_map = {}

        list_map = {
            "Mentions": list(mentions),
            "Hashtags": list(hashtags),
            "URLs": list(urls),
            "Images": list(images),
        }

        self.sorted = "Number of Tweets per %s" % group_by_key_bool

        return group_by_key_bool, post_category, sum_map, static_map, list_map

    def modify_intervals(self, key, data):
        """
        Modify the intervals on a second loop once all the data has been collected. This is particularly useful for
        lists or sets of items that were collected.
        """
        # Collect Aggregate data
        data['Total number of Hashtags'] = len(data['Hashtags'])
        data['Number of unique Hashtags used in Tweets'] = len(set(data['Hashtags']))
        data['Total number of Mentions'] = len(data['Mentions'])
        data['Number of unique Mentions used in Tweets'] = len(set(data['Mentions']))
        data['Total number of URLs'] = len(data['URLs'])
        data['Number of unique URLs used in Tweets'] = len(set(data['URLs']))
        data['Total number of Images'] = len(data['Images'])
        data['Number of unique Images used in Tweets'] = len(set(data['Images']))

        # Delete unused fields
        data.pop('URLs')
        data.pop('Mentions')
        data.pop('Hashtags')
        data.pop('Images')
        data.pop('Created at Timestamp')

        return data
