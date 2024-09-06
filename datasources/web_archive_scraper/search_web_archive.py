"""
Web Archives HTML Scraper

Currently designed around Firefox, but can also work with Chrome; results may vary
"""
from urllib.parse import urlparse
import datetime
import requests
import random
import time

from dateutil.relativedelta import relativedelta

from backend.lib.selenium_scraper import SeleniumSearch
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException, ProcessorException
from common.lib.helpers import validate_url
from common.lib.item_mapping import MappedItem
from common.lib.user_input import UserInput

from common.config_manager import config

class SearchWebArchiveWithSelenium(SeleniumSearch):
    """
    Get HTML page source from Web Archive (web.archive.org) via the Selenium webdriver and Firefox browser
    """
    type = "web_archive_scraper-search"  # job ID
    extension = "ndjson"

    # Web Archive returns "internal error" sometimes even when snapshot exists; we retry
    bad_response_text = ['This snapshot cannot be displayed due to an internal error', 'The Wayback Machine requires your browser to support JavaScript']
    # Web Archive will load and then redirect after a few seconds; check for new page to load
    redirect_text = ['Got an HTTP 302 response at crawl time', 'Got an HTTP 301 response at crawl time']

    urls_to_exclude = ['mailto:', 'javascript', 'archive.org/about', 'archive.org/account/']

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
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
            "frequency": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Frequency over time period",
                "tooltip": "Default 'First Available' scrapes the first available result after start date",
                "options": {
                    "first": "First Available",
                    "monthly": "Monthly",
                    "weekly": "Weekly",
                    "daily": "Daily",
                    "yearly": "Yearly"
                },
                "default": "first"
            },
            "daterange": {
                "type": UserInput.OPTION_DATERANGE,
                "tooltip": "Scrapes first available page after start date; Uses start and end date for frequency",
                "help": "Date range"
            },
        }

        if config.get("selenium.display_advanced_options", False, user=user):
            options["subpages"] = {
                "type": UserInput.OPTION_TEXT,
                "help": "Crawl additional links/subpages",
                "min": 0,
                "max": 5,
                "default": 0,
                "tooltip": "If enabled, the scraper will also crawl and collect random links found on the provided page."
            }
            options["http_request"] = {
                "type": UserInput.OPTION_CHOICE,
                "help": "HTTP or Selenium request",
                "tooltip": "Scrape data with HTTP (python request library) and/or Selenium (automated browser to better imitate a real user); HTTP response is added to body field, but not currently parsed to extract text",
                "options": {
                    "both": "Both HTTP request and Selenium WebDriver",
                    "selenium_only": "Only use Selenium WebDriver",
                },
                "default": "selenium_only"
            }

        return options

    def get_items(self, query):
        """
        Separate and check urls, then loop through each and collects the HTML.

        :param query:
        :return:
        """

        http_request = self.parameters.get("http_request", "selenium_only") == 'both'
        if http_request:
            self.dataset.update_status('Scraping Web Archives with Selenium %s and HTTP Requests' % config.get('selenium.browser'))
        else:
            self.dataset.update_status('Scraping Web Archives with Selenium %s' % config.get('selenium.browser'))
        scrape_additional_subpages = self.parameters.get("subpages", 0)

        preprocessed_urls = []
        for url in query.get('validated_urls'):
            url_group = SearchWebArchiveWithSelenium.create_web_archive_urls(url, query["min_date"], query["max_date"],
                                                                             query.get('frequency'))
            [preprocessed_urls.append(new_url) for new_url in url_group]
        urls_to_scrape = [{'url':url['url'], 'base_url':url['base_url'], 'year':url['year'], 'num_additional_subpages': scrape_additional_subpages, 'subpage_links':[]} for url in preprocessed_urls]

        # Do not scrape the same site twice
        scraped_urls = set()
        num_urls = len(urls_to_scrape)
        if scrape_additional_subpages:
            num_urls = num_urls * (scrape_additional_subpages + 1)
        done = 0

        while urls_to_scrape:
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while scraping urls from the Web Archive")

            self.dataset.update_progress(done / num_urls)
            self.dataset.update_status("Captured %i of %i possible URLs" % (done, num_urls))

            # Grab first url
            url_obj = urls_to_scrape.pop(0)
            url = url_obj['url']
            num_additional_subpages = url_obj['num_additional_subpages']
            result = {
                "base_url": url_obj['base_url'],
                "year": url_obj['year'],
                "url": url,
                "final_url": None,
                "subject": None,
                "body": None,
                "html": None,
                "http_html": None,
                "detected_404": None,
                "timestamp": None,
                "error": '',
            }

            attempts = 0
            success = False
            scraped_page = None
            while attempts < 2:
                attempts += 1
                try:
                    scraped_page = self.simple_scrape_page(url, extract_links=True)
                except Exception as e:
                    self.dataset.log('Url %s unable to be scraped with error: %s' % (url, str(e)))
                    self.restart_selenium()
                    result['error'] += 'SCAPE ERROR:\n' + str(e) + '\n'
                    continue

                if scraped_page:
                    scraped_page['text'] = self.scrape_beautiful_text(scraped_page['page_source'])
                else:
                    # Hard Fail?
                    self.dataset.log('Hard fail; no page source on url: %s' % url)
                    result['error'] += 'SCAPE ERROR:\n No page source on url; retrying\n'
                    continue

                # Redirects require waiting on Internet Archive
                if any([any([redirect_text in text for redirect_text in self.redirect_text]) for text in scraped_page['text']]):
                    # Update last_scraped_url for movement check
                    self.last_scraped_url = self.driver.current_url
                    self.dataset.log('Redirect url: %s' % url)
                    time.sleep(3)
                    time_to_wait = 5
                    try:
                        while time_to_wait > 0:
                            if self.check_for_movement():
                                time.sleep(5)
                                scraped_page = self.collect_results(url)
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
                        redirect_error = 'REDIRECT ERROR:\n%s\n' % str(e)
                        self.dataset.log(redirect_error)
                        result['error'] += redirect_error
                        break

                if any([any([bad_response in text for bad_response in self.bad_response_text]) for text in scraped_page['text']]):
                    # Bad response from Internet Archive
                    bad_internet_archive_request = 'Web Archive bad request detected on url: %s\nTrying again...' % url
                    self.dataset.log(bad_internet_archive_request)
                    result['error'] += bad_internet_archive_request
                    # Try again; Internet Achive is mean
                    time.sleep(1)
                    continue
                elif scraped_page['detected_404']:
                    four_oh_four_error = '404 detected on url: %s\n' % url
                    self.dataset.log(four_oh_four_error)
                    result['error'] += four_oh_four_error
                    break
                else:
                    success = True
                    scraped_urls.add(url)
                    break

            if success:
                self.dataset.log('Collected: %s' % url)
                done += 1
                result['final_url'] = scraped_page.get('final_url')
                result['body'] = scraped_page.get('text')
                result['subject'] = scraped_page.get('page_title')
                result['html'] = scraped_page.get('page_source')
                result['detected_404'] = scraped_page.get('detected_404')
                result['timestamp'] = int(datetime.datetime.now().timestamp())
                result['error'] += scraped_page.get('error', '') if scraped_page.get('error') else ''
                result['selenium_links'] = scraped_page.get('links') if scraped_page.get('links') else scraped_page.get('collect_links_error')

                # Collect links from page source
                domain = urlparse(url).scheme + '://' + urlparse(url).netloc
                num_of_links, links = self.get_beautiful_links(scraped_page['page_source'], domain)
                result['scraped_links'] = links

                # Check is additional subpages need to be scraped
                if num_additional_subpages > 0:
                    # Check if any are available
                    if not url_obj['subpage_links']:
                        # If no, collect links
                        # Randomize links (else we end up with mostly menu items at the top of webpages)
                        random.shuffle(links)
                    else:
                        links = url_obj['subpage_links']

                    # Find the first link that has not been previously scraped
                    while links:
                        link = links.pop(0)
                        if self.check_exclude_link(link.get('url'), scraped_urls, base_url='.'.join(urlparse(url_obj['base_url']).netloc.split('.')[1:]), bad_url_list=self.urls_to_exclude):
                            # Add it to be scraped next
                            urls_to_scrape.insert(0, {
                                'url': link.get('url'),
                                'base_url': url_obj['base_url'],
                                'year': url_obj['year'],
                                'num_additional_subpages': num_additional_subpages - 1, # Make sure to request less additional pages
                                'subpage_links':links,
                            })
                            break

                if http_request:
                    try:
                        http_response = self.request_get_w_error_handling(scraped_page.get('final_url'), timeout=120)
                        self.dataset.log('Collected HTTP response: %s' % scraped_page.get('final_url'))
                        result['http_html'] = http_response.text
                    except Exception as e:
                        result['http_html'] = None
                        http_error = '\nHTTP ERROR:\n' + str(e)
                        result['error'] = 'SELENIUM ERROR:\n' + str(result['error']) + http_error

                yield result
            else:
                # Still need subpages?
                if num_additional_subpages > 0:
                    # Add the next one if it exists
                    links = url_obj['subpage_links']
                    while links:
                        link = links.pop(0)
                        if self.check_exclude_link(link.get('url'), scraped_urls, base_url='.'.join(urlparse(url_obj['base_url']).netloc.split('.')[1:]), bad_url_list=self.urls_to_exclude):
                            # Add it to be scraped next
                            urls_to_scrape.insert(0, {
                                'url': link.get('url'),
                                'base_url': url_obj['base_url'],
                                'year': url_obj['year'],
                                'num_additional_subpages': num_additional_subpages - 1, # Make sure to request less additional pages
                                'subpage_links':links,
                            })
                            break
                # Unsure if we should return ALL failures, but certainly the originally supplied urls
                result['timestamp'] = int(datetime.datetime.now().timestamp())
                if scraped_page:
                    result['error'] += scraped_page.get('error', '') if scraped_page.get('error') else ''
                else:
                    # missing error...
                    result['error'] += 'Unable to scrape'

                yield result


    def request_get_w_error_handling(self, url, retries=3, **kwargs):
        """
        Try requests.get() and logging error in dataset.log().

        Retries ConnectionError three times by default
        """
        try:
            response = requests.get(url, **kwargs)
        except requests.exceptions.Timeout as e:
            self.dataset.log("Error: Timeout on url %s: %s" % (url, str(e)))
            raise e
        except requests.exceptions.SSLError as e:
            self.dataset.log("Error: SSLError on url %s: %s" % (url, str(e)))
            raise e
        except requests.exceptions.TooManyRedirects as e:
            self.dataset.log("Error: TooManyRedirects on url %s: %s" % (url, str(e)))
            raise e
        except requests.exceptions.ConnectionError as e:
            if retries > 0:
                response = self.request_get_w_error_handling(url, retries=retries - 1, **kwargs)
            else:
                self.dataset.log("Error: ConnectionError on url %s: %s" % (url, str(e)))
                raise e
        return response

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
        page_result['body'] = '\n'.join(page_result.get('body')) if page_result.get('body') else ''
        # Convert list of link objects to comma seperated urls
        page_result['scraped_links'] = ','.join([link.get('url') for link in page_result.get('scraped_links')]) if page_result.get('scraped_links') else ''
        # Convert list of links to comma seperated urls
        page_result['selenium_links'] = ','.join(map(str,page_result.get('selenium_links'))) if type(page_result.get('selenium_links')) == list else page_result.get('selenium_links', '')

        return MappedItem(page_result)

    @staticmethod
    def create_web_archive_urls(url, start_date, end_date, frequency):
        """
        Combines url with Web Archive base (https://web.archive.org/web/) if
        needed along with start date to create urls. Will use frequency to
        create additional urls if needed.

        :param str url: url as string
        :param start_date: starting date
        :param end_date: ending date
        :param string frequency: frequency of scrape
        :return list: List of urls to scrape
        """
        web_archive_url = 'https://web.archive.org/web/'
        min_date = datetime.datetime.fromtimestamp(int(start_date))
        max_date = datetime.datetime.fromtimestamp(int(end_date))

        # if already formated, return as is
        if web_archive_url == url[:len(web_archive_url)]:
            return [{'base_url': url, 'year': min_date.year, 'url': url}]

        if frequency == 'yearly':
            years = [year for year in range(min_date.year, max_date.year+1)]

            return  [
                     {
                     'base_url': url,
                     'year': year,
                     'url': web_archive_url + str(year) + min_date.strftime('%m%d') + '/' + url,
                     }
                    for year in years]

        elif frequency in ('monthly', 'weekly', 'daily'):
            dates_needed = []
            current = min_date
            while current <= max_date:
                dates_needed.append({
                     'base_url': url,
                     'year': current.year,
                     'url': web_archive_url + current.strftime('%Y%m%d') + '/' + url,
                     })
                if frequency == 'weekly':
                    current += relativedelta(weeks=1)
                elif frequency == 'monthly':
                    current += relativedelta(months=1)
                elif frequency == 'daily':
                    current += relativedelta(days=1)
                else:
                    raise ProcessorException("Frequency %s not implemented!" % frequency)

            return dates_needed

        elif frequency == 'first':
            return [{'base_url': url, 'year': min_date.year, 'url': web_archive_url + min_date.strftime('%Y%m%d') + '/' + url}]

        else:
            raise Exception('frequency type %s not implemented!' % frequency)

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
        validated_urls = [url for url in urls if validate_url(url)]
        if not validated_urls:
            raise QueryParametersException("No Urls detected!")

        # the dates need to make sense as a range to search within
        query["min_date"], query["max_date"] = query.get("daterange")
        if query["max_date"] is None:
            query["max_date"] = int(datetime.datetime.now().timestamp())
        if query["max_date"] < query["min_date"]:
            raise QueryParametersException("End date must be after start date.")

        return {
            "query": query.get("query"),
            "min_date": query.get("min_date"),
            "max_date": query.get("max_date"),
            "validated_urls": validated_urls,
            "frequency": query.get("frequency"),
            "subpages": query.get("subpages", 0),
            'http_request': query.get("http_request", "selenium_only"),
            }
