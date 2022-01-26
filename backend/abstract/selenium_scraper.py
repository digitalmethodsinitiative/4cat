import abc
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException, SessionNotCreatedException

from backend.abstract.search import Search
from common.lib.exceptions import ProcessorException


class SeleniumScraper(Search, metaclass=abc.ABCMeta):
    """
    Selenium Scraper class

    Selenium utilizes a chrome webdriver and chrome browser to navigate and scrape the web. This processor can be used
    to initialize that browser and navigate it as needed. It replaces search to allow you to utilize the Selenium driver
    and ensure the webdriver and browser are properly closed out upon completion.
    """

    driver = None
    last_scraped_url = None

    def simple_scrape_page(self, url, title_404_strings='default'):
        """
        Simple helper to scrape url. Returns a dictionary containing basic results from scrape including final_url,
        page_title, and page_source otherwise False if the page did not advance (self.check_for_movement() failed).
        Does not handle errors from driver.get() (e.g., badly formed URLs, Timeouts, etc.).

        Note: calls self.reset_current_page() prior to requesting url to ensure each page is uniquely checked.

        You are invited to use this as a template for more complex scraping.

        :param str url:  url as string; beginning with scheme (e.g., http, https)
        :param List title_404_strings:  List of strings representing possible 404 text to be compared with driver.title
        :return dict: A dictionary containing basic results from scrape including final_url, page_title, and page_source.
                      Returns false if no movement was detected
        """
        self.reset_current_page()
        # try:
        self.driver.get(url)
        # except WebDriverException as e:
        #     # restart selenium

        if self.check_for_movement():
            detected_404 = self.check_for_404(title_404_strings)
            page_title = self.driver.title
            current_url = self.driver.current_url
            page_source = self.driver.page_source

            return {
                    'original_url': url,
                    'final_url': current_url,
                    'page_title': page_title,
                    'page_source': page_source,
                    'detected_404': detected_404
                    }
        else:
            return False

    def collect_links(self):
        """

        """
        if self.driver is None:
            raise ProcessorException('Selenium Drive not yet started: Cannot collect links')

        elems = self.driver.find_elements_by_xpath("//a[@href]")
        return [elem.get_attribute("href") for elem in elems]

    def search(self, query):
        """
        Search for items matching the given query

        The real work is done by the get_items() method of the descending
        class. This method just provides some scaffolding and post-processing
        of results via `after_search()`, if it is defined.

        :param dict query:  Query parameters
        :return:  Iterable of matching items, or None if there are no results.
        """
        self.start_selenium()
        # Returns to default position; i.e., 'data:,'
        self.reset_current_page()
        # Sets timeout to 60
        self.set_page_load_timeout()

        # Normal Search function to be used To be implemented by descending classes!
        try:
            posts = self.get_items(query)
        except Exception as e:
            # Ensure Selenium always quits
            self.quit_selenium()
            raise e

        if not posts:
            return None

        # search workers may define an 'after_search' hook that is called after
        # the query is first completed
        if hasattr(self, "after_search") and callable(self.after_search):
            posts = self.after_search(posts)

        return posts

    def start_selenium(self):
        """
        Start a headless browser
        """
        options = Options()
        options.headless = True
        options.add_argument('--headless')
        options.add_argument("--remote-debugging-port=9222")
        options.add_argument('--no-sandbox')
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-browser-side-navigation")

        try:
            self.driver = webdriver.Chrome(options=options)
        except (SessionNotCreatedException, WebDriverException) as e:
            if "binary not found" in str(e):
                raise ProcessorException("Chromium binary is not available.")
            if "only supports Chrome" in str(e):
                raise ProcessorException("Your chromedriver version is incompatible with your Chromium version:\n  (%s)" % e)
            else:
                raise ProcessorException("Could not connect to Chromium (%s)." % e)

    def quit_selenium(self):
        """
        Always attempt to close the browser otherwise multiple versions of Chrome will be left running.

        And Chrome is a memory hungry monster.
        """
        try:
            self.driver.quit()
        except:
            pass

    def clean_up(self):
        """
        Ensures Selenium webdriver and Chrome browser and closed whether processor completes successfully or not.
        """
        super().clean_up()

        self.quit_selenium()

    def set_page_load_timeout(self, timeout=60):
        """
        Adjust the time that Selenium will wait for a page to load before failing
        """
        self.driver.set_page_load_timeout(timeout)

    def check_for_movement(self):
        """
        Some driver.get() commands will not result in an error even if they do not result in updating the page source.
        This can happen, for example, if a url directs the browser to attempt to download a file. It can therefore be
        important to check and ensure a new page was actually obtained before retrieving the page source as you will
        otherwise retrieve he same information from the previous url.

        WARNING: It may also be true that a url redirects to the same url as previous scraped url. This check would assume no
        movement occurred. Use in conjunction with self.reset_current_page() if it is necessary to check every url results
        and identify redirects.
        """
        current_url = self.driver.current_url
        if current_url == self.last_scraped_url:
            return False
        else:
            return True

    def reset_current_page(self):
        """
        It may be desirable to "reset" the current page, for example in conjunction with self.check_for_movement(),
        to ensure the results are obtained for a specific url provided.

        Example: driver.get(url_1) is called and page_source is collected. Then driver.get(url_2) is called, but fails.
        Depending on the type of failure (which may not be detected), calling page_source may return the page_source
        from url_1 even after driver.get(url_2) is called.
        """
        self.driver.get('data:,')
        self.last_scraped_url = self.driver.current_url

    def check_for_404(self, stop_if_in_title='default'):
        """
        Checks page title for references to 404

        Selenium does not have a "status code" in the same way the python requests and other libraries do. This can be
        used to approximate a 404. Alternately, you could use another library to check for 404 errors but that can lead
        to misleading results (as the new library will necessarily constitute a separate request).
        More information here:
        https://www.selenium.dev/documentation/worst_practices/http_response_codes/

        Default values: ["page not found", "directory not found", "file not found", "404 not found", "error 404"]

        :param list stop_if_in_title:  List of strings representing possible 404 text
        """
        if stop_if_in_title == 'default':
            stop_if_in_title = ["page not found", "directory not found", "file not found", "404 not found", "error 404"]

        if any(four_oh_four.lower() in self.driver.title.lower() for four_oh_four in stop_if_in_title):
            return True
        else:
            return False

    def enable_download_in_headless_chrome(self, download_dir):
        """
        It is possible to allow the webbrowser to download files.
        NOTE: this could introduce security risks.
        """
        # add missing support for chrome "send_command"  to selenium webdriver
        self.driver.command_executor._commands["send_command"] = ("POST", '/session/$sessionId/chromium/send_command')

        params = {'cmd': 'Page.setDownloadBehavior', 'params': {'behavior': 'allow', 'downloadPath': download_dir}}
        return self.driver.execute("send_command", params)
