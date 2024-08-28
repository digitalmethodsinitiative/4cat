"""
Selenium Webpage Screenshot Scraper

Currently designed around Firefox, but can also work with Chrome; results may vary
"""
import datetime
import ural
import json
import time
import os
import re

from selenium.common import UnexpectedAlertPresentException

from extensions.web_studies.selenium_scraper import SeleniumSearch
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException
from common.lib.user_input import UserInput
from common.lib.helpers import convert_to_int, url_to_hash
from common.config_manager import config


class ScreenshotWithSelenium(SeleniumSearch):
    """
    Get HTML via the Selenium webdriver and Firefox browser
    """
    type = "image-downloader-screenshots-search"  # job ID
    extension = "zip"

    eager_selenium = True

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        options = {
            "intro-1": {
                "type": UserInput.OPTION_INFO,
                "help": "The given URLs are opened (remotely) in a Firefox browser and screenshots are then taken "
                        "according to the given parameters. The screenshots can then be downloaded as a .zip archive.\n\n"
                        "Please enter a list of urls, one per line. Invalid URLs will be ignored and duplicate URLs will "
                        "be skipped. URLs need to include a protocol, i.e. they need to start with `http://` or `https://`."
            },
            "query": {
                "type": UserInput.OPTION_TEXT_LARGE,
                "help": "List of URLs"
            },
            "capture": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Capture region",
                "options": {
                    "viewport": "Capture only browser window (viewport)",
                    "all": "Capture entire page"
                },
                "default": "viewport"
            },
            "resolution": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Window size",
                "tooltip": "Note that the browser interface is included in this resolution (as it would be in 'reality'). "
                           "Screenshots will be slightly smaller than the selected size as they do not include the "
                           "interface. Only effective when capturing the browser viewport.",
                "options": {
                    "1024x786": "1024x786",
                    "1280x720": "1280x720 (720p)",
                    "1920x1080": "1920x1080 (1080p)",
                    "1440x900": "1440x900",
                },
                "default": "1280x720"
            },
            "wait-time": {
                "type": UserInput.OPTION_TEXT,
                "help": "Load time",
                "tooltip": "Maximum seconds to wait and allow the page to finish loading. If the page finishes loading "
                           "earlier, the screenshot is taken immediately. Note: images may still take time to load after"
                           " the page itself has finished loading.",
                "default": 6,
                "min": 0,
                "max": 60,
            },
            "pause-time": {
                "type": UserInput.OPTION_TEXT,
                "help": "Pause time",
                "tooltip": "Before each screenshot, wait this many seconds before taking the screenshot. This can help "
                           "with images loading or if a site seems to be blocking the screenshot generator due to "
                           "repeat requests. Wayback Machine captures and other slow sites often require longer waits "
                           "(suggest 15 seconds).",
                "default": 0,
                "min": 0,
                "max": 30,
            },
        }
        if config.get('selenium.firefox_extensions', user=user) and config.get('selenium.firefox_extensions', user=user).get('i_dont_care_about_cookies', {}).get('path'):
            options["ignore-cookies"] = {
               "type": UserInput.OPTION_TOGGLE,
               "help": "Attempt to ignore cookie walls",
               "default": False,
               "tooltip": 'If enabled, a firefox extension will attempt to "agree" to any cookie walls automatically.'
            }

        return options

    def get_items(self, query):
        """
        Separate and check urls, then loop through each and take screenshots.

        :param query:
        :return:
        """
        urls_to_scrape = query.get('query')
        ignore_cookies = self.parameters.get("ignore-cookies")
        capture = self.parameters.get("capture")
        resolution = self.parameters.get("resolution", "1024x786")
        pause = self.parameters.get("pause-time")
        wait = self.parameters.get("wait-time")

        width = convert_to_int(resolution.split("x")[0], 1024)
        height = convert_to_int(resolution.split("x").pop(), 786) if capture == "viewport" else None

        # Staging area
        results_path = self.dataset.get_staging_area()
        self.dataset.log('Staging directory location: %s' % results_path)

        # Enable Firefox extension: i don't care about cookies
        if ignore_cookies:
            self.enable_firefox_extension(self.config.get('selenium.firefox_extensions').get('i_dont_care_about_cookies', {}).get('path'))
            self.dataset.update_status("Enabled Firefox extension: i don't care about cookies")

        screenshots = 0
        done = 0
        # Do not scrape the same site twice
        scraped_urls = set()
        total_urls = len(urls_to_scrape)
        metadata = {}

        # Set timeout for driver.get(); Web archives in particular can take a while to load
        self.set_page_load_timeout(30)

        while urls_to_scrape:
            # Grab first url
            url = urls_to_scrape.pop(0)
            if url in scraped_urls:
                done += 1
                continue

            self.dataset.update_progress(done / total_urls)
            self.dataset.log("Capturing screenshot %i of %i: %s" % (done + 1, total_urls, url))

            filename = self.filename_from_url(url) + ".png"
            result = {
                "url": url,
                "filename": filename,
                "timestamp": None,
                "error": [],
                "final_url": None,
                "subject": None,
            }

            attempts = 0
            success = False
            while attempts < 2:
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while making screenshots")

                attempts += 1
                start_time = time.time()
                get_success, errors = self.get_with_error_handling(url, max_attempts=1, wait=wait, restart_browser=True)
                if errors:
                    # Even if success, it is possible to have errors on earlier attempts
                    [result['error'].append("Attempt %i: %s" % (attempts + i, str(error))) for i, error in enumerate(errors)]
                if not get_success:
                    # Try again
                    self.dataset.log("Error collecting screenshot for %s: %s" % (url, ', '.join([str(error) for error in errors])))
                    continue

                if capture == "all":
                    # Scroll down to load all content until wait time exceeded
                    self.scroll_down_page_to_load(max_time=wait)

                if pause:
                    time.sleep(pause)

                page_loaded = self.check_page_is_loaded(max_time=max(int(wait-start_time), 1), auto_dismiss_alert=True)
                scraped_urls.add(url)

                try:
                    self.save_screenshot(results_path.joinpath(filename), width=width, height=height, viewport_only=(capture == "viewport"))
                except Exception as e:
                    self.dataset.log("Error saving screenshot for %s: %s" % (url, str(e)))
                    result['error'].append("Attempt %i: %s" % (attempts, str(e)))
                    continue
                self.dataset.log("Page load time with screenshot: %s" % (time.time() - start_time))

                # Update file attribute with url if supported
                if hasattr(os, "setxattr"):
                    os.setxattr(results_path.joinpath(filename), 'user.url', url.encode())

                screenshots += 1
                success = True
                break

            result['timestamp'] = int(datetime.datetime.now().timestamp())
            result['error'] = ', '.join(result['error'])
            if success:
                self.dataset.update_status("Processed %i/%i URL(s) with %i screenshot(s) taken" % (done + 1, total_urls, screenshots))
                # Update result
                result['final_url'] = self.driver.current_url
                result['subject'] = self.driver.title

            # Record result data
            metadata[url] = result
            done += 1

        with results_path.joinpath(".metadata.json").open("w", encoding="utf-8") as outfile:
            json.dump(metadata, outfile)

        self.dataset.log('Screenshots taken: %i' % screenshots)
        if screenshots != done:
            self.dataset.log("%i URLs could not be screenshotted" % (done - screenshots)) # this can also happens if two provided urls are the same
        # finish up
        self.dataset.update_status("Compressing images")
        return results_path

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
        preprocessed_urls = [url for url in urls if ural.is_url(url, require_protocol=True, tld_aware=True, only_http_https=True, allow_spaces_in_path=False)]

        max_sites = config.get("selenium.max_sites", user=user)
        if len(preprocessed_urls) > max_sites:
            raise QueryParametersException(f"You cannot collect more than {max_sites} screenshots per dataset. If you have more URLs, consider limiting your dataset first by either decreasing the resolution (i.e. fewer screenshots per year) or the length of the dataset (i.e. covering a shorter period of time).")

        # wayback machine toolbar remover
        # temporary inclusion to make student life easier
        detoolbarred_urls = []
        for url in preprocessed_urls:
            if re.findall(r"archive\.org/web/[0-9]+/", url):
                url = re.sub(r"archive\.org/web/([0-9]+)/", "archive.org/web/\\1if_/", url)

            detoolbarred_urls.append(url)

        preprocessed_urls = detoolbarred_urls

        if not preprocessed_urls:
            raise QueryParametersException("No valid URLs provided - please enter one valid URL per line.")

        return {
            **query,
            "query": preprocessed_urls
        }

    @staticmethod
    def filename_from_url(url):
        """
        Return a name for a given url.

        :param str url:  URL
        :return str:  Name
        """
        url_hash = url_to_hash(url)
        domain = ural.get_domain_name(url)

        # Special cases
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        if "web.archive.org/web/" in url:
            archived_url = url.split("web.archive.org/web/")[1]
            if "://" in archived_url:
                # Extract archived timestamp
                timestamp = archived_url.split("/")[0].replace("if_", "")
                # Extract archived domain
                domain = archived_url.split("://")[1].split("/")[0].strip("/") + "-archived"

        return f"{domain}-{timestamp}-{url_hash}"