from datetime import datetime, timedelta
import re
import time
import urllib
from selenium.webdriver.common.by import By
from selenium.common import exceptions as selenium_exceptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from backend.lib.selenium_scraper import SeleniumWrapper
from common.lib.item_mapping import MappedItem
from common.lib.user_input import UserInput
from datasources.url_scraper.search_webpages import SearchWithSelenium

from common.config_manager import config


class SearchAwsStore(SearchWithSelenium):
    """
    Search Amazon Web Services Marketplace data source
    """
    type = "aws-store-search"  # job ID
    category = "Search"  # category
    title = "Amazon Web Services (AWS) Marketplace"  # title displayed in UI
    description = "Query Amazon Web Services Marketplace to retrieve data on applications and developers"  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    is_local = False  # Whether this datasource is locally scraped
    is_static = False  # Whether this datasource is still updated

    config = {
        "cache.aws.query_options": {
            "type": UserInput.OPTION_TEXT_JSON,
            "help": "AWS Query Options",
            "tooltip": "automatically updated",
            "default": {}
        },
        "cache.aws.query_options_updated_at": {
            "type": UserInput.OPTION_TEXT,
            "help": "AWS Query Options Updated At",
            "tooltip": "automatically updated",
            "default": 0,
            "coerce_type": int
        }
    }

    base_url = "https://aws.amazon.com/marketplace/"
    search_url = base_url + "search/"
    max_results = 1000
    query_param_map = {
        "Categories": "category",
        "Vendors": "creator",
        "Pricing Models": "pricing_model",
        "Delivery Methods": "fulfillment_option_type",
    }
    query_param_ignore = ['All pricing models', 'All delivery methods', 'All vendors', 'All categories']


    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow if Selenium is available
        """
        return SearchWithSelenium.is_selenium_available()

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        max_results = cls.max_results
        options = {
            "intro-1": {
                "type": UserInput.OPTION_INFO,
                "help": (
                    "This data source allows you to query Amazon Web Services Marketplace to retrieve data on applications and developers."
                    )
            },
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "help": "Max number of results" + (f" (max {max_results:,})" if max_results != 0 else ""),
                "default": 60 if max_results == 0 else min(max_results, 60),
                "min": 0 if max_results == 0 else 1,
                "max": max_results,
                "tooltip": "The AWS Marketplace returns apps in batches of 20."
            },
            "query": {
                "type": UserInput.OPTION_TEXT_LARGE,
                "help": "List of queries to search (leave blank for all).",
                "default": "",  # need default else regex will fail
            }
        }
        filter_options = cls.get_query_options()
        for filter_name, filter_options in filter_options.items():
            if filter_name not in cls.query_param_map:
                config.db.log.warning(f"AWS Unknown filter name: {filter_name}")
                continue

            options[cls.query_param_map[filter_name]] = {
                "type": UserInput.OPTION_CHOICE,
                "help": f"Filter by {filter_name}",
                "options": {(option["data-value"] if option["name"] not in cls.query_param_ignore else "all"): option["name"] for option in filter_options},
                "default": "all",
            }

        options["full_details"] = {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Include full application details",
                "default": False,
                "tooltip": "If enabled, the full details of each application will be included in the output.",
            }
        return options

    @classmethod
    def get_query_options(cls, force_update=False):
        """
        Get query options from AWS only if they have not been recently checked
        """
        click_js_script = "arguments[0].click()"
        last_updated = config.get("cache.aws.query_options_updated_at", 0)
        if (datetime.fromtimestamp(last_updated) > datetime.now() - timedelta(
                days=1)) and not force_update:
            # Do not re-fetch unless forced or older than one day
            return config.get("cache.aws.query_options")

        selenium_driver = SeleniumWrapper()
        if not selenium_driver.is_selenium_available():
            # Selenium never available in frontend!
            return {}
        # Backend runs get_options for each processor on init; but does not seem to have logging
        selenium_driver.selenium_log.info("Fetching query options from AWS Marketplace")

        selenium_driver.start_selenium()
        selenium_driver.driver.get(cls.base_url)
        try:
            # Get Query options
            search_container_id = "migration_picker_internal_container"
            search_container = selenium_driver.driver.find_element(By.ID, search_container_id)
            option_containers = search_container.find_elements(By.TAG_NAME, "awsui-select")
            # Collect possible filter options
            query_filters = {}
            for option_container in option_containers:
                option_name = option_container.find_element(By.XPATH, "../span").text
                selenium_driver.selenium_log.warning(f"AWS option: {option_name}")
                query_filters[option_name] = []
                # Open option dropdown
                # Use JS here as the dropdown is not visible (cookies popup)
                try:
                    button = WebDriverWait(selenium_driver.driver, 5).until(EC.presence_of_element_located((By.CLASS_NAME, "awsui-select-trigger-icon")))
                    # button = option_container.find_element(By.CLASS_NAME, "awsui-select-trigger-icon")
                    # button.click()
                except selenium_exceptions.NoSuchElementException:
                    selenium_driver.selenium_log.warning(f"Unable to extract options for {option_name}")
                    continue
                selenium_driver.driver.execute_script("arguments[0].scrollIntoView(true);", button)
                selenium_driver.driver.execute_script(click_js_script, button)
                # time.sleep(.5)
                try:
                    drop_down_list = WebDriverWait(selenium_driver.driver, 5).until(EC.presence_of_element_located((By.TAG_NAME, "ul")))
                    # drop_down_list = option_container.find_element(By.TAG_NAME, "ul")
                except selenium_exceptions.NoSuchElementException:
                    selenium_driver.selenium_log.warning(f"Unable to extract options for {option_name}")
                    continue

                # Check if sub lists exist
                groups = drop_down_list.find_elements(By.TAG_NAME, "ul")
                if not groups:
                    groups = [drop_down_list]

                for group in groups:
                    for option in group.find_elements(By.TAG_NAME, "li"):
                        selenium_driver.driver.execute_script("arguments[0].scrollIntoView(true);", option)
                        try:
                            # TODO: sort why these are not appearing!
                            option_value = option.find_element(By.XPATH, "./div[@data-value]").get_attribute("data-value")
                        except selenium_exceptions.NoSuchElementException:
                            selenium_driver.selenium_log.warning(f"Unable to extract options for {option.text}")
                            continue
                        query_filters[option_name].append({
                            "name": option.text,
                            "data-value": option.find_element(By.XPATH, "./div[@data-value]").get_attribute("data-value"),
                        })
            if any(query_filters.values()):
                selenium_driver.selenium_log.info(f"Collected query options from AWS Marketplace: {query_filters}")
                config.set("cache.aws.query_options", query_filters)
                config.set("cache.aws.query_options_updated_at", datetime.now().timestamp())
            else:
                selenium_driver.selenium_log.warning("Failed to collect query options on AWS Marketplace")
        finally:
            # Always quit selenium
            selenium_driver.quit_selenium()

        return query_filters

    def get_items(self, query):
        """
        Fetch items from AWS Store

        :param query:
        :return:
        """
        queries = re.split(',|\n', self.parameters.get('query', ''))
        if not queries:
            # can search all
            queries = [None]
        max_results = int(self.parameters.get('amount', 60))
        full_details = self.parameters.get('full_details', False)
        category = self.parameters.get('category', None) if self.parameters.get('category', None) != "all" else None
        creator = self.parameters.get('creator', None) if self.parameters.get('creator', None) != "all" else None
        pricing_model = self.parameters.get('pricing_model', None) if self.parameters.get('pricing_model', None) != "all" else None
        fulfillment_option_type = self.parameters.get('fulfillment_option_type', None) if self.parameters.get('fulfillment_option_type', None) != "all" else None

        for query in queries:
            page = 1
            result_number = 1
            query_url = self.get_query_url(self.search_url,
                                           query=query if query else None,
                                           category=category,
                                           creator=creator,
                                           pricing_model=pricing_model,
                                           fulfillment_option_type=fulfillment_option_type)
            success, errors = self.get_with_error_handling(query_url)
            if not success:
                self.dataset.log(f"Unable to collect AWS page {query_url}: {errors}")
                continue

            try:
                num_results = self.driver.find_element(By.XPATH, '//span[@data-test-selector="availableProductsCountMessage"]')
                self.dataset.log(f"Found total of {num_results.text} results")
            except selenium_exceptions.NoSuchElementException:
                self.dataset.log("Unknown number of results found")

            results_table = WebDriverWait(self.driver, 5).until(EC.presence_of_element_located((By.TAG_NAME, 'tbody')))
            # results_table = self.driver.find_element(By.TAG_NAME, "tbody")

            # TODO: implement pagination
            for result_block in results_table.find_elements(By.TAG_NAME, "tr"):
                # TODO: check full details
                result = self.parse_search_result(result_block)
                result["4CAT_metadata"] = {"query": query,
                                           "category": category,
                                           "creator": creator,
                                           "pricing_model": pricing_model,
                                           "fulfillment_option_type": fulfillment_option_type,
                                           "page": page,
                                           "rank": result_number,
                                           "collected_at_timestamp": datetime.now().timestamp()}
                result_number += 1
                yield result

    @staticmethod
    def parse_search_result(result_element):
        """
        Parse search result Selenium element for useful data
        """
        # icon
        thumbnail = result_element.find_element(By.XPATH, './/div[@data-semantic="logo"]').find_element(By.TAG_NAME,"img").get_attribute("src")
        # app title
        title_block = result_element.find_element(By.XPATH, './/h2[@data-semantic="title"]')
        title = title_block.text
        app_url = title_block.find_element(By.TAG_NAME, "a").get_attribute("href")
        app_id = urllib.parse.parse_qs(urllib.parse.urlparse(app_url).query).get("applicationId", [None])[0]
        # vendor
        vendor_block = result_element.find_element(By.XPATH, './/a[@data-semantic="vendorNameLink"]')
        vendor_name = vendor_block.text
        vendor_url = vendor_block.get_attribute("href")
        # pricing
        try:
            badge = result_element.find_element(By.XPATH, './/span[@data-semantic="badge-text"]').text
        except selenium_exceptions.NoSuchElementException:
            badge = None
        try:
            pricing = result_element.find_element(By.XPATH, './/div[@data-semantic="pricing"]').text
        except selenium_exceptions.NoSuchElementException:
            pricing = None
        # description
        search_description = result_element.find_element(By.XPATH, './/p[@data-semantic="desc"]').text
        return {
            "app_id": app_id,
            "title": title,
            "app_url": app_url,
            "vendor_name": vendor_name,
            "vendor_url": vendor_url,
            "badge": badge,
            "pricing": pricing,
            "search_description": search_description,
            "thumbnail": thumbnail,
        }

    @staticmethod
    def get_query_url(url, query=None, category=None, creator=None, pricing_model=None, fulfillment_option_type=None):
        filters = []
        params = {}
        if query:
            params["searchTerms"] = query
        if category:
            params["category"] = category
        if creator:
            params["CREATOR"] = creator
            filters.append("CREATOR")
        if pricing_model:
            params["PRICING_MODEL"] = pricing_model
            filters.append("PRICING_MODEL")
        if fulfillment_option_type:
            params["FULFILLMENT_OPTION_TYPE"] = fulfillment_option_type
            filters.append("FULFILLMENT_OPTION_TYPE")
        if filters:
            params["filters"] = ",".join(filters)
        url += "?" + urllib.parse.urlencode(params) if params else ""
        return url

    @staticmethod
    def map_item(item):
        """
        Map item to a standard format
        """
        item["body"] = item["search_description"]
        return MappedItem(item)

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