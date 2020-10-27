"""
Search Parliament Speeches corpus
"""
import urllib.parse
import requests
import datetime
import re

from backend.abstract.search import Search
from backend.lib.exceptions import QueryParametersException, ProcessorInterruptedException


class SearchParliamentSpeeches(Search):
    """
    Search Parliaments Speeches

    Defines methods that are used to query the parliament speech data via PENELOPE.
    """
    type = "parliaments-search"  # job ID
    category = "Search"  # category
    title = "Parliament Speeches Search"  # title displayed in UI
    description = "Queries the MPG's Parliament Speeches dataset via PENELOPE for contributions to German and English parliament speeches."  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    # not available as a processor for existing datasets
    accepts = [None]

    max_workers = 1
    max_retries = 3

    def get_posts_simple(self, query):
        """
        Execute a query; get post data for given parameters

        :param dict query:  Query parameters, as part of the DataSet object
        :return list:  Posts, sorted by thread and post ID, in ascending order
        """
        start = datetime.datetime.utcfromtimestamp(query["min_date"]).strftime("%Y-%m-%d")
        end = datetime.datetime.utcfromtimestamp(query["max_date"]).strftime("%Y-%m-%d")

        regex = query["body_match"].replace("*", ".+")
        corpus = query["corpus"]

        parameters = {
            "dataset_name": corpus,
            "search_query": regex,
            "start_date": start,
            "end_date": end
        }

        self.dataset.update_status("Querying PENELOPE API")
        all_contributions = self.call_penelope_api(parameters)
        posts = [self.item_to_4cat(item) for item in all_contributions]

        return sorted(posts, key=lambda item: (item["timestamp"], item["thread_id"], item["id"]))

    def get_search_mode(self, query):
        """
        Parliament speech searches are always simple

        :return str:
        """
        return "simple"

    def get_posts_complex(self, query):
        """
        Complex post fetching is not used by this datasource

        :param query:
        :return:
        """
        return self.get_posts_simple(query)

    def fetch_posts(self, post_ids, where=None, replacements=None):
        """
        Posts are fetched via instaloader for this datasource
        :param post_ids:
        :param where:
        :param replacements:
        :return:
        """
        pass

    def fetch_threads(self, thread_ids):
        """
        Thread filtering is not a toggle for Instagram datasets

        :param thread_ids:
        :return:
        """
        pass

    def get_thread_sizes(self, thread_ids, min_length):
        """
        Thread filtering is not a toggle for Instagram datasets

        :param tuple thread_ids:
        :param int min_length:
        results
        :return dict:
        """
        pass

    def item_to_4cat(self, post):
        """
        Convert a PENELOPE API post object to 4CAT post data

        :param dict post:  Post data, as from the penelope API
        :return dict:  Re-formatted data
        """
        timebits = [int(bit) for bit in post["date"].split("-")]
        posttime = datetime.datetime(timebits[0], timebits[1], timebits[2])

        return {
            "thread_id": post["discussion_title"],
            "id": post["id"],
            "subject": "",
            "body": post["text"],
            "author": post["name"],
            "author_party": post["party"],
            "author_id": post.get("speaker_id", ""),
            "timestamp": posttime.timestamp(),
            "period": post.get("period", "")
        }

    def call_penelope_api(self, params, *args, **kwargs):
        """
        Call PENELOPE API and don't crash (immediately) if it fails

        :param params: Call parameters
        :param args:
        :param kwargs:
        :return: Response, or `None`
        """
        #https://penelope.vub.be/parliament-data/get-speeches/<search_query>/<dataset_name>/<start_date>/<end_date>/<max_number>
        url = "https://penelope.vub.be/parliament-data/get-speeches/%s/%s/%s/%s/"
        url = url % (
            urllib.parse.quote(params["dataset_name"]),
            urllib.parse.quote(params["start_date"]),
            urllib.parse.quote(params["end_date"]),
            urllib.parse.quote(params["search_query"])

        )

        retries = 0
        while retries < self.max_retries:
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while fetching data from the Penelope API")

            try:
                response = requests.get(url, *args, **kwargs)
                break
            except requests.RequestException as e:
                self.log.info("Error %s while querying PENELOPE Parliament Speeches API - retrying..." % e)
                retries += 1

        if retries >= self.max_retries:
            self.log.error("Error during PENELOPE fetch of query %s" % self.dataset.key)
            self.dataset.update_status("Error while searching for posts on PENELOPE Parliament Speeches API")
            return None
        else:
            return response.json()["speeches"]

    def validate_query(query, request, user):
        """
        Validate input for a dataset query on the 4chan data source.

        Will raise a QueryParametersException if invalid parameters are
        encountered. Mutually exclusive parameters may also be sanitised by
        ignoring either of the mutually exclusive options.

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param User user:  User object of user who has submitted the query
        :return dict:  Safe query parameters
        """
        # this is the bare minimum, else we can't narrow down the full data set
        if not query.get("body_match", None) and not query.get("subject_match", None):
            raise QueryParametersException("Please provide a search query")

        if query.get("corpus") not in ("deu", "gbr"):
            raise QueryParametersException("Please choose a valid corpus to search within")

        # both dates need to be set, or none
        if query.get("min_date", None) and not query.get("max_date", None):
            raise QueryParametersException("When setting a date range, please provide both an upper and lower limit.")

        # the dates need to make sense as a range to search within
        if query.get("min_date", None) and query.get("max_date", None):
            try:
                before = int(query.get("max_date", ""))
                after = int(query.get("min_date", ""))
            except ValueError:
                raise QueryParametersException("Please provide valid dates for the date range.")

            if after < 946684800:
                raise QueryParametersException("Please provide valid dates for the date range.")

            if before < after:
                raise QueryParametersException(
                    "Please provide a valid date range where the start is before the end of the range.")

            if after - before > (6 * 86400 * 30.25):
                raise QueryParametersException("The date range for this query can span 6 months at most.")

            query["min_date"] = after
            query["max_date"] = before
        else:
            raise QueryParametersException("You need to provide a date range for your query")

        is_placeholder = re.compile("_proxy$")
        filtered_query = {}
        for field in query:
            if not is_placeholder.search(field):
                filtered_query[field] = query[field]

        # if we made it this far, the query can be executed
        return filtered_query
