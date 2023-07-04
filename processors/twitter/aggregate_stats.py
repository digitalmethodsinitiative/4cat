"""
Twitter APIv2 aggregated user statistics
"""
import datetime
import numpy as np
from scipy import stats

from common.lib.helpers import UserInput, pad_interval, get_interval_descriptor
from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorException

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class TwitterAggregatedStats(BasicProcessor):
    """
    Collect Twitter statistics. Build to emulate TCAT statistic.
    """
    type = "twitter-aggregated-stats"  # job type ID
    category = "Twitter Analysis"  # category
    title = "Aggregated Statistics"  # title displayed in UI
    description = "Group tweets by category and count tweets per timeframe and then calculate aggregate group statistics (i.e. min, max, average, Q1, median, Q3, and trimmed mean): number of tweets, urls, hashtags, mentions, etc. \nUse for example to find the distribution of the number of tweets per author and compare across time."  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    num_of_different_categories = None

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

        # Format header
        if len(self.num_of_different_categories) <= 5:
            header_subtext = ', '.join(self.num_of_different_categories)
        else:
            header_subtext = '%i total' % len(self.num_of_different_categories)
        header_category = '%s (%s)' % (self.parameters.get("category"), str(header_subtext))

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

                rows.append({**{"date": interval, 'category': header_category, "data_type": data_type}, **row})

        if bool(self.dataset.top_parent().parameters.get("pseudonymise", None)):
            self.dataset.update_status('Dataset previously was pseudonymised; not all metrics could be calculated.', is_final=True)
        self.write_csv_items_and_finish(rows)

    def collect_intervals(self):
        """
        Returns a list of the data_types gathered and a dict of intervals. Pads if self.parameters.get("pad") and
        self.parameters.get("timeframe") is not "all".
        """

        # OrderedDict because dates and headers should have order
        intervals = {}

        category = self.parameters.get("category")
        self.num_of_different_categories = set()

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

            if category == 'user':
                post_category = post.get("author_user").get("username")
                if post_category == 'REDACTED':
                    raise ProcessorException("Author information has been removed; cannot calculate user stats")
            elif category == 'type':
                # Identify tweet type(s)
                tweet_types = [ref.get("type") for ref in post.get("referenced_tweets", [])]
                type_results = ['retweet' if "retweeted" in tweet_types else '',
                                'quote' if "quoted" in tweet_types else '',
                                'reply' if "replied_to" in tweet_types else '']
                type_results.sort()
                post_category = '-'.join([r for r in type_results if r]) if any(type_results) else 'tweet'
            elif category == 'source':
                post_category = post.get("source", 'Unknown')
            elif category == 'place':
                post_category = post.get('geo', {}).get('place', {}).get('full_name', 'Unknown')
            elif category == 'language':
                post_category = post.get("lang", "Unknown")
            else:
                raise ProcessorException("Category '%s' not yet implemented" % category)
            self.num_of_different_categories.add(post_category)

            # Add a counts for the respective timeframe
            if date not in intervals:
                intervals[date] = {}

            post_values = {
                    "Number of Tweets per %s" % category: 1,
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
                    "Created at Timestamp": int(tweet_time.timestamp()),
                }

            # Ensure post_values are integers
            for k, v in list(post_values.items()):
                # Remove None values
                if v is None:
                    post_values.pop(k)
                else:
                    post_values[k] = int(v)

            if post_category not in intervals[date]:
                intervals[date][post_category] = {**post_values}

                # Convenience for easy adding to above
                if not data_types:
                    data_types = list(intervals[date][post_category].keys())
                    self.dataset.log("Data being collected: %s" % data_types)
            else:
                for key, value in post_values.items():
                    if key == "Created at Timestamp":
                        # Skip timestamp
                        pass
                    intervals[date][post_category][key] += int(value)

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


class TwitterAggregatedStatsVis(TwitterAggregatedStats):
    """
    Collect Twitter statistics and create boxplots to visualise.
    """
    type = "twitter-aggregated-stats-vis"  # job type ID
    category = "Twitter Analysis"  # category
    title = "Aggregated Statistics Visualization"  # title displayed in UI
    description = "Gathers Aggregated Statistics data and creates Box Plots visualising the spread of intervals. A large number of intervals will not properly display. "  # description displayed in UI
    extension = "png"  # extension of result file, used internally and in UI

    references = [
        "[matplotlib.pyplot.boxplot documentation](https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.boxplot.html)"
    ]

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        options = cls.options.copy()

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

        # Format header
        category = self.parameters.get("category")
        if len(self.num_of_different_categories) <= 5:
            header_subtext = ', '.join(self.num_of_different_categories)
        else:
            header_subtext = '%i total' % len(self.num_of_different_categories)
        header_category = '%s (%s)' % (category, str(header_subtext))

        # Collect visualization data for each chart
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
            axs[index].set_title('%s per %s' % (data_type.replace(f" per {category}", ""), header_category))
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
