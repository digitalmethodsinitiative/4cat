"""
Log handler
"""
import traceback
import platform
import logging
import time
import json

from pathlib import Path

from logging.handlers import RotatingFileHandler, HTTPHandler

import common.config_manager as config


class WebHookLogHandler(HTTPHandler):
    """
    Basic HTTPHandler for webhooks via standard log handling

    In essence, an HTTPHandler that formats its payload as JSON.
    """
    server_name = ""

    def __init__(self, url):
        """
        Initialise WebHook handler

        :param str url:  URL to send log messages to
        """
        host = url.split("/")[2]
        secure = url.lower().startswith("https")

        super().__init__(host, url, method="POST", secure=secure)

    def emit(self, record):
        """
        Emit a record

        Send the record to the Web server as a percent-encoded dictionary
        This is the `emit()` method of the original HTTPHandler; the only
        change is that content is sent as JSON (which the webhooks expect)
        instead of urlencoded data.

        :param logging.LogRecord record:  Log record to send
        """
        try:
            import http.client, urllib.parse
            host = self.host
            if self.secure:
                h = http.client.HTTPSConnection(host, context=self.context)
            else:
                h = http.client.HTTPConnection(host)
            url = self.url
            ############### CHANGED FROM ORIGINAL ###############
            data = json.dumps(self.mapLogRecord(record))
            #####################################################
            if self.method == "GET":
                if (url.find('?') >= 0):
                    sep = '&'
                else:
                    sep = '?'
                url = url + "%c%s" % (sep, data)
            h.putrequest(self.method, url)
            # support multiple hosts on one IP address...
            # need to strip optional :port from host, if present
            i = host.find(":")
            if i >= 0:
                host = host[:i]
            # See issue #30904: putrequest call above already adds this header
            # on Python 3.x.
            # h.putheader("Host", host)
            if self.method == "POST":
                ############### CHANGED FROM ORIGINAL ###############
                h.putheader("Content-type", "application/json")
                #####################################################
                h.putheader("Content-length", str(len(data)))
            if self.credentials:
                import base64
                s = ('%s:%s' % self.credentials).encode('utf-8')
                s = 'Basic ' + base64.b64encode(s).strip().decode('ascii')
                h.putheader('Authorization', s)
            h.endheaders()
            if self.method == "POST":
                h.send(data.encode('utf-8'))
            h.getresponse()  # can't do anything with the result
        except Exception:
            self.handleError(record)


class SlackLogHandler(WebHookLogHandler):
    """
    Slack webhook log handler
    """

    def mapLogRecord(self, record):
        """
        Format log message so it is compatible with Slack webhooks

        :param logging.LogRecord record: Log record
        """
        if record.levelno in (logging.ERROR, logging.CRITICAL):
            color = "#FF0000"  # red
        elif record.levelno == logging.WARNING:
            color = "#DD7711"  # orange
        else:
            color = "#3CC619"  # green

        # simple stack trace
        location = "`%s`" % "` → `".join(
            [frame.filename.split("/")[-1] + ":" + str(frame.lineno) for frame in traceback.extract_stack()[:-9]])

        # prepare slack webhook payload
        return {
            "text": ":bell: 4CAT %s logged on `%s`:" % (record.levelname.lower(), platform.uname().node),
            "mrkdwn_in": ["text"],
            "attachments": [{
                "color": color,
                "text": record.message + "\n",
                "fields": [{
                    "title": "Stack trace",
                    "value": location,
                    "short": False
                }]
            }]
        }


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

    def __init__(self, output=False, filename='4cat.log'):
        """
        Set up log handler

        :param bool output:  Whether to print logs to output
        """
        if self.logger:
            return

        self.print_logs = output
        log_folder = Path(config.get('PATH_ROOT'), config.get('PATH_LOGS'))
        if not log_folder.exists():
            log_folder.mkdir(parents=True)

        self.log_path = log_folder.joinpath(filename)
        self.previous_report = time.time()

        self.logger = logging.getLogger("4cat-backend")
        self.logger.setLevel(logging.INFO)

        # this handler manages the text log files
        handler = RotatingFileHandler(self.log_path, maxBytes=(50 * 1024 * 1024), backupCount=1)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(asctime)-15s | %(levelname)s at %(location)s: %(message)s",
                                               "%d-%m-%Y %H:%M:%S"))
        self.logger.addHandler(handler)

        # the slack webhook has its own handler, and is only active if the
        # webhook URL is set
        if config.get("logging.slack.webhook"):
            slack_handler = SlackLogHandler(config.get("logging.slack.webhook"))
            slack_handler.setLevel(self.levels.get(config.get("logging.slack.level"), self.alert_level))
            self.logger.addHandler(slack_handler)

    def log(self, message, level=logging.INFO):
        """
        Log message

        :param message:  Message to log
        :param level:  Severity level, should be a logger.* constant
        """
        if self.print_logs and level > logging.DEBUG:
            print("LOG: %s" % message)

        # logging can include the full stack trace in the log, but that's a
        # bit excessive - instead, only include the location the log was called
        frame = traceback.extract_stack()[-3]
        location = frame.filename.split("/")[-1] + ":" + str(frame.lineno)
        self.logger.log(level, message, extra={"location": location})

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
