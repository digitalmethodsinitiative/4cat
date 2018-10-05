"""
Log handler
"""
import logging

from logging.handlers import RotatingFileHandler
import config


class Logger:
    """
    Logger

    Sets up a rotating logger that writes to a log file
    """
    logger = logging.getLogger("4cat-backend")

    def __init__(self):
        """
        Set up log handler
        """
        handler = RotatingFileHandler(config.PATH_LOGS, maxBytes=5242880, backupCount=0)
        handler.setLevel(logging.WARNING)
        handler.setFormatter(logging.Formatter("%(asctime)-15s | %(message)s", "%d-%m-%Y %H:%M:%S"))

        self.logger.addHandler(handler)
        self.logger.setLevel(logging.WARNING)

    def log(self, message, level=logging.INFO):
        """
        Log message

        :param message:  Message to log
        :param level:  Severity level, should be a logger.* constant
        """
        if level > logging.DEBUG:
            print("LOG: %s" % message)
        self.logger.log(level, message)

    def debug(self, message):
        """
        Log DEBUG level message

        :param message: Message to log
        """
        self.log(message, logging.DEBUG)

    def info(self, message):
        """
        Log INFO level message

        :param message: Message to log
        """
        self.log(message, logging.INFO)

    def warning(self, message):
        """
        Log WARNING level message

        :param message: Message to log
        """
        self.log(message, logging.WARN)

    def error(self, message):
        """
        Log ERROR level message

        :param message: Message to log
        """
        self.log(message, logging.ERROR)

    def critical(self, message):
        """
        Log CRITICAL level message

        :param message: Message to log
        """
        self.log(message, logging.CRITICAL)
