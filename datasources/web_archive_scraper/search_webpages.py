"""
Twitter keyword search via the Twitter API v2
"""
from urllib.parse import urlparse
import datetime
import random

from backend.abstract.selenium_scraper import SeleniumScraper
from selenium.common.exceptions import TimeoutException
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException
from common.lib.helpers import validate_url
from common.lib.user_input import UserInput

class SearchWebArchiveWithSelenium(SeleniumScraper):
    """
    Get HTML page source from Web Archive (web.archive.org) via the Selenium webdriver and Chrome browser
    """
    type = "web_archive_scraper-search"  # job ID
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
        scrape_additional_subpages = self.parameters.get("subpages")
        urls_to_scrape = [url.strip() for url in self.parameters.get("query", "").split('\n')]
        urls_to_scrape = [{'url':url, 'num_additional_subpages': scrape_additional_subpages, 'subpage_links':[]} for url in urls_to_scrape]

        # Do not scrape the same site twice
        scraped_urls = set()

        while urls_to_scrape:
            # Grab first url
            url_obj = urls_to_scrape.pop(0)
            url = url_obj['url']
            num_additional_subpages = url_obj['num_additional_subpages']
            result = {
                "url": url,
                "final_url": None,
                "subject": None,
                "body": None,
                "visible_text": None,
                "detected_404": None,
                "timestamp": None,
                "error": False,
            }

            attempts = 0
            success = False
            while attempts < 5:
                attempts += 1
                scraped_page = self.simple_scrape_page(url)

                if scraped_page:
                    scraped_page['text'] = self.scrape_beautiful_text(scraped_page['page_source'])
                else:
                    # Hard Fail?
                    self.dataset.log('Hard fail; no page source on url: %s' % url)
                    continue

                # Redirects require waiting on Internet Archive
                if any([redirect_text in text for text in scraped_page['text']]):
                    # Update last_scraped_url for movement check
                    self.last_scraped_url = self.driver.current_url
                    self.dataset.log('Redirect url: %s' % url)
                    time.sleep(3)
                    time_to_wait = 5
                    try:
                        while time_to_wait > 0:
                            if self.check_for_movement():
                                scraped_page = self.collect_results()
                                if scraped_page:
                                    scraped_page['text'] = self.scrape_beautiful_text(scraped_page['page_source'])
                                    break
                                else:
                                    raise Exception('No page source on url: %s' % url)
                            else:
                                time_to_wait -= 1
                                time.sleep(1)
                    except Exception as e:
                        # most likely something in Selenium "went stale"
                        self.dataset.log('Redirect url unable to be scraped: %s' % url)
                        self.dataset.log(e)
                        scraped_page['error'] = e
                        break

                if any([bad_response_text in text for text in scraped_page['text']]):
                    # Bad response from Internet Archive
                    self.dataset.log('Internet Archive bad requests on url: %s' % url)
                    # Try again; Internet Achive is mean
                    time.sleep(1)
                    continue
                elif scraped_page['detected_404']:
                    self.dataset.log('404 detected on url: %s' % url)
                    scraped_page['error'] = '404 detected on url'
                    break
                else:
                    success = True
                    scraped_urls.add(url)
                    break


            if success:
                self.dataset.log('Collected: %s' % url)
                # Check is additional subpages need to be scraped
                if num_additional_subpages > 0:
                    # Check if any are available
                    if not url_obj['subpage_links']:
                        # If no, collect links
                        domain = urlparse(url).scheme + '://' + urlparse(url).netloc
                        num_of_links, links = self.get_beautiful_links(scraped_page['page_source'], domain)
                        # Randomize links (else we end up with mostly menu items at the top of webpages)
                        random.shuffle(links)
                    else:
                        links = url_obj['subpage_links']

                    # Find the first link that has not been previously scraped
                    while links:
                        link = links.pop(0)
                        if link[1] not in scraped_urls:
                            # Add it to be scraped next
                            urls_to_scrape.insert(0, {
                                'url': link[1],
                                'num_additional_subpages': num_additional_subpages - 1, # Make sure to request less additional pages
                                'subpage_links':links,
                            })
                            break

                # Update result and yield it
                result['final_url'] = scraped_page.get('final_url')
                result['body'] = scraped_page.get('page_source')
                result['subject'] = scraped_page.get('page_title')
                result['visible_text'] = scraped_page.get('text')
                result['detected_404'] = scraped_page.get('detected_404')
                result['timestamp'] = int(datetime.datetime.now().timestamp())
                result['error'] = scraped_page.get('error') # This should be None...
                yield result
            else:
                # Still need subpages?
                if num_additional_subpages > 0:
                    # Add the next one if it exists
                    links = url_obj['subpage_links']
                    while links:
                        link = links.pop(0)
                        if link[1] not in scraped_urls:
                            # Add it to be scraped next
                            urls_to_scrape.insert(0, {
                                'url': link[1],
                                'num_additional_subpages': num_additional_subpages - 1, # Make sure to request less additional pages
                                'subpage_links':links,
                            })
                            break
                # Unsure if we should return ALL failures, but certainly the originally supplied urls
                result['timestamp'] = int(datetime.datetime.now().timestamp())
                result['error'] = scraped_page.get('error')
                yield result

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
