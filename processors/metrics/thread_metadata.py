"""
Thread data
"""
import datetime
import math

from backend.lib.processor import BasicProcessor

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

class ThreadMetadata(BasicProcessor):
    """
    Extracts metadata on threads from the dataset.
    """

    type = "thread-metadata"  # job type ID
    category = "Metrics"  # category
    title = "Thread metadata"  # title displayed in UI
    description = (
        "Extract various metadata on the threads in the dataset, including time data and post counts. Note "
        "that this extracted only on the basis of the items present this dataset."
    )  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    followups = []

    @staticmethod
    def is_compatible_with(module=None, config=None):
        """
        Determine compatibility

        :param Dataset module:  Module ID to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        :return bool:
        """
        return module.is_top_dataset() and module.get_extension() in ("csv", "ndjson")

    def process(self):
        """
        This takes a 4CAT results file as input, and outputs a new CSV file
        with one column with unique thread IDs and another one with the number
        of posts in that thread.
        """
        threads = {}

        self.dataset.update_status("Reading source file")

        progress = 0
        no_timestamp = 0

        for post in self.source_dataset.iterate_items(self):
            if post["thread_id"] not in threads:
                threads[post["thread_id"]] = {
                    "subject": post.get("subject", ""),
                    "first_post": 0,
                    "image_md5": "",  # only relevant for the chans
                    "country_name": "",  # only relevant for the chans
                    "op_body": "",
                    "author": "",
                    "last_post": 0,
                    "images": 0,
                    "count": 0,
                }

            if post.get("subject"):
                threads[post["thread_id"]]["subject"] = post.get("subject", "")

            if post.get("image_md5"):
                threads[post["thread_id"]]["images"] += 1

            if post["id"] == post["thread_id"]:
                threads[post["thread_id"]]["author"] = post.get("author", "")
                threads[post["thread_id"]]["country_name"] = post.get(
                    "country_name", "N/A"
                )
                threads[post["thread_id"]]["image_md5"] = post.get("image_md5", "N/A")
                threads[post["thread_id"]]["op_body"] = post.get("body", "")

            try:
                timestamp = int(
                    datetime.datetime.strptime(
                        post["timestamp"], "%Y-%m-%d %H:%M:%S"
                    ).timestamp()
                )

                threads[post["thread_id"]]["first_post"] = min(
                    timestamp, threads[post["thread_id"]]["first_post"]
                )
                threads[post["thread_id"]]["last_post"] = max(
                    timestamp, threads[post["thread_id"]]["last_post"]
                )
                threads[post["thread_id"]]["count"] += 1

            except ValueError:
                no_timestamp += 1

            progress += 1
            if progress % 500 == 0:
                self.dataset.update_status(
                    f"Iterated through {progress:,} of {self.source_dataset.num_rows:,} items"
                )
                self.dataset.update_progress(progress / self.source_dataset.num_rows)

        results = [
            {
                "thread_id": thread_id,
                "timestamp": datetime.datetime.utcfromtimestamp(
                    threads[thread_id]["first_post"]
                ).strftime("%Y-%m-%d %H:%M:%S")
                if threads[thread_id]["first_post"]
                else "",
                "timestamp_lastpost": datetime.datetime.utcfromtimestamp(
                    threads[thread_id]["last_post"]
                ).strftime("%Y-%m-%d %H:%M:%S")
                if threads[thread_id]["last_post"]
                else "",
                "timestamp_unix": threads[thread_id]["first_post"] or "",
                "timestamp_lastpost_unix": threads[thread_id]["last_post"] or "",
                "subject": threads[thread_id]["subject"],
                "author": threads[thread_id]["author"],
                "op_body": threads[thread_id]["op_body"],
                "num_posts": threads[thread_id]["count"],
                **(
                    {
                        "thread_age": (
                            threads[thread_id]["last_post"]
                            - threads[thread_id]["first_post"]
                        ),
                        "thread_age_friendly": self.timify_secs(
                            threads[thread_id]["last_post"]
                            - threads[thread_id]["first_post"]
                        ),
                    } if threads[thread_id]["last_post"] and threads[thread_id]["first_post"]
					else {"thread_age": "", "thread_age_friendly": ""}
                ),
                **(
                    {
                        "num_images": threads[thread_id]["images"],
                        "image_md5": threads[thread_id]["image_md5"],
                        "country_code": threads[thread_id]["country_code"],
                    }
                    if self.source_dataset.type in ("fourchan", "eightchan", "eightkun")
                    else {}
                )
            }
            for thread_id in threads
        ]

        if not results:
            return

        if no_timestamp:
            self.dataset.update_status(
                f"{no_timestamp:,} items did not have a valid timestamp and were not included "
                f"in time-related statistics (e.g. first/last item)",
                is_final=True,
            )

        self.write_csv_items_and_finish(results)

    def timify_secs(self, number):
        """
        For the non-geniuses, convert an amount of seconds to a more readable
        approximation like '4h 5m'

        :param int number:  Amount of seconds
        :return str:  Readable approximation
        """
        try:
            number = int(number)
        except TypeError:
            return number

        time_str = ""

        hours = math.floor(number / 3600)
        if hours > 0:
            time_str += "%ih " % hours
            number -= hours * 3600

        minutes = math.floor(number / 60)
        if minutes > 0:
            time_str += "%im " % minutes
            number -= minutes * 60

        seconds = number
        time_str += "%is " % seconds

        return time_str.strip()
