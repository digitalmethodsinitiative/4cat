"""
Twitter APIv2 individual user statistics
"""
from common.lib.helpers import UserInput
from processors.twitter.base_twitter_stats import TwitterStatsBase
from common.lib.exceptions import ProcessorException

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class TwitterStats(TwitterStatsBase):
    """
    Collect Twitter statistics. Build to emulate TCAT statistic.
    """
    type = "twitter-user-stats-individual"  # job type ID
    category = "Twitter Analysis"  # category
    title = "Individual User Statistics"  # title displayed in UI
    description = "Lists users and their number of tweets, number of followers, number of friends, how many times they are listed, their UTC time offset, whether the user has a verified account and how many times they appear in the data set."  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    sorted = "Tweets (in interval)"

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
        group_by_key_category = "Username"
        group_by_key = str(post.get("author_user").get("username"))
        if group_by_key == 'REDACTED':
            # Cannot calculate user stats when users have been removed!
            raise ProcessorException("Author information has been removed; cannot calculate user stats")

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

        num_urls = len(urls)
        num_hashtags = len(hashtags)
        num_mentions = len(mentions)
        num_images = len(
            [item["url"] for item in post.get("attachments", {}).get("media_keys", []) if
             type(item) is dict and item.get("type") == "photo"])

        sum_map = {
                    "Tweets (in interval)": 1,
                    "Retweets (in interval)": 1 if any([ref.get("type") == "retweeted" for ref in post.get("referenced_tweets", [])]) else 0,
                    "Quotes (in interval)": 1 if any([ref.get("type") == "quoted" for ref in post.get("referenced_tweets", [])]) else 0,
                    "Replies (in interval)": 1 if any(
                        [ref.get("type") == "replied_to" for ref in post.get("referenced_tweets", [])]) else 0,
                    "Number of Tweets with URL (in interval)": 1 if num_urls > 0 else 0,
                    "Total Number of URLs Used (in interval)": num_urls,
                    "Number of Tweets with Hashtag (in interval)": 1 if num_hashtags > 0 else 0,
                    "Total Number of Hashtags Used (in interval)": num_hashtags,
                    "Number of Tweets with Mention (in interval)": 1 if num_mentions > 0 else 0,
                    "Total Number of Mentions Used (in interval)": num_mentions,
                    "Number of Tweets with Image (in interval)": 1 if num_images > 0 else 0,
                    "Total Number of Images Used (in interval)": num_images,
                    "Total Retweets of User's Tweets (in interval)": post.get('public_metrics').get('retweet_count'),
                    "Total Replies of User's Tweets (in interval)": post.get('public_metrics').get('reply_count'),
                    "Total Likes of User's Tweets (in interval)": post.get('public_metrics').get('like_count'),
                    "Total Quotes of User's Tweets (in interval)": post.get('public_metrics').get('quote_count'),
                }
        # These are user-specific metrics and not per tweet/post like above
        static_map = {
                    "User ID": post["author_user"]["id"],
                    "Name": post["author_user"]["name"],
                    "Location": post["author_user"].get("location"),
                    "Verified": post["author_user"].get("verified"),
                    "Number User is Following (at time of collection)": post.get("author_user").get('public_metrics').get(
                        'following_count'),
                    "Number Followers of User (at time of collection)": post.get("author_user").get('public_metrics').get(
                        'followers_count'),
                    "Total Number of Tweets (at time of collection)": post.get("author_user").get('public_metrics').get(
                        'tweet_count'),
                }
        list_map = {}

        return group_by_key_category, group_by_key, sum_map, static_map, list_map
