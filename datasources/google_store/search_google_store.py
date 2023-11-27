import re
from common.lib.user_input import UserInput
from datasources.apple_store.search_apple_store import SearchAppleStore, collect_from_store


class SearchGoogleStore(SearchAppleStore):
    """
    Search Google Store data source


    Defines methods to fetch data from Apples application store on demand
    """
    type = "google-store-search"  # job ID
    category = "Search"  # category
    title = "Google Store Search"  # title displayed in UI
    description = "Query Google's app store to retrieve data on applications and developers"  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    is_local = False  # Whether this datasource is locally scraped
    is_static = False  # Whether this datasource is still updated

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):

        options = {
            "intro-1": {
                "type": UserInput.OPTION_INFO,
                "help": "This data source allows you to query Apple's app store to retrieve data on applications and developers."
            },
            "method": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Query Type",
                "options": {
                    "query-app": "App IDs",
                    "query-search-detail": "Search by query",
                    "query-developer-detail": "Developer IDs",
                    "query-similar-detail": "Similar Apps",
                    "query-permissions": "Permissions", # Permissions do not exist for apple store!
                },
                "default": "query-search-detail"
            },
            "query": {
                "type": UserInput.OPTION_TEXT_LARGE,
                "help": "List of App IDs, Developer IDs, or queries to search for.",
                "requires": "method^=query", # starts with query
                "tooltip": "Seperate IDs or queries with commas to search multiple."
            },
            "full_details": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Include full application details",
                "default": False,
                "tooltip": "If enabled, the full details of each application will be included in the output.",
                "requires": "method$=detail", # ends with detail
            },
            "intro-2": {
                "type": UserInput.OPTION_INFO,
                "help": "Language and Country options have limited effects due to geographic restrictions and results given based on from what country the request originates (i.e. the country where 4CAT is based)."
            },
            "languages": {
                "type": UserInput.OPTION_TEXT,
                "help": "Languages to query.",
                "default": "en",
                "tooltip": "Seperate ISO two letter language codes with commas to search multiple languages. If left blank, only English will be used."
            },
            "countries": {
                "type": UserInput.OPTION_TEXT,
                "help": "Countries to query.",
                "default": "us",
                "tooltip": "Seperate ISO two letter country codes with commas to search multiple countries. If left blank, only US will be used."
            },
        }
        
        return options

    def get_items(self, query):
        """
        Fetch items from Google Store

        :param query:
        :return:
        """
        queries = re.split(',|\n', self.parameters.get('query', ''))
        # Updated method from options to match the method names in the collect_from_store function
        method = {
            'query-app': 'app',
            'query-search-detail': 'search',
            'query-developer-detail': 'developer',
            'query-similar-detail': 'similar',
            'query-permissions': 'permissions',
        }.get(self.parameters.get('method'))

        params = {}
        if method == 'search':
            params['queries'] = queries
        elif method == 'developer':
            params['devId'] = queries
        elif method == 'similar':
            params['appId'] = queries
        elif method == 'permissions':
            params['appId'] = queries
        else:
            params['appId'] = queries

        self.dataset.log(f"Collecting {method} from Google Store")
        results = collect_from_store('google', method, languages=re.split(',|\n', self.parameters.get('languages')), countries=re.split(',|\n', self.parameters.get('countries')), full_detail=self.parameters.get('full_details', False), params=params, log=self.dataset.log)
        self.dataset.log(f"Collected {len(results)} results from Google Store")
        return results
