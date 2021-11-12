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


    @abc.abstractmethod
    def scrape_pages(self, query):
        """
        Method to scrape urls with for a given query

        To be implemented by descending classes!

        :param dict query:  Query parameters
        :return Generator:  A generator or iterable that returns items
          collected according to the provided parameters.
        """
        pass

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

        posts = self.get_items(query)

        self.quit_selenium()

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
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')

        try:
            self.driver = webdriver.Chrome(options=options)
        except (SessionNotCreatedException, WebDriverException) as e:
            if "binary not found" in str(e):
                raise ProcessorException("Chromium binary is not available.")
            if "only supports Chrome" in str(e):
                raise ProcessorException("Your chromedriver version is incompatible with your Chromium version:\n  (%s)" % e)
            else:
                raise ProcessorException("Could not connect to Chromium (%s)." % e)

        # self.last_scraped_url = self.driver.current_url

    def quit_selenium(self):
        """
        Always attempt to close the browser
        """
        try:
            self.driver.quit()
        except:
            pass

    def check_for_movement(self):
        """
        Some driver.get() commands will not result in an error even if the do not result in updating the page source.
        This can happen, for example, if a url directs the browser to attempt to download a file. It can therefore be
        important to check and ensure a new page was actually obtained before retrieving the page source as you will
        otherwise retrieve he same information from the previous url.

        WARNING: It may also be true that a url redirects to the same url as previous. This check would assume no
        movement occurred. In the event of scraping, that information would already be obtained, but you would not know
        the new url redirects to the same information.
        """
        current_url = self.driver.current_url
        if current_url == self.last_scraped_url:
            return False
        else:
            return True

    def check_for_404(self, stop_if_in_title='default'):
        """
        Checks page title for references to 404

        Selenium does not have a "status code" in the same way the python requests and other libraries do. This can be
        used to approximate a 404. Alternately, you could use another library to check for 404 errors.
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