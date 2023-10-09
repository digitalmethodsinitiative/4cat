"""
Twitter APIv2 general tweet statistics
"""
from common.lib.helpers import UserInput
from processors.twitter.base_twitter_stats import TwitterStatsBase

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class TwitterStats(TwitterStatsBase):
    """
    Collect Twitter statistics. Built to emulate TCAT statistic.
    """
    type = "twitter-0-stats"  # job type ID
    category = "Twitter Analysis"  # category
    title = "Twitter Statistics"  # title displayed in UI
    description = "Contains the number of tweets, number of tweets with links, number of tweets with hashtags, number of tweets with mentions, number of retweets, and number of replies"  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    options = {
        "timeframe": {
            "type": UserInput.OPTION_CHOICE,
            "default": "month",
            "options": {"all": "Overall", "year": "Year", "month": "Month", "week": "Week", "day": "Day",
                        "hour": "Hour", "minute": "Minute"},
            "help": "Produce counts per"
        },
        "pad": {
            "type": UserInput.OPTION_TOGGLE,
            "default": True,
            "help": "Include dates where the count is zero",
            "tooltip": "Makes the counts continuous. For example, if there are posts in May and July but not June, June will be included with 0 posts."
        }
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
        Maps a post to collect aggregate data. Returns a key for grouping data, a dictionary of sum data that can
        be added up when encountered again, a dictionary of static data that should be updated, and a dictionary of
        list data that should be appended to.

        E.g. number of tweets might be summed over interval, a username of tweeter will be static, and a list of
        hashtags used might be collected (appended to a list).
        """
        # To further group intervals, name the category (e.g. "hashtags")
        group_by_key_category = False

        # Can be a string (representing the record e.g. author_name) or a list of strings (which will each get a separate record e.g. list of hashtags)
        group_by_keys = None

        # Use set as hashtag/mention is either in tweet or not AND adding it from the reference tweet should not duplicate
        hashtags = set([tag["tag"] for tag in post.get("entities", {}).get("hashtags", [])])
        mentions = set([tag["username"] for tag in post.get("entities", {}).get("mentions", [])])
        num_urls = len([tag["expanded_url"] for tag in post.get("entities", {}).get("urls", [])])
        num_images = len(
            [item["url"] for item in post.get("attachments", {}).get("media_keys", []) if
             type(item) is dict and item.get("type") == "photo"])

        # Update hashtags and mentions
        for ref_tweet in post.get('referenced_tweets', []):
            if ref_tweet.get('type') in ['retweeted', 'quoted']:
                hashtags.update([tag['tag'] for tag in ref_tweet.get('entities', {}).get('hashtags', [])])
                mentions.update([tag['username'] for tag in ref_tweet.get('entities', {}).get('mentions', [])])

        # Map the data in the post to either be summed (by grouping and interval)
        sum_map = {
            "Number of Tweets": 1,
            "Number of Tweets with links": 1 if num_urls > 0 else 0,
            "Number of Tweets with hashtags": 1 if len(hashtags) > 0 else 0,
            "Number of Tweets with mentions": 1 if len(mentions) > 0 else 0,
            "Number of Tweets with images": 1 if num_images > 0 else 0,
            "Number of Retweets": 1 if any([ref.get("type") == "retweeted" for ref in post.get("referenced_tweets", [])]) else 0,
            "Number of Replies": 1 if any([ref.get("type") == "replied_to" for ref in post.get("referenced_tweets", [])]) else 0,
            "Number of Quotes": 1 if any([ref.get("type") == "quoted" for ref in post.get("referenced_tweets", [])]) else 0,
        }
        # These are user-specific metrics and not per tweet/post like above
        static_map = {}
        # These keys contain lists of items (e.g. hashtags)
        list_map = {
            "Authors": [str(post.get("author_user").get("username"))],
            # These are counted BY value so a list should be used
            "Hashtags": list(hashtags),
            "Mentions": list(mentions),
        }

        return group_by_key_category, group_by_keys, sum_map, static_map, list_map

    def padding_map(self):
        """
        Returns the base dictionary to be used if there are no values in a certain interval.
        """
        return {
            "Number of Tweets": 0,
            "Number of Tweets with links": 0,
            "Number of Tweets with hashtags": 0,
            "Number of Tweets with mentions": 0,
            "Number of Tweets with images": 0,
            "Number of Retweets": 0,
            "Number of Replies": 0,
            "Number of Quotes": 0,
            "Authors": [],
            "Hashtags": [],
            "Mentions": [],
        }

    def modify_intervals(self, key, data):
        """
        Modify the intervals on a second loop once all the data has been collected. This is particularly useful for
        lists or sets of items that were collected.
        """
        # Count the number of unique authors
        data['Number of unique Authors'] = len(set(data['Authors']))

        # Tally authors, hashtags, and mentions
        top_authors = {}
        for author in data['Authors']:
            if author in top_authors:
                top_authors[author] += 1
            else:
                top_authors[author] = 1
        sorted_authors = ["%s: %s" % (k, v) for k, v in
                          sorted(top_authors.items(), key=lambda item: item[1], reverse=True)]
        data["Top 10 authors"] = ', '.join(sorted_authors[:10])

        top_hashtags = {}
        for tag in data['Hashtags']:
            if tag in top_hashtags:
                top_hashtags[tag] += 1
            else:
                top_hashtags[tag] = 1
        sorted_tags = ["%s: %s" % (k, v) for k, v in
                       sorted(top_hashtags.items(), key=lambda item: item[1], reverse=True)]
        data["Top 10 hashtags"] = ', '.join(sorted_tags[:10])

        top_mentions = {}
        for mention in data['Mentions']:
            if mention in top_mentions:
                top_mentions[mention] += 1
            else:
                top_mentions[mention] = 1
        sorted_mentions = ["%s: %s" % (k, v) for k, v in
                           sorted(top_mentions.items(), key=lambda item: item[1], reverse=True)]
        data["Top 10 mentions"] = ', '.join(sorted_mentions[:10])

        # Remove unnecessary keys
        data.pop('Created at Timestamp')
        data.pop("Authors")
        data.pop("Hashtags")
        data.pop("Mentions")

        return data
