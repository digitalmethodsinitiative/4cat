"""
Twitter APIv2 base stats class
"""
import abc
import datetime

from common.lib.helpers import pad_interval, get_interval_descriptor
from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorException

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class TwitterStatsBase(BasicProcessor):
    """
    Collect Twitter statistics. Build to emulate TCAT statistic.
    """
    type = "twitter-stats-base"  # job type ID
    category = "Twitter Analysis"  # category
    title = "Twitter Base Statistics"  # title displayed in UI
    description = "This is a class to help other twitter classes"  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI


    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Determine if processor is compatible with dataset

        :param module: Dataset or processor to determine compatibility with
        """
        return False

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
        data_types = None
        # Iterate through each post and collect data for each interval
        for post in self.source_dataset.iterate_items(self, bypass_map_item=True):
            try:
                tweet_time = datetime.datetime.strptime(post["created_at"], "%Y-%m-%dT%H:%M:%S.000Z")
                post["timestamp"] = tweet_time.strftime("%Y-%m-%d %H:%M:%S")
                date = get_interval_descriptor(post, timeframe)
            except ValueError as e:
                self.dataset.update_status("%s, cannot count posts per %s" % (str(e), timeframe), is_final=True)
                self.dataset.update_status(0)
                return

            # Map the data in the post to either be summed (by grouping and interval) or updated (keeping most recent)
            group_by_keys_category, group_by_keys, sum_map, static_map, list_map = self.map_data(post)

            # Additional groupings in intervals
            if group_by_keys_category is not False:
                if type(group_by_keys) is str:
                    group_by_keys = [group_by_keys]
                elif type(group_by_keys) is not set:
                    raise ProcessorException("group_by_keys must be a string or list")

                # Add a counts for the respective timeframe
                if date not in intervals:
                    intervals[date] = {}

                for group_by_key in group_by_keys:
                    if group_by_key not in intervals[date]:
                        # Add new record for this grouping
                        intervals[date][group_by_key] = {**static_map, **sum_map, **list_map, **{"Created at Timestamp": int(tweet_time.timestamp())}}

                        # Convenience for easy adding to above
                        if not data_types:
                            data_types = list(intervals[date][group_by_key].keys())
                            self.dataset.log("Data being collected: %s" % data_types)

                    else:
                        # Update existing record for this grouping
                        for key, value in sum_map.items():
                            intervals[date][group_by_key][key] += value
                        for key, value in list_map.items():
                            intervals[date][group_by_key][key].update(value)

                        # Methodology question: which stat is best to use? Most recent? Largest? Smallest? Likely they will be identical or minimally different.
                        # Using most recent for now.
                        if int(tweet_time.timestamp()) > intervals[date][group_by_key]["Created at Timestamp"]:
                            for key, value in static_map.items():
                                intervals[date][group_by_key][key] = value

            # Aggregate by intervals only
            else:
                if date not in intervals:
                    intervals[date] = {**static_map, **sum_map, **list_map, **{"Created at Timestamp": int(tweet_time.timestamp())}}

                    # Convenience for easy adding to above
                    if not data_types:
                        data_types = list(intervals[date].keys())
                        self.dataset.log("Data being collected: %s" % data_types)
                else:
                    # Update existing record for this grouping
                    for key, value in sum_map.items():
                        intervals[date][key] += value
                    for key, value in list_map.items():
                        intervals[date][key].update(value)

                    # Methodology question: which stat is best to use? Most recent? Largest? Smallest? Likely they will be identical or minimally different.
                    # Using most recent for now.
                    if int(tweet_time.timestamp()) > intervals[date]["Created at Timestamp"]:
                        for key, value in static_map.items():
                            intervals[date][key] = value

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
                    intervals[k] = self.padding_map()

        rows = []
        for interval, data in intervals.items():
            if group_by_keys_category:
                for group_key, group_data in data.items():
                    group_data = self.modify_intervals(group_key, group_data)
                    rows.append({**{"date": interval, group_by_keys_category: group_key}, **group_data})
            else:
                rows.append({**{"date": interval}, **data})

        self.write_csv_items_and_finish(rows)

    def padding_map(self):
        """
        Returns the base dictionary to be used if there are no values in a certain interval.
        """
        return {}

    def modify_intervals(self, key, data):
        """
        Modify the intervals on a second loop once all the data has been collected. This is particularly useful for
        lists or sets of items that were collected.
        """
        return data

    @abc.abstractmethod
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

        # Map the data in the post to either be summed (by grouping and interval)
        sum_map = {}
        # These are user-specific metrics and not per tweet/post like above
        static_map = {}
        # These keys contain sets of items (e.g. hashtags)
        list_map = {}

        return group_by_key_category, group_by_keys, sum_map, static_map, list_map
