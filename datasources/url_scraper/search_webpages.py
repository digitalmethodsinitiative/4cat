"""
Twitter keyword search via the Twitter API v2
"""
from urllib.parse import urlparse
import datetime

from backend.abstract.selenium_scraper import SeleniumScraper
from selenium.common.exceptions import TimeoutException
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException
from common.lib.helpers import validate_url
from common.lib.user_input import UserInput

class SearchWithSelenium(SeleniumScraper):
    """
    Get HTML via the Selenium webdriver and Chrome browser
    """
    type = "url_scraper-search"  # job ID
    max_workers = 1

    options = {
        "intro-1": {
            "type": UserInput.OPTION_INFO,
            "help": "This data source uses [Selenium](https://selenium-python.readthedocs.io/) in combination with "
                    "a [Chrome webdriver](https://sites.google.com/chromium.org/driver/) and Google Chrome for linux "
                    "to scrape the HTML source code. "
                    "\n"
                    "By mimicing a person using an actual browser, this method results in source code that closer "
                    "resembles the source code an actual user receives when compared with simple HTML requests. It "
                    "will also render JavaScript that starts as soon as a url is retrieved by a browser. "
        },
        "query-info": {
            "type": UserInput.OPTION_INFO,
            "help": "Please enter a list of urls one per line."
        },
        "query": {
            "type": UserInput.OPTION_TEXT_LARGE,
            "help": "List of urls"
        },
        "subpages": {
            "type": UserInput.OPTION_TEXT,
            "help": "Crawl additional host links/subpages",
            "min": 0,
            "max": 5,
            "default": 0
        },
    }

    def get_items(self, query):
        """
        Separate and check urls, then loop through each and collects the HTML.

        :param query:
        :return:
        """
        num_of_subpages = self.parameters.get("subpages")
        urls = [url.strip() for url in self.parameters.get("query", "").split('\n')]
        # Holds additional links if crawling desired
        additional_urls_groups_to_scrape = []

        # First scrape all original urls
        for url in urls:
            result = self.collect_page_result(url)

            # Add additional links to be scraped afterwards
            if num_of_subpages > 0:
                host = urlparse(url).netloc
                links = self.collect_links()
                additional_urls_groups_to_scrape.append((host, url, links))

            yield result

        # Scrape additional subpages if requested
        if num_of_subpages > 0:
            for url_group in additional_urls_groups_to_scrape:
                collected_pages = 0
                host = url_group[0]
                original_link = url_group[1]
                links = url_group[2]
                for url in links:
                    # Break if adequate pages collected
                    if collected_pages >= num_of_subpages:
                        break
                    # Check that url is in same host and not the original link
                    if urlparse(url).netloc == host and url != original_link:
                        # Attempt to scrape url
                        result = self.collect_page_result(url)
                        # Check that results was successfully scraped
                        if result['error'] is False:
                            collected_pages += 1
                            yield result

    def collect_page_result(self, url):
        """
        Crawls a url and creates a results object with necessary information
        """
        result = {
            "url": url,
            "final_url": None,
            "subject": None,
            "body": None,
            "detected_404": None,
            "timestamp": None,
            "error": False,
        }
        if not validate_url(url):
            # technically we have already validated, but best to inform user which urls are invalid
            result['timestamp'] = int(datetime.datetime.now().timestamp())
            result['error'] = 'Invalid URL format'
        else:
            # Try to scrape the url
            try:
                self.dataset.log('Scraping url: %s' % url)
                scraped_page = self.simple_scrape_page(url)
            except TimeoutException as e:
                result['timestamp'] = int(datetime.datetime.now().timestamp())
                result['error'] = 'Selenium TimeoutException: %s' % e
                return result

            # simple_scrape_page returns False if the browser did not load a new page
            if scraped_page:
                result['final_url'] = scraped_page.get('final_url')
                result['body'] = scraped_page.get('page_source')
                result['subject'] = scraped_page.get('page_title')
                result['detected_404'] = scraped_page.get('detected_404')
                result['timestamp'] = int(datetime.datetime.now().timestamp())
            else:
                result['timestamp'] = int(datetime.datetime.now().timestamp())
                result['error'] = 'Unable to scrape url'

        return result


    @staticmethod
    def validate_query(query, request, user):
        """
        Validate input for a dataset query on the Selenium Webpage Scraper.

        Will raise a QueryParametersException if invalid parameters are
        encountered. Parameters are additionally sanitised.

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param User user:  User object of user who has submitted the query
        :return dict:  Safe query parameters
        """

        # this is the bare minimum, else we can't narrow down the full data set
        if not query.get("query", None):
            raise QueryParametersException("Please provide a List of urls.")

        urls = [url.strip() for url in query.get("query", "").split('\n')]
        preprocessed_urls = [url for url in urls if validate_url(url)]
        if not preprocessed_urls:
            raise QueryParametersException("No Urls detected!")

        return {
            "query": query.get("query"),
            "subpages": query.get("subpages", 0)
            }
