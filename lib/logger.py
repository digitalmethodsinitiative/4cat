import logging

from logging.handlers import RotatingFileHandler
from config import config


class Logger:
    logger = None

    def __init__(self):
        self.logger = logging.getLogger("4cat-scraper")

        handler = RotatingFileHandler(config.log_path, maxBytes=5242880, backupCount=1)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(asctime)-15s | %(message)s", "%d-%m-%Y %H:%M:%S"))

        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)

    def log(self, message, level=logging.INFO):
        print("LOG: %s" % message)
        self.logger.log(level, message)

    def debug(self, message):
        self.log(message, logging.DEBUG)

    def info(self, message):
        self.log(message, logging.INFO)

    def warning(self, message):
        self.log(message, logging.WARN)

    def error(self, message):
        self.log(message, logging.ERROR)

    def critical(self, message):
        self.log(message, logging.CRITICAL)
