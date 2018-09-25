import time

from lib.keyboard import KeyPoller
from lib.logger import Logger
from config import config

from scrapers.scrapeThreads import ThreadScraper
from scrapers.scrapeBoards import BoardScraper


class ScraperManager:
    """
    Scraper Manager

    Simple class that contains the main loop as well as a threaded keyboard poller
    that listens for a keypress (which can be used to end the main loop)
    """
    looping = True
    key_poller = None
    scraper_threads = []

    def __init__(self):
        """
        Set up key poller
        """
        print("Welcome!")
        self.key_poller = KeyPoller(self)
        self.log = Logger()
        self.loop()

    def abort(self):
        """
        End main loop
        """
        self.looping = False

    def loop(self):
        """
        Loop the scraper manager

        Every few seconds, this checks if any scrapers have finished, and if so, whether
        any new ones should be started.

        If aborted, all scrapers are politely asked to abort too.
        """
        # manage scrapers
        while self.looping:
            board_scrapers = len([scraper for scraper in self.scraper_threads if scraper.type == "board"])
            for i in range(board_scrapers, config.max_board_scrapers):
                self.log.info("Starting new board scraper")
                board_scraper = BoardScraper()
                self.scraper_threads.append(board_scraper)

            thread_scrapers = len([scraper for scraper in self.scraper_threads if scraper.type == "thread"])
            for i in range(thread_scrapers, config.max_thread_scrapers):
                self.log.info("Starting new thread scraper")
                thread_scraper = ThreadScraper()
                self.scraper_threads.append(thread_scraper)

            # remove references to finished scrapers
            for scraper in self.scraper_threads:
                if not scraper.isAlive():
                    self.scraper_threads.remove(scraper)

            self.log.info("Running scrapers: %i" % len(self.scraper_threads))

            # check in five seconds if any scrapers died and need to be restarted (probably not!)
            time.sleep(5)

        # let all scrapers end
        print("Waiting for all scrapers to finish...")
        for scraper in self.scraper_threads:
            scraper.abort()

        print("Done!")
