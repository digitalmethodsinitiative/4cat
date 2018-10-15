"""
Log handler
"""
import logging
import sys
import os

from lib.helpers import get_absolute_folder
from logging.handlers import RotatingFileHandler, SMTPHandler

sys.path.insert(0, os.path.dirname(__file__) + '/../..')
import config


class Logger:
	"""
	Logger

	Sets up a rotating logger that writes to a log file
	"""
	logger = None
	log_path = None

	def __init__(self):
		"""
		Set up log handler
		"""
		self.logger = logging.getLogger("4cat-backend")
		self.logger.setLevel(logging.INFO)
		self.log_path = get_absolute_folder(config.PATH_LOGS) + "/4cat.log"

		handler = RotatingFileHandler(self.log_path, maxBytes=(25 * 1024 * 1024), backupCount=0)
		handler.setLevel(logging.INFO)
		handler.setFormatter(logging.Formatter("%(asctime)-15s | %(levelname)s (%(filename)s:%(lineno)d): %(message)s",
											   "%d-%m-%Y %H:%M:%S"))

		self.logger.addHandler(handler)
		self.info("Logging to %s" % self.log_path)

	def enable_mailer(self):
		"""
		Enable the log mailer

		This sends an e-mail to a pre-defined address when a log message of at least
		level WARNING is logged.
		"""
		mailer = SMTPHandler("localhost", "backend@4cat.oilab.eu", config.WARN_EMAILS, "4CAT Backend logger")
		mailer.setLevel(logging.WARNING)

		self.logger.addHandler(mailer)

	def get_location(self):
		"""
		Get location of log file

		:return string:  Absolute path to log location
		"""
		return self.log_path

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
