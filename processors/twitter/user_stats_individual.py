"""
Twitter APIv2 individual user statistics
"""
import datetime

from common.lib.helpers import UserInput, pad_interval, get_interval_descriptor
from backend.abstract.processor import BasicProcessor

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class TwitterStats(BasicProcessor):
    """
    Collect Twitter statistics. Build to emulate TCAT statistic.
    """
    type = "twitter-user-stats-individual"  # job type ID
    category = "Twitter Analysis"  # category
    title = "Individual User Statistics"  # title displayed in UI
    description = "Lists users and their number of tweets, number of followers, number of friends, how many times they are listed, their UTC time offset, whether the user has a verified account and how many times they appear in the data set."  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    options = {
        "timeframe": {
            "type": UserInput.OPTION_CHOICE,
            "default": "month",
            "options": {"all": "Overall", "year": "Year", "month": "Month", "week": "Week", "day": "Day",
                        "hour": "Hour", "minute": "Minute"},
            "help": "Produce counts per"
        },
        # Padding would require padding for all authors/users to make any sense! That's a bit more complex.
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

    def process(self):
        """
        This takes a 4CAT twitter dataset file as input, and outputs a csv.
        """
        # OrderedDict because dates and headers should have order
        intervals = {}

        timeframe = self.parameters.get("timeframe")

        first_interval = "9999"
        last_interval = "0000"

        self.dataset.update_status("Processing posts")
        with self.dataset.get_results_path().open("w") as results:
            counter = 0
            data_types = None

            for post in self.source_dataset.iterate_items(self, bypass_map_item=True):
                try:
                    tweet_time = datetime.datetime.strptime(post["created_at"], "%Y-%m-%dT%H:%M:%S.000Z")
                    post["timestamp"] = tweet_time.strftime("%Y-%m-%d %H:%M:%S")
                    date = get_interval_descriptor(post, timeframe)
                except ValueError as e:
                    self.dataset.update_status("%s, cannot count posts per %s" % (str(e), timeframe), is_final=True)
                    self.dataset.update_status(0)
                    return

                author = post.get("author_user").get("username")
                num_urls = len([tag["expanded_url"] for tag in post.get("entities", {}).get("urls", [])])
                num_hashtags = len([tag["tag"] for tag in post.get("entities", {}).get("hashtags", [])])
                num_mentions = len(
                            [tag["username"] for tag in post.get("entities", {}).get("mentions", [])])
                num_images = len(
                            [item["url"] for item in post.get("attachments", {}).get("media_keys", []) if
                             type(item) is dict and item.get("type") == "photo"])

                # Add a counts for the respective timeframe
                if date not in intervals:
                    intervals[date] = {}

                if author not in intervals[date]:
                    intervals[date][author] = {
                        "User ID": post["author_user"]["id"],
                        "Username": post["author_user"]["username"],
                        "Name": post["author_user"]["name"],
                        "Location": post["author_user"].get("location"),
                        "Verified": post["author_user"].get("verified"),
                        "Number User is Following (at time of collection)": post.get("author_user").get('public_metrics').get(
                            'following_count'),
                        "Number Followers of User (at time of collection)": post.get("author_user").get('public_metrics').get(
                            'followers_count'),
                        "Total Number of Tweets (at time of collection)": post.get("author_user").get('public_metrics').get(
                            'tweet_count'),

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

                        # Probably do not need to report this, but it is used to find the most recent record
                        "Created at Timestamp": int(tweet_time.timestamp()),
                    }

                    # Convenience for easy adding to above
                    if not data_types:
                        data_types = list(intervals[date][author].keys())
                        self.dataset.log("Data being collected per author: %s" % data_types)

                else:
                    intervals[date][author]["Tweets (in interval)"] += 1
                    intervals[date][author]["Retweets (in interval)"] += 1 if any(
                        [ref.get("type") == "retweeted" for ref in post.get("referenced_tweets", [])]) else 0
                    intervals[date][author]["Quotes (in interval)"] += 1 if any(
                        [ref.get("type") == "quoted" for ref in post.get("referenced_tweets", [])]) else 0
                    intervals[date][author]["Replies (in interval)"] += 1 if any(
                        [ref.get("type") == "replied_to" for ref in post.get("referenced_tweets", [])]) else 0
                    intervals[date][author]["Number of Tweets with URL (in interval)"] += 1 if num_urls > 0 else 0
                    intervals[date][author]["Total Number of URLs Used (in interval)"] += num_urls
                    intervals[date][author]["Number of Tweets with Hashtag (in interval)"] += 1 if num_hashtags > 0 else 0
                    intervals[date][author]["Total Number of Hashtags Used (in interval)"] += num_hashtags
                    intervals[date][author]["Number of Tweets with Mention (in interval)"] += 1 if num_mentions else 0
                    intervals[date][author]["Total Number of Mentions Used (in interval)"] += num_mentions
                    intervals[date][author]["Number of Tweets with Image (in interval)"] += 1 if num_images else 0
                    intervals[date][author]["Total Number of Images Used (in interval)"] += num_images

                    intervals[date][author]["Total Retweets of User's Tweets (in interval)"] += post.get('public_metrics').get('retweet_count')
                    intervals[date][author]["Total Replies of User's Tweets (in interval)"] += post.get('public_metrics').get('reply_count')
                    intervals[date][author]["Total Likes of User's Tweets (in interval)"] += post.get('public_metrics').get('like_count')
                    intervals[date][author]["Total Quotes of User's Tweets (in interval)"] += post.get('public_metrics').get('quote_count')

                    # These are user-specific metrics and not per tweet/post like above
                    # Methodology question: which stat is best to use? Most recent? Largest? Smallest? Likely they will be identical or minimally different.
                    # Using most recent for now.
                    if int(tweet_time.timestamp()) > intervals[date][author]["Created at Timestamp"]:
                        intervals[date][author]["Created at Timestamp"] = int(datetime.datetime.strptime(post["created_at"], "%Y-%m-%dT%H:%M:%S.000Z").timestamp())
                        intervals[date][author]["User ID"] = post["author_user"]["id"]
                        intervals[date][author]["User Name"] = post["author_user"]["username"]
                        intervals[date][author]["Name"] = post["author_user"]["name"]
                        intervals[date][author]["Location"] = post["author_user"].get("location")
                        intervals[date][author]["Verified"] =post["author_user"].get("verified")
                        intervals[date][author]["Number User is Following (at time of collection)"] = post.get("author_user").get('public_metrics').get('following_count')
                        intervals[date][author]["Number Followers of User (at time of collection)"] = post.get("author_user").get('public_metrics').get('followers_count')
                        intervals[date][author]["Total Number of Tweets (at time of collection)"] = post.get("author_user").get('public_metrics').get('tweet_count')

                first_interval = min(first_interval, date)
                last_interval = max(last_interval, date)

                counter += 1

                if counter % 2500 == 0:
                    self.dataset.update_status("Processed through " + str(counter) + " posts.")

            # pad interval if needed, this is useful if the result is to be
            # visualised as a histogram, for example
            if self.parameters.get("pad") and timeframe != "all":
                missing, intervals = pad_interval(intervals, first_interval, last_interval)

                # Convert 0 values to dict
                for k, v in intervals.items():
                    if isinstance(v, int):
                        intervals[k] = {}

            rows = []
            for interval, data in intervals.items():
                for author, author_data in data.items():
                    rows.append({**{"date": interval}, **author_data})

        self.write_csv_items_and_finish(rows)
