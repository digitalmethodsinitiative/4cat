"""
Twitter APIv2 aggregated user statistics
"""
import datetime
import numpy as np
from scipy import stats

from common.lib.helpers import UserInput, pad_interval, get_interval_descriptor
from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorException

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
    title = "Aggregated User Statistics"  # title displayed in UI
    description = "Calculates aggregate statistics for users grouped by interval (min, max, average, Q1, median, Q3, and trimmed mean): number of tweets per user, urls per user, number of followers, number of users following, and user's total number of tweets"  # description displayed in UI
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
        self.dataset.update_status("Processing posts")
        # Iterate through each post and collect data for each interval
        # Abstracted to use in child classes
        try:
            data_types, intervals = self.collect_intervals()
        except ProcessorException as e:
            self.dataset.update_status(str(e), is_final=True)
            self.dataset.update_status(0)
            return

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

    def collect_intervals(self):
        """
        Returns a list of the data_types gathered and a dict of intervals. Pads if self.parameters.get("pad") and
        self.parameters.get("timeframe") is not "all".
        """

        # OrderedDict because dates and headers should have order
        intervals = {}

        timeframe = self.parameters.get("timeframe")

        first_interval = "9999"
        last_interval = "0000"

        counter = 0
        data_types = None

        for post in self.source_dataset.iterate_items(self, bypass_map_item=True):
            try:
                tweet_time = datetime.datetime.strptime(post["created_at"], "%Y-%m-%dT%H:%M:%S.000Z")
                post["timestamp"] = tweet_time.strftime("%Y-%m-%d %H:%M:%S")
                date = get_interval_descriptor(post, timeframe)
            except ValueError as e:
                raise ProcessorException("%s, cannot count posts per %s" % (str(e), timeframe))

            author = post.get("author_user").get("username")
            if author == 'REDACTED':
                raise ProcessorException("Author information has been removed; cannot calculate user stats")

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
                    "Number of URLs": len([tag["expanded_url"] for tag in post.get("entities", {}).get("urls", [])]),
                    "Number of Hashtags": len([tag["tag"] for tag in post.get("entities", {}).get("hashtags", [])]),
                    "Number of Mentions": len(
                        [tag["username"] for tag in post.get("entities", {}).get("mentions", [])]),
                    "Number of Images": len(
                        [item["url"] for item in post.get("attachments", {}).get("media_keys", []) if
                         type(item) is dict and item.get("type") == "photo"]),
                    "Number User is Following": post.get("author_user").get('public_metrics').get('following_count'),
                    "Number Followers of User": post.get("author_user").get('public_metrics').get('followers_count'),
                    "Number of Tweets (account lifetime)": post.get("author_user").get('public_metrics').get(
                        'tweet_count'),
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
                intervals[date][author]["Number of URLs"] += len(
                    [tag["expanded_url"] for tag in post.get("entities", {}).get("urls", [])])
                intervals[date][author]["Number of Hashtags"] += len(
                    [tag["tag"] for tag in post.get("entities", {}).get("hashtags", [])])
                intervals[date][author]["Number of Mentions"] += len(
                    [tag["username"] for tag in post.get("entities", {}).get("mentions", [])])
                intervals[date][author]["Number of Images"] += len(
                    [item["url"] for item in post.get("attachments", {}).get("media_keys", []) if
                     type(item) is dict and item.get("type") == "photo"])

                # These are user-specific metrics and not per tweet/post like above
                # Methodology question: which stat is best to use? Most recent? Largest? Smallest? Likely they will be identical or minimally different.
                # Using most recent for now.
                if int(tweet_time.timestamp()) > intervals[date][author]["Created at Timestamp"]:
                    intervals[date][author]["Created at Timestamp"] = int(
                        datetime.datetime.strptime(post["created_at"], "%Y-%m-%dT%H:%M:%S.000Z").timestamp())
                    intervals[date][author]["Number User is Following"] = post.get("author_user").get(
                        'public_metrics').get('following_count')
                    intervals[date][author]["Number Followers of User"] = post.get("author_user").get(
                        'public_metrics').get('followers_count')
                    intervals[date][author]["Number of Tweets (account lifetime)"] = post.get("author_user").get(
                        'public_metrics').get('tweet_count')

            first_interval = min(first_interval, date)
            last_interval = max(last_interval, date)

            counter += 1

            if counter % 2500 == 0:
                self.dataset.update_status("Processed through " + str(counter) + " posts.")

        # pad interval if needed, this is useful if the result is to be
        # visualised as a histogram, for example
        if self.parameters.get("pad") and timeframe != "all":
            self.dataset.update_status("Padding intervals if empty...")
            missing, intervals = pad_interval(intervals, first_interval, last_interval)

            # Convert 0 values to dict
            for k, v in intervals.items():
                if isinstance(v, int):
                    intervals[k] = {}

        return data_types, intervals


class TwitterStatsVis(TwitterStats):
    """
    Collect Twitter statistics and create boxplots to visualise.
    """
    type = "twitter-user-stats-vis"  # job type ID
    category = "Twitter Analysis"  # category
    title = "Aggregated User Statistics Visualization"  # title displayed in UI
    description = "Gathers Aggregated User Statistics data and creates Box Plots visualising the spread of intervals. A large number of intervals will not properly display. "  # description displayed in UI
    extension = "png"  # extension of result file, used internally and in UI

    references = [
        "[matplotlib.pyplot.boxplot documentation](https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.boxplot.html)"
    ]

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        options = cls.options

        options["show_outliers"] = {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Show outliers in the boxplot",
            "tooltip": "Adds outliers (data points outside the whiskers; .7% of most extreme data if data was normally distributed) to the boxplot"
        }

        options["label_median"] = {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Add numerical median to top of each boxplot",
            "tooltip": "Adds the median value as a label to better compare data with large distributions of values"
        }

        return options

    def process(self):
        """
        This takes a 4CAT twitter dataset file as input, and outputs a csv.
        """
        import matplotlib.pyplot as plt

        self.dataset.update_status("Processing posts")
        data_types, intervals = self.collect_intervals()

        vis_data = {data_type: {'intervals': [], 'data': []} for data_type in data_types if
                    data_type not in ['Created at Timestamp']}

        counter = 0
        for interval, data in intervals.items():
            for data_type in data_types:
                try:
                    values = np.array([int(item[data_type]) for item in data.values()])
                except Exception as e:
                    self.dataset.log("data_type: %s" % str(data_type))
                    self.dataset.log("data: %s" % str(data))
                    self.dataset.log("Error: %s" % str(e))
                    raise e

                if data_type in vis_data.keys():
                    vis_data[data_type]['intervals'].append(interval)
                    vis_data[data_type]['data'].append(values)
                    counter += 1

        self.dataset.update_status("Creating visualisations")
        fig, axs = plt.subplots(len(vis_data.keys()), 1, figsize=(max(len(intervals)*1.5, 10), len(vis_data.keys()) * 10),
                                constrained_layout=True)

        for index, (data_type, data) in enumerate(vis_data.items()):
            axs[index].boxplot(data['data'], sym='+' if self.parameters.get("show_outliers") else '')
            axs[index].set_title(data_type)
            axs[index].set_xticklabels(data['intervals'])

            if self.parameters.get("label_median"):
                # Add medians to the boxplot
                pos = np.arange(len(data['data'])) + 1
                lower_labels = [str(np.median(plot_values)) for plot_values in data['data']]
                weights = ['bold', 'semibold']
                for tick, label in zip(range(len(data['data'])), axs[index].get_xticklabels()):
                    k = tick % 2
                    axs[index].text(pos[tick], 0.99, lower_labels[tick],
                                    transform=axs[index].get_xaxis_transform(),
                                    horizontalalignment='center', size='x-small',
                                    weight=weights[k])

        # finish up
        self.dataset.update_status("Saving result")
        plt.savefig(str(self.dataset.get_results_path()))
        self.dataset.update_status("Finished")
        self.dataset.finish(counter)
