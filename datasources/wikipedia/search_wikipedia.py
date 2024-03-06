"""
Wikipedia article search
"""
from datetime import datetime, timezone
import requests

from backend.lib.search import Search
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException
from common.lib.item_mapping import MappedItem
from common.lib.user_input import UserInput


class SearchWikipedia(Search):
    """
    Get Wikipedia articles via Wikimedia's API
    """
    type = "wikipedia-search"  # job ID
    title = "Wikipedia Search"
    extension = "ndjson"
    is_local = False    # Whether this datasource is locally scraped
    is_static = False   # Whether this datasource is still updated

    references = [
        "[Wikimedia API](https://api.wikimedia.org/wiki/Searching_for_Wikipedia_articles_using_Python)",
    ]


    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        """
        Options for the user to provide in order to run the search

        :param parent_dataset:  Should always be None
        :param user:  User to provide options for
        :return dict:  Data source options
        """

        options = {
            "intro-1": {
                "type": UserInput.OPTION_INFO,
                "help": "Search Wikipedia articles and retreive their metadata. You will need a Wikimedia API key which can be obtained by creating a user account and request a personal API key. They provide [instructions here.](https://api.wikimedia.org/wiki/Getting_started_with_Wikimedia_APIs)"
            },
            "api_key": {
                "type": UserInput.OPTION_TEXT,
                "sensitive": True, # Ensures 4CAT knows to keep this value secret and not stored in the 4CAT database
                "cache": True, # Allows the value to be cached by the user's browser to use again
                "help": "API Key"
            },
            "query": {
                "type": UserInput.OPTION_TEXT,
                "help": "Search query"
            },
        }

        return options

    @staticmethod
    def validate_query(query, request, user):
        """
        Validate the options input needed to query the Wikipedia data source.

        Will raise a QueryParametersException if invalid parameters are
        encountered. Parameters are additionally sanitised.

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param User user:  User object of user who has submitted the query
        :return dict:  Safe query parameters
        """
        # Please provide something...
        if not query.get("api_key", None): # corresponds to the "api_key" option in `get_options`
            raise QueryParametersException("Please provide an API key.")

        # Please provide something...
        if not query.get("query", None): # corresponds to the "query" option in `get_options`
            raise QueryParametersException("Please provide a query.")

        return query

    def get_items(self, query):
        """
        Use the Wikimedia API to collect articles

        :param query:
        :return:
        """
        api_key = query.get("api_key") # corresponds to the "api_key" option in `get_options`
        if api_key is None:
            # Because API keys are not kept, if this dataset was interrupted, it cannot be resumed
            self.dataset.update_status(
                "Wikipedia query failed or was interrupted; please create new query in order to provide your API key again.",
                is_final=True)
            return [] # No items to return

        # Get the query
        language_code = 'en' # Wikipedia needs a language code; we could add an option for this
        search_query = query.get("query") # corresponds to the "query" option in `get_options`
        number_of_results = 10 # Another great option to add
        headers = {
            'Authorization': api_key,
            'User-Agent': '4CAT (4cat.nl)' # Be nice to open source resources and let them know who is using their API
        }

        base_url = 'https://api.wikimedia.org/core/v1/wikipedia/'
        endpoint = '/search/page'
        url = base_url + language_code + endpoint
        parameters = {'q': search_query, 'limit': number_of_results}

        self.dataset.update_status("Querying Wikimedia API for {}".format(search_query)) # update_status adds a message to the dataset's status log and to the UI
        response = requests.get(url, headers=headers, params=parameters)
        collection_time = datetime.now(tz=timezone.utc).timestamp() # Add a timestamp to the metadata

        if response.status_code != 200:
            self.dataset.update_status(
                "Wikimedia API query failed with status code {} and reason {}.".format(response.status_code, response.reason),
                is_final=True)
            return []

        total_results = len(response.json()['pages'])
        # Get the data
        for i, article_result in enumerate(response.json()['pages']):
            if self.interrupted:
                # In this example, it is not necessary to check for interruptions, but if we were following up with more
                # queries or collecting the actual articles, we would need to check for interruptions
                raise ProcessorInterruptedException("Interrupted while fetching articles from the Wikimedia API")

            # It is a good practice to add some metadata to items such as collection time
            article_result['4CAT_metadata'] = {"collected_at": collection_time, "query": search_query, 'language_code': language_code}

            yield article_result
            self.dataset.update_progress(i+1 / total_results) # update_progress updates the progress bar in the UI

    @staticmethod
    def map_item(item):
        """
        Map a nested Wikipedia object to a flat dictionary

        :param item:  Wikipedia object as originally returned by the VK API
        :return dict:  Dictionary in the format expected by 4CAT
        """
        # We return a MappedItem object as that can allow us some flexibility to handle issues in the data (such as
        # missing fields) and notify users
        fourcat_metadata = item.get('4CAT_metadata', {})
        collected_at = datetime.fromtimestamp(item.get('4CAT_metadata', {}).get('collected_at'))
        language = fourcat_metadata.get('language_code')

        display_title = item['title']
        article_url = 'https://' + language + '.wikipedia.org/wiki/' + item['key']

        return MappedItem({
            # Some fields are required by 4CAT
            "id": item["id"],
            "timestamp": collected_at.strftime("%Y-%m-%d %H:%M:%S"),
            "body": item.get("excerpt", ""), # The "body" field is often used by default in 4CAT as the main text of the item
            "author": "", # We don't have an author for Wikipedia articles, but it is a required field
            "thread_id": "", # We don't have a thread ID for Wikipedia articles, but it is a required field

            # Additional data
            "link": article_url,
            "subject": display_title, # "subject" is a commonly used field in 4CAT
            "description": item.get("description", ""),
            "image_url": "https:" + item.get("thumbnail", {}).get("url", "") if item.get("thumbnail") else "", # "image_url" is a commonly used field in 4CAT and should be a valid link for 4CAT to download later

            # Metadata if desired; can be useful if we collected multiple queries and/or languages
            "language_code": language,
            "query": fourcat_metadata.get('query', ""),
            "unix_timestamp": int(collected_at.timestamp()),
        })