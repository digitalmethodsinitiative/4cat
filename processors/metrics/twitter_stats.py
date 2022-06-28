"""
Collapse post bodies into one long string
"""
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
    type = "twitter-stats"  # job type ID
    category = "Post metrics"  # category
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

            for post in self.source_dataset.iterate_items(self):
                try:
                    date = get_interval_descriptor(post, timeframe)
                except ValueError as e:
                    self.dataset.update_status("%s, cannot count posts per %s" % (str(e), timeframe), is_final=True)
                    self.dataset.update_status(0)
                    return

                # Add a counts for the respective timeframe
                if date not in intervals:
                    intervals[date] = {
                        "Number of Tweets": 1,
                        "Number of Tweets with links": 1 if post.get("urls") else 0,
                        "Number of Tweets with hashtags": 1 if post.get("hashtags") else 0,
                        "Number of Tweets with mentions": 1 if post.get("mentions") else 0,
                        "Number of Tweets with images": 1 if post.get("images") else 0,
                        "Number of Retweets": 1 if post.get("is_retweet") == 'yes' else 0,
                        "Number of Replies": 1 if post.get("is_reply") == 'yes' else 0,
                        "Number of Quotes": 1 if post.get("is_quote_tweet") == 'yes' else 0,
                        "Number of unique Authors": {post.get('author')},
                        # "Number of unique Threads": {post.get('thread_id')},
                        "Top 10 hashtags": {},
                        "Top 10 authors": {post.get('author'): 1},
                        "Top 10 mentions": {},
                    }
                else:
                    intervals[date]["Number of Tweets"] += 1
                    intervals[date]["Number of Tweets with links"] += 1 if post.get("urls") else 0
                    intervals[date]["Number of Tweets with hashtags"] += 1 if post.get("hashtags") else 0
                    intervals[date]["Number of Tweets with mentions"] += 1 if post.get("mentions") else 0
                    intervals[date]["Number of Tweets with images"] += 1 if post.get("images") else 0
                    intervals[date]["Number of Retweets"] += 1 if post.get("is_retweet") == 'yes' else 0
                    intervals[date]["Number of Replies"] += 1 if post.get("is_reply") == 'yes' else 0
                    intervals[date]["Number of Quotes"] += 1 if post.get("is_quote_tweet") == 'yes' else 0
                    intervals[date]["Number of unique Authors"].add(post.get('author'))
                    # intervals[date]["Number of unique Threads"].add(post.get('thread_id'))
                    if post.get('author') not in intervals[date]["Top 10 authors"]:
                        intervals[date]["Top 10 authors"][post.get('author')] = 1
                    else:
                        intervals[date]["Top 10 authors"][post.get('author')] += 1

                if post.get("hashtags"):
                    for hashtag in post.get("hashtags").split(','):
                        if hashtag not in intervals[date]["Top 10 hashtags"]:
                            intervals[date]["Top 10 hashtags"][hashtag] = 1
                        else:
                            intervals[date]["Top 10 hashtags"][hashtag] += 1

                if post.get("mentions"):
                    for mention in post.get("mentions").split(','):
                        if mention not in intervals[date]["Top 10 mentions"]:
                            intervals[date]["Top 10 mentions"][mention] = 1
                        else:
                            intervals[date]["Top 10 mentions"][mention] += 1

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
                        intervals[k] = {
                            "Number of Tweets": 0,
                            "Number of Tweets with links": 0,
                            "Number of Tweets with hashtags": 0,
                            "Number of Tweets with mentions": 0,
                            "Number of Tweets with images": 0,
                            "Number of Retweets": 0,
                            "Number of Replies": 0,
                            "Number of Quotes": 0,
                            "Number of unique Authors": 0,
                            # "Number of unique Threads": 0,
                            "Top 10 hashtags": {},
                            "Top 10 authors": {},
                            "Top 10 mentions": {},
                        }

            rows = []
            for interval, data in intervals.items():
                data["Number of unique Authors"] = len(data["Number of unique Authors"])
                # data["Number of unique Threads"] = len(data["Number of unique Threads"])

                sorted_tags = ["%s: %s" % (k, v) for k, v in
                               sorted(data["Top 10 hashtags"].items(), key=lambda item: item[1], reverse=True)]
                data["Top 10 hashtags"] = ', '.join(sorted_tags[:10])

                sorted_authors = ["%s: %s" % (k, v) for k, v in
                                   sorted(data["Top 10 authors"].items(), key=lambda item: item[1], reverse=True)]
                data["Top 10 authors"] = ', '.join(sorted_authors[:10])

                sorted_mentions = ["%s: %s" % (k, v) for k, v in
                                   sorted(data["Top 10 mentions"].items(), key=lambda item: item[1], reverse=True)]
                data["Top 10 mentions"] = ', '.join(sorted_mentions[:10])

                rows.append({**{"date": interval}, **data})

        self.write_csv_items_and_finish(rows)
