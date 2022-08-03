"""
Collapse post bodies into one long string
"""
import datetime
import numpy as np
from scipy import stats

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
    type = "twitter-user-stats"  # job type ID
    category = "Twitter Analysis"  # category
    title = "User statistics"  # title displayed in UI
    description = "Calculates the min, max, average, Q1, median, Q3, and trimmed mean for: number of tweets per user, urls per user, number of followers, number of users following, and user's total number of tweets per time interval"  # description displayed in UI
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

                # Add a counts for the respective timeframe
                if date not in intervals:
                    intervals[date] = {}

                if author not in intervals[date]:
                    intervals[date][author] = {
                        "Number of Tweets": 1,
                        "Total Retweets of Tweets": post.get('public_metrics').get('retweet_count'),
                        "Total Replies of Tweets": post.get('public_metrics').get('reply_count'),
                        "Total Likes of Tweets": post.get('public_metrics').get('like_count'),
                        "Total Quotes of Tweets": post.get('public_metrics').get('quote_count'),
                        "Number of URLs" : len([tag["expanded_url"] for tag in post.get("entities", {}).get("urls", [])]),
                        "Number of Hashtags": len([tag["tag"] for tag in post.get("entities", {}).get("hashtags", [])]),
                        "Number of Mentions": len([tag["username"] for tag in post.get("entities", {}).get("mentions", [])]),
                        "Number of Images": len([item["url"] for item in post.get("attachments", {}).get("media_keys", []) if
                           type(item) is dict and item.get("type") == "photo"]),
                        "Number User is Following": post.get("author_user").get('public_metrics').get('following_count'),
                        "Number Followers of User": post.get("author_user").get('public_metrics').get('followers_count'),
                        "Number of Tweets (account lifetime)": post.get("author_user").get('public_metrics').get('tweet_count'),
                        "Created at Timestamp": int(tweet_time.timestamp()),
                    }

                    # Convenience for easy adding to above
                    if not data_types:
                        data_types = list(intervals[date][author].keys())
                        self.dataset.log("Data being collected per author: %s" % data_types)

                else:
                    intervals[date][author]["Number of Tweets"] += 1
                    intervals[date][author]["Total Retweets of Tweets"] += post.get('public_metrics').get('retweet_count')
                    intervals[date][author]["Total Replies of Tweets"] += post.get('public_metrics').get('reply_count')
                    intervals[date][author]["Total Likes of Tweets"] += post.get('public_metrics').get('like_count')
                    intervals[date][author]["Total Quotes of Tweets"] += post.get('public_metrics').get('quote_count')
                    intervals[date][author]["Number of URLs"] += len([tag["expanded_url"] for tag in post.get("entities", {}).get("urls", [])])
                    intervals[date][author]["Number of Hashtags"] += len([tag["tag"] for tag in post.get("entities", {}).get("hashtags", [])])
                    intervals[date][author]["Number of Mentions"] += len([tag["username"] for tag in post.get("entities", {}).get("mentions", [])])
                    intervals[date][author]["Number of Images"] += len([item["url"] for item in post.get("attachments", {}).get("media_keys", []) if
                            type(item) is dict and item.get("type") == "photo"])

                    # These are user-specific metrics and not per tweet/post like above
                    # Methodology question: which stat is best to use? Most recent? Largest? Smallest? Likely they will be identical or minimally different.
                    # Using most recent for now.
                    if int(tweet_time.timestamp()) > intervals[date][author]["Created at Timestamp"]:
                        intervals[date][author]["Created at Timestamp"] = int(datetime.datetime.strptime(post["created_at"], "%Y-%m-%dT%H:%M:%S.000Z").timestamp())
                        intervals[date][author]["Number User is Following"] = post.get("author_user").get('public_metrics').get('following_count')
                        intervals[date][author]["Number Followers of User"] = post.get("author_user").get('public_metrics').get('followers_count')
                        intervals[date][author]["Number of Tweets (account lifetime)"] = post.get("author_user").get('public_metrics').get('tweet_count')

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
                for data_type in data_types:
                    row = {}
                    try:
                        values = np.array([int(item[data_type]) for item in data.values()])
                    except Exception as e:
                        self.dataset.log("data_type: %s" % str(data_type))
                        self.dataset.log("data: %s" % str(data))
                        self.dataset.log("Error: %s" % str(e))
                        raise e
                    row['min'] = values.min()
                    row['max'] = values.max()
                    row['mean'] = values.mean()
                    row['Q1'] = np.percentile(values, 25)
                    row['Q2'] = np.median(values)
                    row['Q3'] = np.percentile(values, 75)
                    row['25%_trimmed_mean'] = stats.trim_mean(values, 0.25)

                    rows.append({**{"date": interval, "data_type": data_type}, **row})

        self.write_csv_items_and_finish(rows)
