import time
import datetime
import re
import json
import requests
from bs4 import BeautifulSoup


from backend.lib.search import Search
from common.lib.exceptions import ProcessorInterruptedException, ProcessorException
from common.lib.item_mapping import MappedItem
from common.lib.user_input import UserInput


class SearchAzureStore(Search):
    """
    Search Microsoft Azure Store data source
    """
    type = "azure-store-search"  # job ID
    category = "Search"  # category
    title = "Microsoft Azure Store Search"  # title displayed in UI
    description = "Query Microsoft's Azure app store to retrieve data on applications and developers"  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    is_local = False  # Whether this datasource is locally scraped
    is_static = False  # Whether this datasource is still updated

    base_url = "https://azuremarketplace.microsoft.com"

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        max_results = 1000
        options = {
            "intro-1": {
                "type": UserInput.OPTION_INFO,
                "help": ("This data source allows you to query Microsoft's Azure app store to retrieve data on applications and developers."
                         )
            },
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "help": "Max number of results" + (f" (max {max_results:,})" if max_results != 0 else ""),
                "default": 60 if max_results == 0 else min(max_results, 60),
                "min": 0 if max_results == 0 else 1,
                "max": max_results,
                "tooltip": "The Azure store returns apps in batches of 60."
            },
            "method": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Query Type",
                "options": {
                    "search": "Search",
                },
                "default": "search"
            },
            "query": {
                "type": UserInput.OPTION_TEXT_LARGE,
                "help": "List of queries to search",
                "default": "", # need default else regex will fail
            },
            "full_details": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Include full application details",
                "default": False,
                "tooltip": "If enabled, the full details of each application will be included in the output.",
            },
        }
        
        return options

    def get_items(self, query):
        """
        Fetch items from Apple Store

        :param query:
        :return:
        """
        queries = re.split(',|\n', self.parameters.get('query', ''))
        # Updated method from options to match the method names in the collect_from_store function
        method = self.parameters.get('method')
        max_results = int(self.parameters.get('amount', 60))
        full_details = self.parameters.get('full_details', False)

        if method == "search":
            for query in queries:
                self.dataset.update_status(f"Processing query {query}")
                if self.interrupted:
                    raise ProcessorInterruptedException(f"Processor interrupted while fetching query {query}")
                page = 1
                num_results = 0
                while True:
                    results = self.get_query_results(query, previous_results=num_results, page=page)
                    if not results:
                        self.dataset.update_status(f"No additional results found for query {query}")
                        break

                    for result in results:
                        if full_details:
                            if self.interrupted:
                                # Only interrupting if we are collecting full details as otherwise we have already collected everything
                                raise ProcessorInterruptedException(f"Processor interrupted while fetching details for {result.get('title')}")

                            if num_results >= max_results:
                                break
                            result = self.get_app_details(result)

                        result["query"] = query
                        yield result
                        num_results += 1

                        self.dataset.update_status(f"Processed {num_results}{' of ' + str(max_results) if max_results > 0 else ''}")
                        if max_results > 0:
                            self.dataset.update_progress(num_results / max_results)

                    if num_results >= max_results:
                        # We may have extra result as results are batched
                        break

                    page += 1

    def get_app_details(self, app):
        """
        Collect full details for an app
        """
        app_url = self.base_url + app["href"]
        try:
            response = requests.get(app_url, timeout=30)
        except requests.exceptions.RequestException as e:
            self.dataset.log(f"Failed to fetch details for app {app.get('title')} from Azure Store: {e}")
            return app
        if response.status_code != 200:
            self.dataset.log(f"Failed to fetch details for app {app.get('title')} from Azure Store: {response.status_code} {response.reason}")
            return app

        soup = BeautifulSoup(response.content, "html.parser")
        # Update with more detailed source
        app["source"] = str(soup)

        # General content
        # Title block
        title_block = soup.find("div", attrs={"class": "appDetailHeader"})
        app["full_title"] = title_block.find("h1").get_text()
        app["developer_name"] = title_block.find("h2").get_text()

        # Details block
        details_block = soup.find("div", attrs={"class": "imageDetailsContainer"})
        regex = re.compile('.*appLargeIcon*')
        app["icon_link"] = details_block.find("div", attrs={"class": regex}).get_text()
        detail_categories = {}
        for header in details_block.find_all("header"):
            header_group = header.parent
            detail_categories[header.get_text().lower()] = [{"text": cat.get_text(), "href": cat.get("href")}
                                                    for cat in header_group.find_all("a")]
        app["details"] = detail_categories

        # App tabs
        app["tabs"] = self.collect_additional_tabs(soup)

        return app

    def collect_additional_tabs(self, soup):
        """
        There are tabs beyond "Overview" that contain additional information.

        It appears these mostly do not load in normal HTML, so we will need to be clever...
        """
        #TODO become clever
        # There are additional tabs to be collected
        app_tabs = {}
        regex = re.compile('.*defaultTab*')
        tabs = soup.find_all("a", attrs={"class": regex})
        for tab in tabs:
            tab_label = tab.find("label").get_text().lower()
            if tab.get("aria-selected") == "true":
                # Current tab
                tab_content = soup.find("div", attrs={"class": "tabContent"})
            else:
                # Request other tab
                try:
                    tab_request = requests.get(self.base_url + tab.get("href"), timeout=30)
                except requests.exceptions.RequestException as e:
                    self.dataset.log(
                        f"Failed to fetch additional tab {tab_label} for app {app.get('title')} from Azure Store: {e}")
                    continue
                if tab_request.status_code != 200:
                    self.dataset.log(
                        f"Failed to fetch additional tab {tab_label} for app {app.get('title')} from Azure Store: {tab_request.status_code} {tab_request.reason}")
                    continue
                tab_soup = BeautifulSoup(tab_request.content, "html.parser")
                tab_content = tab_soup.find("div", attrs={"class": "tabContent"})

            app_tabs[tab_label] = {
                "text": tab_content.get_text(separator="\n"),
                "source": str(tab_content)
            }

        return app_tabs

    def get_query_results(self, query, previous_results=0, page=1, store="en-us"):
        """
        Fetch query results from Azure Store
        """
        query_url = self.base_url + f"/{store}/marketplace/apps"
        params = {
            "search": query,
            "page": page
        }
        try:
            response = requests.get(query_url, params, timeout=30)
        except requests.exceptions.RequestException as e:
            raise ProcessorException(f"Failed to fetch data from Azure Store: {e}")
        if response.status_code != 200:
            raise ProcessorException(f"Failed to fetch data from Azure Store: {response.status_code} {response.reason}")

        soup = BeautifulSoup(response.content, "html.parser")
        results = soup.find_all("div", attrs={"class": "spza_tileWrapper"})

        return [{
            "title": soup.find("div", attrs={"class": "tileContent"}).get_text(),
            "href": soup.find("a").get("href"),
            "rank": i+previous_results,
            "source": str(soup),
            } for i, soup in enumerate(results, start=1)]

    @staticmethod
    def validate_query(query, request, user):
        """
        Validate input for a dataset query on the data source.

        Will raise a QueryParametersException if invalid parameters are
        encountered. Parameters are additionally sanitised.

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param User user:  User object of user who has submitted the query
        :return dict:  Safe query parameters
        """
           
        return query


    @staticmethod
    def map_item(item):
        """
        Map item to a common format that includes, at minimum, "id", "thread_id", "author", "body", and "timestamp" fields.

        :param item:
        :return:
        """
        # Map expected detail groups and tabs
        tab_groups = [
            "overview",
            "plans",
            "ratings + reviews",
        ]
        additional_tabs = [{tab_label: tab.get('text')} for tab_label, tab in item.get("tabs", {}).items() if tab_label.lower() not in tab_groups]
        detail_groups = [
            "pricing information",
            "categories",
            "support",
            "legal",
        ]
        additional_details = [{detail_label: detail.get("text")} for detail_label, detail in item.get("details", {}).items() if detail_label.lower() not in detail_groups]

        formatted_item = {
            "query": item.get("query"),
            "rank": item.get("rank"),
            "title": item.get("title", ""),
            "developer_name": item.get("developer_name", ""),
            "icon_link": item.get("icon_link", ""),
            "url": SearchAzureStore.base_url + item.get("href", ""),
            "full_title": item.get("full_title", ""),
            "pricing_information": ", ".join([detail.get("text") for detail in item.get("details", {}).get("pricing information", [])]),
            "categories": ", ".join([detail.get("text") for detail in item.get("details", {}).get("categories", [])]),
            "support": ", ".join([detail.get("text") + f": {SearchAzureStore.base_url + detail.get('href')}" for detail in item.get("details", {}).get("support", [])]),
            "legal": ", ".join([detail.get("text") + f": {SearchAzureStore.base_url + detail.get('href')}" for detail in item.get("details", {}).get("legal", [])]),
            "overview": item.get("tabs", {}).get("overview", {}).get("text", ""),
            "plans": item.get("tabs", {}).get("plans", {}).get("text", ""),
            "ratings_reviews": item.get("tabs", {}).get("ratings + reviews", {}).get("text", ""),
            "details": additional_details,
            "additional_tabs": additional_tabs,
            "body": item.get("tabs", {}).get("overview", {}).get("text", ""),
        }

        return MappedItem(formatted_item)
