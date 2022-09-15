"""
Selenium Webpage Screenshot Scraper

Currently designed around Firefox, but can also work with Chrome; results may vary
"""
from hashlib import sha256
import datetime
import json
import os

from backend.abstract.selenium_scraper import SeleniumScraper
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException
from common.lib.helpers import validate_url
from common.lib.user_input import UserInput


class ScreenshotWithSelenium(SeleniumScraper):
    """
    Get HTML via the Selenium webdriver and Firefox browser
    """
    type = "url_screenshots-search"  # job ID
    extension = "zip"
    max_workers = 1

    options = {
        "intro-1": {
            "type": UserInput.OPTION_INFO,
            "help": "This data source uses [Selenium](https://selenium-python.readthedocs.io/) in combination with "
                    "a [Firefox webdriver](https://github.com/mozilla/geckodriver/releases) and Firefox for linux "
                    "to take screenshots of webpages. "
        },
        "query-info": {
            "type": UserInput.OPTION_INFO,
            "help": "Please enter a list of urls one per line."
        },
        "query": {
            "type": UserInput.OPTION_TEXT_LARGE,
            "help": "List of urls"
        },
        "wait-time": {
            "type": UserInput.OPTION_TEXT,
            "help": "Time in seconds to wait for page to load",
            "default": 2,
            "min": 0,
            "max": 5,
        },
        "ignore-cookies": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Attempt to ignore cookie requests",
            "default": True,
            "tooltip": 'If enabled, a firefox extension will attempt to "agree" to any cookie requests'
        },
    }

    def get_items(self, query):
        """
        Separate and check urls, then loop through each and take screenshots.

        :param query:
        :return:
        """
        self.dataset.log('Query: %s' % str(query))
        self.dataset.log('Parameters: %s' % str(self.parameters))
        urls_to_scrape = query.get('urls')
        ignore_cookies = self.parameters.get("ignore-cookies")
        wait = self.parameters.get("wait-time")

        # Staging area
        results_path = self.dataset.get_staging_area()
        self.dataset.log('Staging directory location: %s' % results_path)

        # Enable Firefox extension: i don't care about cookies
        if ignore_cookies:
            # TODO: fix this up to use our config and error handle a shitty extension
            self.driver.enable_firefox_extension('/usr/src/app/jid1-KKzOGWgsW3Ao4Q@jetpack.xpi')

        screenshots = 0
        processed_urls = 0
        total_urls = len(urls_to_scrape)
        # Do not scrape the same site twice
        scraped_urls = set()
        metadata = {}
        while urls_to_scrape:
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while scraping urls from the Web Archive")
            # Grab first url
            url = urls_to_scrape.pop(0)
            result = {
                "url": url,
                "filename": None,
                "timestamp": None,
                "error": [],
                "final_url": None,
                "subject": None,
            }

            attempts = 0
            success = False
            while attempts < 2:
                attempts += 1
                self.reset_current_page()
                try:
                    self.driver.get(url)
                except Exception as e:
                    # TODO: This is way too broad and should be handled in the SeleniumWrapper
                    self.dataset.log("Error collectiong %s: %s" % (url, str(e)))
                    result['error'].append("Attempt %i: %s" % (attempts, str(e)))
                    continue

                if self.check_for_movement():
                    hash = sha256(url.encode()).hexdigest()[:13]
                    filename = f'{hash}.png'
                    try:
                        self.save_screenshot(results_path.joinpath(filename))
                    except Exception as e:
                        self.dataset.log("Error saving screenshot for %s: %s" % (url, str(e)))
                        result['error'].append("Attempt %i: %s" % (attempts, str(e)))
                        continue
                    result['filename'] = filename
                    # Update file attribute with url
                    os.setxattr(results_path.joinpath(filename), 'user.url', url.encode())
                    screenshots += 1
                    success = True
                else:
                    # No page was reached...
                    result['error'].append("Driver was not able to navigate to page")

            result['timestamp'] = int(datetime.datetime.now().timestamp())
            result['error'] = ', '.join(result['error'])
            if success:
                self.dataset.log('Collected: %s' % url)
                # Update result and yield it
                result['final_url'] = self.driver.current_url
                result['subject'] = self.driver.title

            # Record result data
            metadata[url] = result

        with results_path.joinpath(".metadata.json").open("w", encoding="utf-8") as outfile:
            json.dump(metadata, outfile)

        self.dataset.log('Screenshots taken: %i' % screenshots)
        # finish up
        self.dataset.update_status("Compressing images")
        self.write_archive_and_finish(results_path, finish=False)

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
        urls = [url.strip() for url in query.get("query", "").replace("\n", ",").split(',')]
        preprocessed_urls = [url for url in urls if validate_url(url)]
        if not preprocessed_urls:
            raise QueryParametersException("No Urls detected!")

        return {
            "urls": preprocessed_urls,
            "wait-time": query.get("wait-time"),
            "ignore-cookies": query.get("ignore-cookies"),
            }
