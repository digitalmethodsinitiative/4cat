import subprocess
import time
import shutil
import abc
import os
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from bs4.element import Comment

from backend.lib.search import Search
from common.lib.logger import Logger
from common.lib.exceptions import ProcessorException
from common.config_manager import config
from common.lib.user_input import UserInput

if config.get('selenium.browser') and config.get('selenium.selenium_executable_path'):
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.common.exceptions import WebDriverException, SessionNotCreatedException, UnexpectedAlertPresentException, \
    TimeoutException, JavascriptException, NoAlertPresentException, ElementClickInterceptedException
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.common.desired_capabilities import DesiredCapabilities

    if config.get('selenium.browser') == 'chrome':
        from selenium.webdriver.chrome.options import Options
    elif config.get('selenium.browser') == 'firefox':
        from selenium.webdriver.firefox.options import Options
    else:
        raise ImportError('selenium.browser only works with "chrome" or "firefox"')
else:
    raise ImportError('Selenium not set up')


class SeleniumWrapper(metaclass=abc.ABCMeta):
    """
    Selenium Scraper class

    Selenium utilizes a chrome webdriver and chrome browser to navigate and scrape the web. This processor can be used
    to initialize that browser and navigate it as needed. It replaces search to allow you to utilize the Selenium driver
    and ensure the webdriver and browser are properly closed out upon completion.
    """

    driver = None
    last_scraped_url = None
    browser = None

    consecutive_errors = 0
    num_consecutive_errors_before_restart = 3

    selenium_log = Logger(logger_name='selenium', filename='selenium.log', log_level='DEBUG')

    def get_with_error_handling(self, url, max_attempts=1, wait=0, restart_browser=False):
        """
        Attempts to call driver.get(url) with error handling. Will attempt to restart Selenium if it fails and can
        attempt to kill Firefox (and allow Selenium to restart) itself if allowed.

        Returns a tuple containing a bool (True if successful, False if not) and a list of the errors raised.
        """
        # Start clean
        self.reset_current_page()

        success = False
        attempts = 0
        errors = []
        while attempts < max_attempts:
            attempts += 1
            try:
                self.driver.get(url)
                success = True
                self.consecutive_errors = 0
            except TimeoutException as e:
                errors.append(f"Timeout retrieving {url}")
                self.selenium_log.debug(f"Selenium Timeout({url}): {e}")
            except Exception as e:
                self.selenium_log.error(f"Error driver.get({url}): {e}")
                errors.append(e)
                self.consecutive_errors += 1
                
                # Check consecutive errors
                if self.consecutive_errors > self.num_consecutive_errors_before_restart:
                    # First kill browser
                    if restart_browser:
                        self.kill_browser(self.browser)
                    
                    # Then restart Selenium
                    self.restart_selenium()

            if success:
                # Check for movement
                if self.check_for_movement():
                    # True success
                    break
                else:
                    success = False
                    errors.append(f"Failed to navigate to new page (current URL: {self.last_scraped_url}); check url is not the same as previous url")

            if attempts < max_attempts:
                time.sleep(wait)

        return success, errors

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
        self.driver.get(url)

        if self.check_for_movement():

            results = self.collect_results(url, extract_links, title_404_strings)
            return results

        else:
            raise Exception("Failed to navigate to new page; check url is not the same as previous url")

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
                try:
                    links = self.collect_links()
                except Exception as e:
                    if hasattr(self, 'dataset'):
                        self.dataset.log('Error collecting links for url %s: %s' % (url, str(e)))
                    links = None
                    result['collect_links_error'] = e
            result['links'] = links

        return result

    def collect_links(self):
        """

        """
        if self.driver is None:
            raise ProcessorException('Selenium Drive not yet started: Cannot collect links')

        elems = self.driver.find_elements(By.XPATH, "//a[@href]")
        return [elem.get_attribute("href") for elem in elems]

    @staticmethod
    def check_exclude_link(link, previously_used_links, base_url=None, bad_url_list=None):
        """
        Check if a link should not be used. Returns True if link not in previously_used_links
        and not in bad_url_list. If a base_url is included, the link string MUST include the
        base_url as a substring (this can be used to ensure a url contains a particular domain).

        If bad_url_lists is None, the default list (['mailto:', 'javascript']) is used.

        :param str link:                    link to check
        :param set previously_used_links:   set of links to exclude
        :param str base_url:                substring to ensure is part of link
        :param list bad_url_list:           list of substrings to exclude
        :return bool:                       True if link should NOT be excluded else False
        """
        if bad_url_list is None:
            bad_url_list = ['mailto:', 'javascript']

        if link and link not in previously_used_links and \
            not any([bad_url in link[:len(bad_url)] for bad_url in bad_url_list]):
                if base_url is None:
                    return True
                elif base_url in link:
                    return True
                else:
                    return False
        else:
            return False

    def start_selenium(self, eager=False):
        """
        Start a headless browser

        :param bool eager:  Eager loading?
        """
        self.browser = config.get('selenium.browser')
        # TODO review and compare Chrome vs Firefox options
        options = Options()
        options.headless = True
        options.add_argument('--headless')
        # options.add_argument("--remote-debugging-port=9222")
        options.add_argument('--no-sandbox')
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-browser-side-navigation")

        if eager:
            options.set_capability("pageLoadStrategy", "eager")

        try:
            if self.browser == 'chrome':
                self.driver = webdriver.Chrome(executable_path=config.get('selenium.selenium_executable_path'), options=options)
            elif self.browser == 'firefox':
                self.driver = webdriver.Firefox(executable_path=config.get('selenium.selenium_executable_path'), options=options)
            else:
                if hasattr(self, 'dataset'):
                    self.dataset.update_status("Selenium Scraper not configured")
                raise ProcessorException("Selenium Scraper not configured; browser must be 'firefox' or 'chrome'")
        except (SessionNotCreatedException, WebDriverException) as e:
            if hasattr(self, 'dataset'):
                self.dataset.update_status("Selenium Scraper not configured; contact admin.", is_final=True)
                self.dataset.finish(0)
            if "only supports Chrome" in str(e):
                raise ProcessorException("Your chromedriver version is incompatible with your Chromium version:\n  (%s)" % e)
            elif "Message: '' executable may have wrong" in str(e):
                raise ProcessorException('Webdriver not installed or path to executable incorrect (%s)' % str(e))
            else:
                raise ProcessorException("Could not connect to browser (%s)." % str(e))
        self.selenium_log.info(f"Selenium started with browser PID: {self.driver.service.process.pid}")

    def quit_selenium(self):
        """
        Always attempt to close the browser otherwise multiple versions of Chrome will be left running.

        And Chrome is a memory hungry monster.
        """
        try:
            self.driver.quit()
        except Exception as e:
            self.selenium_log.error(e)

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
        try:
            current_url = self.driver.current_url
        except UnexpectedAlertPresentException:
            # attempt to dismiss random alert
            self.dismiss_alert()
            current_url = self.driver.current_url
        if current_url == self.last_scraped_url:
            return False
        else:
            return True

    def dismiss_alert(self):
        """
        Dismiss any alert that may be present
        """
        current_window_handle = self.driver.current_window_handle
        try:
            alert = self.driver.switch_to.alert
            if alert:
                alert.dismiss()
        except NoAlertPresentException:
            return
        self.driver.switch_to.window(current_window_handle)

    def check_page_is_loaded(self, max_time=60, auto_dismiss_alert=True):
        """
        Check if page is loaded. Returns True if loaded, False if not.
        """
        try:
            try:
                WebDriverWait(self.driver, max_time).until(
                    lambda driver: driver.execute_script('return document.readyState') == 'complete')
            except UnexpectedAlertPresentException as e:
                # attempt to dismiss random alert
                if auto_dismiss_alert:
                    self.dismiss_alert()
                    WebDriverWait(self.driver, max_time).until(
                        lambda driver: driver.execute_script('return document.readyState') == 'complete')
                else:
                    raise e
        except TimeoutException:
            return False

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

    def enable_firefox_extension(self, path_to_extension, temporary=True):
        """
        Enables Firefox extension.
        """
        if self.browser != 'firefox':
            raise Exception('Cannot add firefox extension to non firefox browser!')
        if self.driver is None:
            raise Exception('Must start firefox before installing extension!')
        self.driver.install_addon(os.path.abspath(path_to_extension), temporary=temporary)

    def save_screenshot(self, path, wait=2, width=None, height=None, viewport_only=False):
        # Save current screen size
        original_size = self.driver.get_window_size()
        dom_width = self.driver.execute_script('return document.body.parentNode.scrollWidth')
        dom_height = self.driver.execute_script('return document.body.parentNode.scrollHeight')

        # Wait 30 up to 30 seconds for 'body' to load
        WebDriverWait(self.driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, 'body')))

        # Gather and adjust screen size
        if not width:
            width = dom_width

        if not height:
            height = dom_height

        self.driver.set_window_size(width, height)

        # Wait for page to load
        time.sleep(wait)

        # Take screenshot
        if viewport_only:
            self.driver.execute_script("return document.body.style.overflow = 'hidden';")
            self.driver.save_screenshot(str(path))  # has scrollbar
        else:
            self.driver.find_element(By.TAG_NAME, "body").screenshot(str(path))  # avoids scrollbar

        # Return to previous size (might not be necessary)
        self.driver.set_window_size(original_size['width'], original_size['height'])

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
            links_to_return.append({'link_text': link_text,
                                    'url': link_url.rstrip('/'),
                                    'original_url': original_url})
        return url_count, links_to_return

    @staticmethod
    def get_beautiful_iframe_links(page_source, beautiful_soup_parser='html.parser'):
        """
        takes page_source and creates BeautifulSoup entity, then looks for iframes
        and gets their src link. This could perhaps be more robust. Selenium can
        also switch to iframes to extract html/text, but you have to know a bit
        more in order to select them (xpath, css, etc.).

        You could then either use requests of selenium to scrape these links.
        TODO: is it possible/desirable to insert the html source code back into
        the original url?
        """
        iframe_links = []
        soup = BeautifulSoup(page_source, beautiful_soup_parser)
        iframes = soup.findAll('iframe')
        if iframes:
            for iframe in iframes:
                iframe_links.append(iframe.get('src'))
        return iframe_links

    def scroll_down_page_to_load(self, max_time=None):
        """
        Scroll down page until it is fully loaded. Returns top of window at end.
        """
        start_time = time.time()
        last_bottom = self.driver.execute_script('return window.scrollY')
        action = None
        while True:
            if max_time is not None:
                if time.time() - start_time > max_time:
                    # Stop if max_time exceeded
                    return last_bottom

            # Scroll down
            try:
                self.driver.execute_script("window.scrollTo(0, window.scrollY + window.innerHeight);")
            except JavascriptException as e:
                # Apparently no window.scrollTo?
                if action is None:
                    action = ActionChains(self.driver)
                    action.send_keys(Keys.PAGE_DOWN)
                action.perform()

            # Wait for anything to load
            try:
                WebDriverWait(self.driver, max_time).until(lambda driver: driver.execute_script('return document.readyState') == 'complete')
            except TimeoutException:
                # Stop if timeout
                return last_bottom

            current_bottom = self.driver.execute_script('return window.scrollY')
            if last_bottom == current_bottom:
                # We've reached the bottom of the page
                return current_bottom

            last_bottom = current_bottom
            time.sleep(.2)

    def kill_browser(self, browser):
        self.selenium_log.info(f"4CAT is killing {browser} with PID: {self.driver.service.process.pid}")
        try:
            subprocess.check_call(['kill', str(self.driver.service.process.pid)])
        except subprocess.CalledProcessError as e:
            self.selenium_log.error(f"Error killing {browser}: {e}")
            self.quit_selenium()
            raise e

    def destroy_to_click(self, button, max_time=5):
        """
        A most destructive way to click a button. If something is obscuring the button, it will be removed. Repeats
        destruction until the button is clicked or max_time is exceeded.

        Probably a good idea to reload after use if additional elements are needed

        :param button:  The button to click
        :param max_time:  Maximum time to attempt to click button
        """
        start_time = time.time()
        while True:
            try:
                button.click()
                self.selenium_log.debug("button clicked!")
                break
            except ElementClickInterceptedException as e:
                if time.time() - start_time > max_time:
                    break
                error = e
                self.selenium_log.debug(f"destroy_to_click: {error.msg}")

                error_element_type = error.msg.split("element <")[1].split(" ")[0].rstrip(">")
                if len(error.msg.split("element <")[1].split("class=\"")) > 1:
                    error_element_class = error.msg.split("element <")[1].split("class=\"")[1].split(" ")[0]
                else:
                    error_element_class = ""
                self.selenium_log.info(f"destroy_to_click removing element: ({error_element_type}, {error_element_class}")

                self.driver.execute_script(
                    f"document.querySelector('{error_element_type}{'.' + error_element_class if error_element_class else ''}').remove();")

    @classmethod
    def is_selenium_available(cls):
        """
        Check if Selenium is available
        """
        if config.get("selenium.installed"):
             return shutil.which(config.get("selenium.selenium_executable_path"))
        else:
            return False


class SeleniumSearch(SeleniumWrapper, Search, metaclass=abc.ABCMeta):
    """
    Selenium Scraper class

    Selenium utilizes a chrome webdriver and chrome browser to navigate and scrape the web. This processor can be used
    to initialize that browser and navigate it as needed. It replaces search to allow you to utilize the Selenium driver
    and ensure the webdriver and browser are properly closed out upon completion.
    """
    max_workers = 3
    config = {
        "selenium.browser": {
            "type": UserInput.OPTION_TEXT,
            "default": "",
            "help": "Browser type ('firefox' or 'chrome')",
            "tooltip": "This must corespond to the installed webdriver; Docker installs firefox when backend container restarts if this is set to 'firefox'",
        },
        "selenium.max_sites": {
            "type": UserInput.OPTION_TEXT,
            "default": 120,
            "help": "Posts per page",
            "coerce_type": int,
            "tooltip": "Posts to display per page"
        },
        "selenium.selenium_executable_path": {
            "type": UserInput.OPTION_TEXT,
            "default": "",
            "help": "Path to webdriver (geckodriver or chromedriver)",
            "tooltip": "Docker installs to /usr/local/bin/geckodriver",
        },
        "selenium.firefox_extensions": {
            "type": UserInput.OPTION_TEXT_JSON,
            "default": {
                "i_dont_care_about_cookies": {"path": "", "always_enabled": False},
                },
            "help": "Firefox Extensions",
            "tooltip": "Can be used by certain processors and datasources",
        },
        "selenium.display_advanced_options": {
            "type": UserInput.OPTION_TOGGLE,
            "default": True,
            "help": "Show advanced options",
            "tooltip": "Show advanced options for Selenium processors",
        },
        "selenium.installed": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Has Selenium been installed",
            "tooltip": "Toggling off will disable Selenium processors",
        },
    }

    def search(self, query):
        """
        Search for items matching the given query

        The real work is done by the get_items() method of the descending
        class. This method just provides some scaffolding and post-processing
        of results via `after_search()`, if it is defined.

        :param dict query:  Query parameters
        :return:  Iterable of matching items, or None if there are no results.
        """
        try:
            self.start_selenium(eager=(hasattr(self, "eager_selenium") and self.eager_selenium))
        except ProcessorException as e:
            self.quit_selenium()
            raise e
        # Returns to default position; i.e., 'data:,'
        self.reset_current_page()
        # Sets timeout to 60; can be updated later if desired
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


    def clean_up(self):
        """
        Ensures Selenium webdriver and Chrome browser and closed whether processor completes successfully or not.
        """
        super().clean_up()

        self.quit_selenium()
