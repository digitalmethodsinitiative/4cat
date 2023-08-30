"""
Screenshot URLs w/ Selenium
"""
from backend.lib.processor import BasicProcessor
from common.lib.helpers import UserInput, extract_urls_from_string
from common.lib.exceptions import ProcessorInterruptedException, ProcessorException
from backend.lib.selenium_scraper import SeleniumWrapper

import os
import json
from hashlib import sha256

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class ScreenshotURLs(BasicProcessor):
    """
    Screenshot URLs w/ Selenium
    """
    type = "screenshot-urls"  # job type ID
    category = "Visual"  # category
    title = "Collect Screenshots of URLs"  # title displayed in UI
    description = "Use a Selenium based crawler to request each url and take a screenshot image of the webpage"
    extension = "zip"  # extension of result file, used internally and in UI

    options = {
        "columns": {
            "type": UserInput.OPTION_TEXT,
            "help": "Column(s) to extract URLs",
            "default": "body",
            "tooltip": "URLs will be extracted from each enabled column."
            },
        "wait-time": {
            "type": UserInput.OPTION_TEXT,
            "help": "Time in seconds to wait for page to load",
            "default": 2,
            "min": 0,
            "max": 5,
            },
        "split-comma": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Split column values by comma?",
            "default": False,
            "tooltip": "If enabled, columns can contain multiple URLs separated by commas, which will be considered "
            "separately"
            },
        "ignore-cookies": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Attempt to ignore cookie requests",
            "default": False,
            "tooltip": "If enabled, a firefox extension [i don't care about cookies](https://addons.mozilla.org/nl/firefox/addon/i-dont-care-about-cookies/) will be used"
            },
        }

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        """
        Update columns field with actual columns
        """
        options = cls.options

        if parent_dataset and parent_dataset.get_columns():
            columns = parent_dataset.get_columns()
            options["columns"]["type"] = UserInput.OPTION_MULTI
            options["columns"]["inline"] = True
            options["columns"]["options"] = {v: v for v in columns}
            options["columns"]["default"] = ['body']
            for default in ['url', 'urls', 'links']:
                if default in columns:
                    options["columns"]["default"] = [default]
                    break


        # extensions = config.get('selenium.firefox_extensions')
        # if 'i_dont_care_about_cookies' in extensions and extensions['extensions'].get('path'):
        #     options['ignore-cookies'] = {
        #         "type": UserInput.OPTION_TOGGLE,
        #         "help": "Attempt to ignore cookie requests",
        #         "default": False,
        #         "tooltip": "If enabled, a firefox extension [i don't care about cookies](https://addons.mozilla.org/nl/firefox/addon/i-dont-care-about-cookies/) will be used"
        #     }

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

        ignore_cookies = self.parameters.get("ignore-cookies")
        wait = self.parameters.get("wait-time")
        split_comma = self.parameters.get("split-comma")
        columns = self.parameters.get("columns")
        if not columns:
            self.dataset.update_status("No columns selected; no screenshots taken.", is_final=True)
            self.dataset.finish(0)
            return

        results_path = self.dataset.get_staging_area()
        self.dataset.log('Staging directory location: %s' % results_path)

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
                    urls[post_url] = {'ids': {post.get('id', 0)}}
                else:
                    urls[post_url]['ids'].add(post.get('id', 0))

        if not urls:
            self.dataset.update_status("No urls identified.", is_final=True)
            self.dataset.finish(0)
            return
        else:
            self.dataset.log('Collected %i urls.' % len(urls))

        self.dataset.update_status("Starting Selenium Webdriver.")
        webdriver = SeleniumWrapper()
        try:
            webdriver.start_selenium()
            if ignore_cookies:
                webdriver.enable_firefox_extension('/usr/src/app/jid1-KKzOGWgsW3Ao4Q@jetpack.xpi')
        except ProcessorException as e:
            self.dataset.log("Error starting Selenium: %s" % str(e))
            self.dataset.update_status("Error starting Selenium; contact admin.", is_final=True)
            self.dataset.finish(0)
            webdriver.quit_selenium()
            return

        screenshots = 0
        processed_urls = 0
        total_urls = len(urls)
        for url in urls:
            # Stop processing if worker has been asked to stop
            if self.interrupted:
                webdriver.quit_selenium()
                raise ProcessorInterruptedException("Interrupted while downloading images.")

            processed_urls += 1
            if processed_urls % 50:
                self.dataset.update_status("processed %i/%i urls with %i screenshots taken" % (processed_urls, total_urls, screenshots))
                self.dataset.update_progress(processed_urls / total_urls)

            webdriver.reset_current_page()
            try:
                webdriver.driver.get(url)
            except Exception as e:
                # TODO: This is way too broad and should be handled in the SeleniumWrapper
                self.dataset.log("Error collectiong %s: %s" % (url, str(e)))
                urls[url]['error'] = str(e)
                continue

            if webdriver.check_for_movement():
                hash = sha256(url.encode()).hexdigest()[:13]
                filename = f'{hash}.png'
                try:
                    webdriver.save_screenshot(results_path.joinpath(filename))
                except Exception as e:
                    self.dataset.log("Error saving screenshot for %s: %s" % (url, str(e)))
                    urls[url]['error'] = str(e)
                    continue
                urls[url]['filename'] = filename
                # Update file attribute with url
                os.setxattr(results_path.joinpath(filename), 'user.url', url.encode())
                screenshots += 1
            else:
                # No page was reached...
                urls[url]['error'] = "Driver was not able to go to page"

        with results_path.joinpath(".metadata.json").open("w", encoding="utf-8") as outfile:
            # Reformat sets
            for url, data in urls.items():
                data['ids'] = list(data['ids'])
            json.dump(urls, outfile)

        self.dataset.log('Screenshots taken: %i' % screenshots)
        # finish up
        self.dataset.update_status("Compressing images")
        self.write_archive_and_finish(results_path)
