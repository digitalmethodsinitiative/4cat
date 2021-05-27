"""
Search Parliament Speeches corpus
"""
import urllib.parse
import requests
import datetime

from backend.abstract.search import Search
from common.lib.helpers import UserInput
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException


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

    options = {
        "intro": {
            "type":  UserInput.OPTION_INFO,
            "help": "Parliament speech data is retrieved via [PENELOPE](https://penelope.vub.be). It covers speeches "
                    "from the Bundestag (the German national parliament) starting from [Period "
                    "19](https://en.wikipedia.org/wiki/2017_German_federal_election), as well as speeches from the "
                    "British House of Commons starting from January 2016. Both datasets end in October 2019. The data "
                    "has been collected by the [MIS Institute at MPG Leipzig](https://www.mis.mpg.de/).\n\nResults "
                    "are formatted as one 'thread' per distinct debate, with each individual contribution to that "
                    "debate as a 'post' in the thread"
        },
        "corpus": {
            "type": UserInput.OPTION_CHOICE,
            "options": {
                "gbr": "House of Commons (Great Britain)",
                "deu": "Bundestag (Germany)"
            },
            "default": "gbr",
            "help": "Corpus to search"
        },
        "body_match": {
            "type": UserInput.OPTION_TEXT,
            "help": "Content contains"
        },
        "daterange": {
            "type": UserInput.OPTION_DATERANGE,
            "help": "Publication date"
        }
    }

    def get_items(self, query):
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
        if not query.get("body_match", None):
            raise QueryParametersException("Please provide a search query")

        # the dates need to make sense as a range to search within
        query["min_date"], query["max_date"] = query["daterange"]
        del query["daterange"]

        # both dates need to be set, or none
        if query.get("min_date", None) and not query.get("max_date", None):
            raise QueryParametersException("When setting a date range, please provide both an upper and lower limit.")

        return query
