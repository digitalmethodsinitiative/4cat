"""
Log handler
"""
import requests
import datetime
import platform
import smtplib
import logging
import socket
import time
import json
import sys
import re

from collections import OrderedDict
from pathlib import Path

from logging.handlers import RotatingFileHandler, SMTPHandler
from common.lib.helpers import send_email

import config


class Logger:
	"""
	Logger

	Sets up a rotating logger that writes to a log file
	"""
	logger = None
	log_path = None
	print_logs = True
	db = None
	previous_report = 0
	levels = {
		"DEBUG": logging.DEBUG,
		"INFO": logging.INFO,
		"WARNING": logging.WARNING,
		"ERROR": logging.ERROR,
		"CRITICAL": logging.CRITICAL,
		"FATAL": logging.FATAL
	}
	alert_level = "FATAL"

	def __init__(self, output=False, db=None):
		"""
		Set up log handler

		:param bool output:  Whether to print logs to output
		"""
		if self.logger:
			return

		self.print_logs = output
		self.log_path = Path(config.PATH_ROOT, config.PATH_LOGS, "4cat.log")
		self.previous_report = time.time()

		self.logger = logging.getLogger("4cat-backend")
		self.logger.setLevel(logging.INFO)

		# this handler manages the text log files
		handler = RotatingFileHandler(self.log_path, maxBytes=(50 * 1024 * 1024), backupCount=1)
		handler.setLevel(logging.DEBUG)
		handler.setFormatter(logging.Formatter("%(asctime)-15s | %(levelname)s %(message)s",
											   "%d-%m-%Y %H:%M:%S"))

		self.logger.addHandler(handler)

		if hasattr(config, "WARN_LEVEL"):
			self.alert_level = self.levels.get(config.WARN_LEVEL, self.alert_level)

		if db:
			self.db = db

	def enable_mailer(self):
		"""
		Enable the log mailer

		This sends an e-mail to a pre-defined address when a log message of at least
		level WARNING is logged.
		"""
		mailer = SMTPHandler("localhost", config.NOREPLY_EMAIL, config.WARN_EMAILS, "4CAT Backend logger")
		mailer.setLevel(logging.WARNING)

		self.logger.addHandler(mailer)

	def log(self, message, level=logging.INFO, slack_alert=True):
		"""
		Log message

		:param message:  Message to log
		:param level:  Severity level, should be a logger.* constant
		:param bool slack_alert:  If configured, send a log alert to slack webhook
		"""
		if self.print_logs and level > logging.DEBUG:
			print("LOG: %s" % message)

		# because we use a wrapper the context location the logger itself is
		# useless (it will always point to this function) so we get it
		# ourselves
		bare_message = message
		try:
			frames = []
			frame_index = 2
			while True:
				try:
					frame = sys._getframe(frame_index)
					frames.append(frame)
				except ValueError:
					break
				frame_index += 1

			file_location = frames[0].f_code.co_filename.split("/").pop() + ":" + str(frames[-1].f_lineno)
			message = "(" + file_location + ")" + ": " + message
		except AttributeError:
			# the _getframe method may not be available
			message = ": " + message
			location = "Unknown"
			frames = []

		self.logger.log(level, message)

		# log messages can optionally be sent as a Slack alert
		# this is configured in config.py with WARN_SLACK_URL and WARN_LEVEL
		if level >= self.alert_level and hasattr(config, "WARN_SLACK_URL") and config.WARN_SLACK_URL:
			# determine appropriate colour - red = uh oh, orange = warning, rest = green
			if level in (logging.ERROR, logging.CRITICAL):
				color = "#FF0000"  # red
			elif level == logging.WARNING:
				color = "#DD7711"  # orange
			else:
				color = "#3CC619"  # green

			# include full call stack for easier debugging
			location = "`%s`" % "` ← `".join(
				[frame.f_code.co_filename.split("/").pop() + ":" + str(frame.f_lineno) for frame in frames])

			# prepare slack webhook payload
			message = {
				"text": "4CAT Alert logged on `%s`:" % platform.uname().node,
				"mrkdwn_in": ["text"],
				"attachments": [{
					"color": color,
					"text": bare_message + "\n",
					"fields": [{
						"title": "Location",
						"value": location,
						"short": False
					}]
				}]
			}

			# call the Slack web hook
			if slack_alert:
				try:
					e = requests.post(config.WARN_SLACK_URL, json.dumps(message))
				except requests.RequestException as e:
					# do not use self.warning because it will trigger an infinite
					# loop of trying to send something to Slack
					self.log(self.levels["WARNING"], "Could not send log alerts to Slack webhook (%s)" % e, False)

		# every 10 minutes, collect and send warnings etc
		if config.WARN_EMAILS and self.previous_report < time.time() - config.WARN_INTERVAL:
			self.previous_report = time.time()
			self.collect_and_send()

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

	def fatal(self, message):
		"""
		Log FATAL level message

		:param message: Message to log
		"""
		self.log(message, logging.FATAL)

	def collect_and_send(self):
		"""
		Compile a report of recently logged alerts and send it to the admins
		"""
		grouped_logs = {}
		log_regex = re.compile("([0-9: -]+) \| ([A-Z]+) \(([^)]+)\): (.+)")
		try:
			min_level = self.levels[config.WARN_LEVEL]
		except KeyError:
			min_level = self.levels["WARNING"]

		# this string will be used to recognize when a report was last compiled
		magic = "Compiling logs into report"

		# process lines from log
		with open(self.log_path) as logfile:
			logs = logfile.readlines()

		warnings = 0
		for log in reversed(logs):
			log = log.strip()

			# filter info from log file
			bits = re.match(log_regex, log)
			if not bits:
				# line does not match log format...
				continue

			if bits.group(4).strip() == magic:
				# anything beyond this message has already been compiled/processed earlier
				break

			key = bits.group(3) + ":" + bits.group(4)
			timestamp = datetime.datetime.strptime(bits.group(1), '%d-%m-%Y %H:%M:%S').timestamp()
			level = self.levels[bits.group(2)] if bits.group(2) in self.levels else self.levels["DEBUG"]

			# see if the message is important enough to be in the report
			if level < min_level:
				continue

			warnings += 1

			# store logs, grouped by combination of log message and log location
			if key in grouped_logs:
				grouped_logs[key]["first"] = min(grouped_logs[key]["first"], timestamp)
				grouped_logs[key]["last"] = max(grouped_logs[key]["last"], timestamp)
				grouped_logs[key]["amount"] += 1
			else:
				grouped_logs[key] = {
					"location": bits.group(3),
					"message": bits.group(4),
					"level": bits.group(2),
					"first": timestamp,
					"last": timestamp,
					"amount": 1
				}

		self.info(magic)
		# see if we have anything to send
		if not grouped_logs:
			return

		# order logs, most-logged message first
		sorted_logs = OrderedDict()
		sort_keys = {logkey: grouped_logs[logkey]["amount"] for logkey in grouped_logs}
		for logkey in sorted(sort_keys, key=sort_keys.__getitem__):
			sorted_logs[logkey] = grouped_logs[logkey]

		# compile a report to send to an unfortunate admin, if so configured
		if config.WARN_EMAILS:
			mail = "Hello! The following 4CAT warnings were logged since the last alert:\n\n"
			for logkey in reversed(sorted_logs):
				log = sorted_logs[logkey]
				first = datetime.datetime.utcfromtimestamp(log["first"]).strftime("%d %b '%y %H:%M:%S")
				last = datetime.datetime.utcfromtimestamp(log["last"]).strftime("%d %b '%y %H:%M:%S")
				mail += "- *%s*\n" % log["message"]
				mail += "  _%s_ - %ix at %s (first %s, last %s)\n\n" % (
					log["level"], log["amount"], log["location"], first, last)

			mail += "This report was compiled at %s." % datetime.datetime.now().strftime('%d %B %Y %H:%M:%S')

			try:
				send_email(config.WARN_EMAILS, mail)
			except (smtplib.SMTPException, ConnectionRefusedError, socket.timeout) as e:
				self.error("Could not send log alerts via e-mail (%s)" % e)
