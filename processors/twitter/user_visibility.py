"""
Twitter APIv2 base stats class
"""
import datetime

from common.lib.helpers import get_interval_descriptor
from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.user_input import UserInput

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class TwitterUserVisibility(BasicProcessor):
    """
    Collect User stats as both author and mention.
    """
    type = "twitter-user-visibility"  # job type ID
    category = "Twitter Analysis"  # category
    title = "User Visibility"  # title displayed in UI
    description = "Collects usernames and totals how many tweets are authored by the user and how many tweets mention the user"  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    options = {
                  "timeframe": {
                      "type": UserInput.OPTION_CHOICE,
                      "default": "month",
                      "options": {"all": "Overall", "year": "Year", "month": "Month", "week": "Week", "day": "Day",
                                  "hour": "Hour", "minute": "Minute"},
                      "help": "Produce counts per"
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
        # OrderedDict because dates and headers should have order
        intervals = {}

        timeframe = self.parameters.get("timeframe")

        first_interval = "9999"
        last_interval = "0000"

        counter = 0
        # Iterate through each post and collect data for each interval
        for post in self.source_dataset.iterate_items(self, bypass_map_item=True):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while processing Tweets")

            try:
                tweet_time = datetime.datetime.strptime(post["created_at"], "%Y-%m-%dT%H:%M:%S.000Z")
                post["timestamp"] = tweet_time.strftime("%Y-%m-%d %H:%M:%S")
                date = get_interval_descriptor(post, timeframe)
            except ValueError as e:
                return self.dataset.finish_with_error("%s, cannot count posts per %s" % (str(e), timeframe))

            if date not in intervals:
                intervals[date] = {}

            # Add author
            author = post.get("author_user").get("username")
            if author == 'REDACTED':
                return self.dataset.finish_with_error("Author information has been removed; cannot calculate frequencies")

            if author not in intervals[date]:
                intervals[date][author] = {
                    'Tweets': 1,
                    'Mentions': 0,
                }
            else:
                intervals[date][author]['Tweets'] += 1

            # Add mentions
            mentions = set([tag["username"] for tag in post.get("entities", {}).get("mentions", [])])
            # Add referenced tweet data to the collected information
            for ref_tweet in post.get('referenced_tweets', []):
                if ref_tweet.get('type') in ['retweeted', 'quoted']:
                    mentions.update([tag['username'] for tag in ref_tweet.get('entities', {}).get('mentions', [])])
            for mention in mentions:
                if mention not in intervals[date]:
                    intervals[date][mention] = {
                        'Tweets': 0,
                        'Mentions': 1,
                    }
                else:
                    intervals[date][author]['Mentions'] += 1

            first_interval = min(first_interval, date)
            last_interval = max(last_interval, date)

            counter += 1

            if counter % 2500 == 0:
                self.dataset.update_status("Processed through " + str(counter) + " posts.")

        rows = []
        for interval, data in intervals.items():
            interval_rows = []
            for author, author_data in data.items():
                # Add total and reorder
                interval_rows.append({
                    "Date": interval,
                    'Author': author,
                    'Tweets': author_data['Tweets'],
                    'Mentions': author_data['Mentions'],
                    'Total': author_data['Tweets']+author_data['Mentions']
                })

            interval_rows = sorted(interval_rows, key=lambda d: d['Total'], reverse=True)

            rows += interval_rows

        self.write_csv_items_and_finish(rows)
