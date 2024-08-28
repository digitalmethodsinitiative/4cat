"""
Screenshot URLs w/ Selenium
"""
import datetime
import re
import time
from selenium.common import UnexpectedAlertPresentException

from backend.lib.processor import BasicProcessor
from common.lib.helpers import UserInput, extract_urls_from_string, convert_to_int
from common.lib.exceptions import ProcessorInterruptedException, ProcessorException
from extensions.web_studies.selenium_scraper import SeleniumWrapper
from extensions.web_studies.datasources.url_screenshots.search_webpage_screenshots  import ScreenshotWithSelenium
from common.config_manager import config

import os
import json

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class ScreenshotURLs(BasicProcessor):
    """
    Screenshot URLs w/ Selenium
    """
    type = "image-downloader-screenshot-urls"  # job type ID
    category = "Visual"  # category
    title = "Collect Screenshots of URLs"  # title displayed in UI
    description = "Use a Selenium based crawler to request each url and take a screenshot image of the webpage"
    extension = "zip"  # extension of result file, used internally and in UI

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        """
        Update columns field with actual columns
        """
        options = {
            "columns": {
                "type": UserInput.OPTION_TEXT,
                "help": "Column(s) to extract URLs",
                "default": "body",
                "tooltip": "URLs will be extracted from each enabled column."
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
                "tooltip": "Wait this many seconds before taking the screenshot, to allow the page to finish loading "
                           "first. If the page finishes loading earlier, the screenshot is taken immediately.",
                "default": 6,
                "min": 0,
                "max": 60,
            },
            "pause-time": {
                "type": UserInput.OPTION_TEXT,
                "help": "Pause time",
                "tooltip": "Before each screenshot, wait this many seconds before taking the screenshot. This can help "
                           "with images loading or if a site seems to be blocking the screenshot generator due to "
                           "repeat requests.",
                "default": 0,
                "min": 0,
                "max": 15,
            },
            "split-comma": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Split column values by comma?",
                "default": False,
                "tooltip": "If enabled, columns can contain multiple URLs separated by commas, which will be considered "
                           "separately"
            },
        }

        if parent_dataset and parent_dataset.get_columns():
            columns = parent_dataset.get_columns()
            options["columns"]["type"] = UserInput.OPTION_MULTI
            options["columns"]["inline"] = True
            options["columns"]["options"] = {v: v for v in columns}
            options["columns"]["default"] = ['body']
            for default in ['final_url', 'url', 'urls', 'links']:
                if default in columns:
                    options["columns"]["default"] = [default]
                    break

        if config.get('selenium.firefox_extensions', user=user) and config.get('selenium.firefox_extensions', user=user).get('i_dont_care_about_cookies', {}).get('path'):
            options['ignore-cookies'] = {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Attempt to ignore cookie requests",
                "default": False,
                "tooltip": "If enabled, a firefox extension [i don't care about cookies](https://addons.mozilla.org/nl/firefox/addon/i-dont-care-about-cookies/) will be used"
            }

        return options

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow processor on datasets

        :param module: Dataset or processor to determine compatibility with
        """
        return module.is_dataset() and module.get_extension() in ("csv", "ndjson")

    def process(self):
        """
        Extracts URLs and uses SeleniumScraper to take screenshots
        """
        if self.source_dataset.num_rows == 0:
            self.dataset.update_status("No items in dataset.", is_final=True)
            self.dataset.finish(0)
            return

        # Collect URLs from parent dataset
        split_comma = self.parameters.get("split-comma")
        columns = self.parameters.get("columns")
        if not columns:
            self.dataset.update_status("No columns selected; no screenshots taken.", is_final=True)
            self.dataset.finish(0)
            return

        urls = {}
        self.dataset.update_status("Reading source file and extracting URLs")
        item_index = 0
        for post in self.source_dataset.iterate_items(self):
            post_urls = set()

            # loop through all columns and process values for item
            for column in columns:
                value = post.get(column)
                if not value:
                    continue

                # remove all whitespace from beginning and end (needed for single URL check)
                values = [value.strip()]
                if split_comma:
                    values = values[0].split(',')

                for value in values:
                    post_urls |= set(extract_urls_from_string(value))

            for post_url in post_urls:
                if post_url not in urls:
                    urls[post_url] = {'ids': {str(post.get('id', 0))}}
                else:
                    urls[post_url]['ids'].add(str(post.get('id', 0)))

        if not urls:
            self.dataset.update_status("No urls identified.", is_final=True)
            self.dataset.finish(0)
            return
        else:
            self.dataset.log('Collected %i urls.' % len(urls))

        # Create results folder
        results_path = self.dataset.get_staging_area()
        self.dataset.log('Staging directory location: %s' % results_path)

        # Start Selenium
        ignore_cookies = False  # self.parameters.get("ignore-cookies")
        capture = self.parameters.get("capture")
        resolution = self.parameters.get("resolution", "1024x786")
        pause = self.parameters.get("pause-time")
        wait = self.parameters.get("wait-time")

        width = convert_to_int(resolution.split("x")[0], 1024)
        height = convert_to_int(resolution.split("x").pop(), 786) if capture == "viewport" else None

        self.dataset.update_status("Starting Selenium Webdriver.")
        webdriver = SeleniumWrapper()
        try:
            webdriver.start_selenium()
            if ignore_cookies:
                webdriver.enable_firefox_extension(
                    self.config.get('selenium.firefox_extensions').get('i_dont_care_about_cookies', {}).get('path'))
                self.dataset.update_status("Enabled Firefox extension: i don't care about cookies")
        except ProcessorException as e:
            self.dataset.log("Error starting Selenium: %s" % str(e))
            self.dataset.update_status("Error starting Selenium; contact admin.", is_final=True)
            self.dataset.finish(0)
            webdriver.quit_selenium()
            return

        # Set timeout for driver.get(); Web archives in particular can take a while to load
        webdriver.set_page_load_timeout(30)

        screenshots = 0
        done = 0
        total_urls = len(urls)
        # Do not scrape the same site twice
        scraped_urls = set()
        metadata = {}
        for url, post_ids in urls.items():
            # Remove Archive.org toolbar
            if re.findall(r"archive\.org/web/[0-9]+/", url):
                url = re.sub(r"archive\.org/web/([0-9]+)/", "archive.org/web/\\1if_/", url)

            scraped_urls.add(url)
            filename = ScreenshotWithSelenium.filename_from_url(url) + ".png"
            result = {
                "url": url,
                "filename": filename,
                "timestamp": None,
                "error": [],
                "final_url": None,
                "subject": None,
                "post_ids": ", ".join(list(post_ids['ids'])),
            }

            attempts = 0
            success = False
            while attempts < 2:
                # Stop processing if worker has been asked to stop
                if self.interrupted:
                    webdriver.quit_selenium()
                    raise ProcessorInterruptedException("Interrupted while collecting screenshots.")

                attempts += 1
                get_success, errors = webdriver.get_with_error_handling(url, max_attempts=1, wait=wait, restart_browser=True)
                if errors:
                    # Even if success, it is possible to have errors on earlier attempts
                    [result['error'].append("Attempt %i: %s" % (attempts + i, error)) for i, error in enumerate(errors)]
                if not get_success:
                    # Try again
                    self.dataset.log("Error collecting screenshot for %s: %s" % (url, ', '.join(errors)))
                    continue

                start_time = time.time()
                if capture == "all":
                    # Scroll down to load all content until wait time exceeded
                    webdriver.scroll_down_page_to_load(max_time=wait)
                else:
                    # Wait for page to load with no scrolling
                    while time.time() < start_time + wait:
                        try:
                            load_complete = webdriver.driver.execute_script("return (document.readyState == 'complete');")
                        except UnexpectedAlertPresentException:
                            # attempt to dismiss random alert
                            webdriver.dismiss_alert()
                            load_complete = webdriver.driver.execute_script("return (document.readyState == 'complete');")
                        if load_complete:
                            break
                        time.sleep(0.1)
                self.dataset.log("Page load time: %s" % (time.time() - start_time))

                if pause:
                    time.sleep(pause)

                try:
                    webdriver.save_screenshot(results_path.joinpath(filename), width=width, height=height,
                                         viewport_only=(capture == "viewport"))
                except Exception as e:
                    self.dataset.log("Error saving screenshot for %s: %s" % (url, str(e)))
                    result['error'].append("Attempt %i: %s" % (attempts, str(e)))
                    continue

                result['filename'] = filename

                # Update file attribute with url if supported
                if hasattr(os, "setxattr"):
                    os.setxattr(results_path.joinpath(filename), 'user.url', url.encode())

                screenshots += 1
                success = True
                break

            result['timestamp'] = int(datetime.datetime.now().timestamp())
            result['error'] = ', '.join(result['error'])
            if success:
                self.dataset.log('Collected: %s' % url)
                # Update result and yield it
                result['final_url'] = webdriver.driver.current_url
                result['subject'] = webdriver.driver.title

            # Record result data
            metadata[url] = result
            done += 1

            if done % 50:
                self.dataset.update_status(
                    "processed %i/%i urls with %i screenshots taken" % (done, total_urls, screenshots))
            self.dataset.update_progress(done / total_urls)

        with results_path.joinpath(".metadata.json").open("w", encoding="utf-8") as outfile:
            json.dump(metadata, outfile)

        self.dataset.log('Screenshots taken: %i' % screenshots)
        if screenshots != done:
            self.dataset.log("%i URLs could not be screenshotted" % (done - screenshots)) # this can also happens if two provided urls are the same
        # finish up
        self.dataset.update_status("Compressing images")
        self.write_archive_and_finish(results_path)

        # Quit Selenium
        webdriver.quit_selenium()
