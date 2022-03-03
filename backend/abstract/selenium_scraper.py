import abc
from selenium import webdriver
from selenium.common.exceptions import WebDriverException, SessionNotCreatedException
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from bs4.element import Comment

from backend.abstract.search import Search
from common.lib.exceptions import ProcessorException
import config

if hasattr(config, 'SELENIUM_BROWSER') and hasattr(config, 'SELENIUM_EXECUTABLE_PATH'):
    if config.SELENIUM_BROWSER == 'chrome':
        from selenium.webdriver.chrome.options import Options
    elif config.SELENIUM_BROWSER == 'firefox':
        from selenium.webdriver.firefox.options import Options
    else:
        # TODO raise some sort of error; stop class from being used
        pass


class SeleniumScraper(Search, metaclass=abc.ABCMeta):
    """
    Selenium Scraper class

    Selenium utilizes a chrome webdriver and chrome browser to navigate and scrape the web. This processor can be used
    to initialize that browser and navigate it as needed. It replaces search to allow you to utilize the Selenium driver
    and ensure the webdriver and browser are properly closed out upon completion.
    """

    driver = None
    last_scraped_url = None

    def simple_scrape_page(self, url, extract_links=False, title_404_strings='default'):
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

        try:
            self.driver.get(url)
        except Exception as e:
            self.log.warning("Selenium driver.get() exception: " + str(e))
            self.restart_selenium()
            try:
                # try again
                self.driver.get(url)
            except Exception as e:
                self.log.error(str(e))
                return False

        if self.check_for_movement():

            results = self.collect_results(url, extract_links, title_404_strings)
            return results

        else:
            return False

    def collect_results(self, url, extract_links=False, title_404_strings='default'):

        result = {
            'original_url': url,
            'detected_404': self.check_for_404(title_404_strings),
            'page_title': self.driver.title,
            'final_url': self.driver.current_url,
            'page_source': self.driver.page_source,
            }

        if extract_links:
            try:
                links = self.collect_links()
            except Exception as e:
                print(e)
                print('trying to get links again')
                try:
                    links = self.collect_links()
                except Exception as e:
                    print(e)
                    links = []
            result['links'] = links

        return result

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
        # TODO review and compare Chrome vs Firefox options
        options = Options()
        options.headless = True
        options.add_argument('--headless')
        options.add_argument("--remote-debugging-port=9222")
        options.add_argument('--no-sandbox')
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-browser-side-navigation")

        try:
            if hasattr(config, 'SELENIUM_BROWSER') and hasattr(config, 'SELENIUM_EXECUTABLE_PATH'):
                if config.SELENIUM_BROWSER == 'chrome':
                    self.driver = webdriver.Chrome(executable_path=config.SELENIUM_EXECUTABLE_PATH, options=options)
                elif config.SELENIUM_BROWSER == 'firefox':
                    self.driver = webdriver.Firefox(executable_path=config.SELENIUM_EXECUTABLE_PATH, options=options)
                else:
                    raise ProcessorException('Selenium Scraper not configured')

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

    def restart_selenium(self):
        """
        Weird Selenium error? Restart and try again.
        """
        self.quit_selenium()
        self.start_selenium()
        self.reset_current_page()

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
            stop_if_in_title = ["page not found", "directory not found", "file not found", "404 not found", "error 404", "error page"]

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

    # Some BeautifulSoup helper functions
    @staticmethod
    def scrape_beautiful_text(page_source, beautiful_soup_parser='html.parser'):
        """takes page source and uses BeautifulSoup to extract a list of all visible text items on page"""

        # Couple of helper functions
        def tag_visible(element):
            """checks BeautifulSoup element to see if it is visible on webpage"""

            """original list of elements:
            ['style', 'script', 'head', 'title', 'meta', '[document]']
            """
            if element.parent.name in ['i:pgf', 'svg', 'img', 'script', 'style', 'script', 'head', 'title', 'meta', '[document]']:
                return False
            if isinstance(element, Comment):
                return False
            return True

        def text_from_html(soup):
            """take BeautifulSoup entity, finds all text blocks, and checks if block is visible on page"""
            texts = soup.findAll(text=True)
            visible_texts = filter(tag_visible, texts)
            return visible_texts

        def anyalpha(string):
            """Check for any alpha"""
            return any([c.isalpha() for c in string])

        # Create soup
        soup = BeautifulSoup(page_source, beautiful_soup_parser)

        # I may be able to simplify this... just if t?
        text = [t.strip() for t in text_from_html(soup) if t.strip()]
        # Only return is there is at least some alphabetic info
        text = [t for t in text if anyalpha(t)]
        # Add the page title as the first entry to the text
        if soup.title:
            title = soup.title.text.strip()
            return [title] + text
        else:
            return text

    @staticmethod
    def get_beautiful_links(page_source, domain, beautiful_soup_parser='html.parser'):
        """
        takes page_source and creates BeautifulSoup entity and url that was scraped, finds all links,
        and returns the number of links and a list of all links in tuple of shown text, fixed link,
        and original link.

        Uses domain to attempt to fix links that are partial.
        """
        soup = BeautifulSoup(page_source, beautiful_soup_parser)
        url_count = 0
        all_links= soup.findAll('a')
        links_to_return = []
        for link in all_links:
            link_url = link.get('href')
            original_url = link_url
            link_text = None
            if link_url is not None:
                url_count += 1
                link_text = link.text
                # If image in link, find alt text and add to link_text
                for img in link.findAll('img'):
                    alt_text = img.get('alt')
                    if alt_text and type(alt_text) == str:
                        link_text = ' '.join([link_text, alt_text])
                # Fix URL if needed
                if link_url.strip()[:4] == "http":
                    pass
                else:
                    link_url = urljoin(domain, link_url)
            else:
                continue
            links_to_return.append((link_text, link_url.rstrip('/'), original_url))
        return url_count, links_to_return
