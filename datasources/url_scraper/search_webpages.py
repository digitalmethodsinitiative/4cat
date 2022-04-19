"""
Selenium Webpage HTML Scraper

Currently designed around Firefox, but can also work with Chrome; results may vary
"""
from urllib.parse import urlparse
import datetime
import random

from backend.abstract.selenium_scraper import SeleniumScraper
from selenium.common.exceptions import TimeoutException
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException
from common.lib.helpers import validate_url
from common.lib.user_input import UserInput

class SearchWithSelenium(SeleniumScraper):
    """
    Get HTML via the Selenium webdriver and Firefox browser
    """
    type = "url_scraper-search"  # job ID
    extension = "ndjson"
    max_workers = 1

    options = {
        "intro-1": {
            "type": UserInput.OPTION_INFO,
            "help": "This data source uses [Selenium](https://selenium-python.readthedocs.io/) in combination with "
                    "a [Firefox webdriver](https://github.com/mozilla/geckodriver/releases) and Firefox for linux "
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
        self.dataset.log('Query: %s' % str(query))
        self.dataset.log('Parameters: %s' % str(self.parameters))
        scrape_additional_subpages = self.parameters.get("subpages")
        urls_to_scrape = [{'url':url, 'base_url':url, 'num_additional_subpages': scrape_additional_subpages, 'subpage_links':[]} for url in query.get('urls')]

        # Do not scrape the same site twice
        scraped_urls = set()

        while urls_to_scrape:
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while scraping urls from the Web Archive")
            # Grab first url
            url_obj = urls_to_scrape.pop(0)
            url = url_obj['url']
            num_additional_subpages = url_obj['num_additional_subpages']
            result = {
                "base_url": url_obj['base_url'],
                "url": url,
                "final_url": None,
                "subject": None,
                "body": None,
                "html": None,
                "detected_404": None,
                "timestamp": None,
                "error": '',
            }

            attempts = 0
            success = False
            while attempts < 2:
                attempts += 1
                try:
                    scraped_page = self.simple_scrape_page(url, extract_links=True)
                except Exception as e:
                    self.dataset.log('Url %s unable to be scraped with error: %s' % (url, str(e)))
                    self.restart_selenium()
                    scraped_page['error'] = 'SCAPE ERROR:\n' + str(e) + '\n'
                    continue

                # Check for results and collect text
                if scraped_page:
                    scraped_page['text'] = self.scrape_beautiful_text(scraped_page['page_source'])
                else:
                    # Hard Fail?
                    self.dataset.log('Hard fail; no page source on url: %s' % url)
                    continue

                # Check for 404 errors
                if scraped_page['detected_404']:
                    four_oh_four_error = '404 detected on url: %s\n' % url
                    self.dataset.log(four_oh_four_error)
                    scraped_page['error'] = four_oh_four_error if not scraped_page.get('error', False) else scraped_page['error'] + four_oh_four_error
                    break
                else:
                    success = True
                    scraped_urls.add(url)
                    break

            if success:
                self.dataset.log('Collected: %s' % url)
                # Update result and yield it
                result['final_url'] = scraped_page.get('final_url')
                result['body'] = scraped_page.get('text')
                result['subject'] = scraped_page.get('page_title')
                result['html'] = scraped_page.get('page_source')
                result['detected_404'] = scraped_page.get('detected_404')
                result['timestamp'] = int(datetime.datetime.now().timestamp())
                result['error'] = scraped_page.get('error') # This should be None...
                result['selenium_links'] = scraped_page.get('links') if scraped_page.get('links') else scraped_page.get('collect_links_error')

                # Collect links from page source
                domain = urlparse(url).scheme + '://' + urlparse(url).netloc
                num_of_links, links = self.get_beautiful_links(scraped_page['page_source'], domain)
                result['scraped_links'] = links

                # Check if additional subpages need to be scraped
                if num_additional_subpages > 0:
                    # Check if any link from base_url are available
                    if not url_obj['subpage_links']:
                        # If not, use this pages links collected above
                        # TODO could also use selenium detected links; results vary, check as they are also being stored
                        # Randomize links (else we end up with mostly menu items at the top of webpages)
                        random.shuffle(links)
                    else:
                        links = url_obj['subpage_links']

                    # Find the first link that has not been previously scraped
                    while links:
                        link = links.pop(0)
                        if self.check_exclude_link(link.get('url'), scraped_urls, base_url='.'.join(urlparse(url_obj['base_url']).netloc.split('.')[1:])):
                            # Add it to be scraped next
                            urls_to_scrape.insert(0, {
                                'url': link.get('url'),
                                'base_url': url_obj['base_url'],
                                'num_additional_subpages': num_additional_subpages - 1, # Make sure to request less additional pages
                                'subpage_links':links,
                            })
                            break

                yield result

            else:
                # Page was not successfully scraped
                # Still need subpages?
                if num_additional_subpages > 0:
                    # Add the next one if it exists
                    links = url_obj['subpage_links']
                    while links:
                        link = links.pop(0)
                        if self.check_exclude_link(link.get('url'), scraped_urls, base_url='.'.join(urlparse(url_obj['base_url']).netloc.split('.')[1:])):
                            # Add it to be scraped next
                            urls_to_scrape.insert(0, {
                                'url': link.get('url'),
                                'base_url': url_obj['base_url'],
                                'num_additional_subpages': num_additional_subpages - 1, # Make sure to request less additional pages
                                'subpage_links':links,
                            })
                            break
                # Unsure if we should return ALL failures, but certainly the originally supplied urls
                result['timestamp'] = int(datetime.datetime.now().timestamp())
                if scraped_page:
                    result['error'] = scraped_page.get('error')
                else:
                    # missing error...
                    result['error'] = 'Unable to scrape'

                yield result
    @staticmethod
    def map_item(page_result):
        """
        Map webpage result from JSON to 4CAT expected values.

        This makes some minor changes to ensure processors can handle specific
        columns and "export to csv" has formatted data.

        :param json page_result:  Object with original datatypes
        :return dict:  Dictionary in the format expected by 4CAT
        """
        # Convert list of text strings to one string
        page_result['body'] = '\n'.join(page_result.get('body'))
        # Convert list of link objects to comma seperated urls
        page_result['scraped_links'] = ','.join([link.get('url') for link in page_result['scraped_links']])
        # Convert list of links to comma seperated urls
        page_result['selenium_links'] = ','.join(map(str,page_result['selenium_links'])) if type(page_result['selenium_links']) == list else page_result['selenium_links']

        return page_result


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
            "urls": preprocessed_urls,
            "subpages": query.get("subpages", 0)
            }
