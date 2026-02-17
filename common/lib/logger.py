"""
Log handler
"""
import traceback
import platform
import logging
import time
import json
import re

from pathlib import Path

from logging.handlers import RotatingFileHandler, HTTPHandler

from common.config_manager import CoreConfigManager
from common.lib.helpers import get_software_commit

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
            import http.client
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
    _base_github_url = ""
    _base_4cat_url = ""
    _base_4cat_path = ""
    _extension_path = ""

    def __init__(self, *args, **kwargs):
        """
        Constructor

        We add an argument for the Github link to link to in the stack trace
        for easier debugging.

        :param args:
        :param kwargs:
        """
        if "config" in kwargs:
            config = kwargs["config"]
            del kwargs["config"]
        else:
            raise TypeError("SlackLogHandler() expects a config reader as argument")

        # construct a github URL to link in slack alerts to easily review
        # erroneous code
        if config.get("4cat.github_url"):
            github_url = config.get("4cat.github_url")
            if github_url.endswith("/"):
                github_url = github_url[:-1]
            github_url += "/blob/"

            # use commit hash if available, else link to master
            commit = get_software_commit()
            github_url += f"{commit[0] or 'master'}/"
            self._base_github_url = github_url

        # we cannot use the config reader later because the logger is shared
        # across threads and the config reader/memcache is not thread-safe, so
        # pre-read the relevant values here
        self._base_4cat_url = f"http{'s' if config.get('flask.https') else ''}://{config.get('flask.server_name')}/results/"
        self._base_4cat_path = config.get("PATH_ROOT")
        self._extension_path = config.get("PATH_EXTENSIONS")

        super().__init__(*args, **kwargs)

    def mapLogRecord(self, record):
        """
        Format log message so it is compatible with Slack webhooks

        :param logging.LogRecord record: Log record
        """
        if record.levelno in (logging.ERROR, logging.CRITICAL):
            emoji = ":skull:"
            color = "#FF0000"  # red
        elif record.levelno == logging.WARNING:
            emoji = ":bell:"
            color = "#DD7711"  # orange
        else:
            emoji = ":information_source:"
            color = "#3CC619"  # green

        # this also catches other 32-char hex strings...
        # but a few false positives are OK as a trade-off for the convenience
        error_message = re.sub(r"\b([0-9a-fA-F]{32})\b", f"<{self._base_4cat_url}\\1/|\\1>", record.message)

        # simple stack trace
        if record.stack:
            # this is the stack where the log was called
            frames = record.stack
        else:
            # the last 9 frames are not specific to the exception (general logging code etc)
            # the frame before that is where the exception was raised
            frames = traceback.extract_stack()[:-9]

        # go through the traceback and distinguish 4CAT's own code from library
        # or stdlib code, and annotate accordingly
        nice_frames = []
        highlight_frame = None
        highlight_link = None
        for frame in frames:
            framepath = Path(frame.filename)
            frame_location = frame.filename.split("/")[-1] + ":" + str(frame.lineno)

            # make a link to the github if it is a file in the 4cat root and
            # not in the venv (i.e. it is 4CAT's own code)
            if (
                    framepath.is_relative_to(self._base_4cat_path)
                    and not framepath.is_relative_to(self._extension_path)
                    and "site-packages" not in framepath.parts
                    and self._base_github_url
            ):
                sub_path = str(framepath.relative_to(self._base_4cat_path))
                url = f"{self._base_github_url}{sub_path}#L{frame.lineno}"
                frame_location = f"<{url}|`{frame_location}`>"
                highlight_frame = frame
                highlight_link = frame_location
            else:
                frame_location = f"_`{frame_location}`_"

            if not highlight_frame:
                highlight_frame = frame
                highlight_link = frame_location

            nice_frames.append(frame_location)

        # prepare slack webhook payload
        attachments = [{
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Stack trace:*\n{' → '.join(nice_frames)}"
            }
        }]

        # try to read some metadata from the offending file
        try:
            with Path(highlight_frame.filename).open() as infile:
                attachments.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Code* (" + highlight_link + "):\n```" + infile.readlines()[highlight_frame.lineno - 1].strip() + "```",
                    }
                })
        except (IndexError, AttributeError):
            # the file is not readable, or the line number is out of bounds
            pass

        return {
            "attachments": [
                {
                    "color": color,
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"{emoji} *4CAT {record.levelname.lower()} logged on `{platform.uname().node}`:*",
                            },
                        },
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": error_message},
                        },
                        *attachments,
                    ],
                }
            ]
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
        "DEBUG2": 5,  # logging.DEBUG = 10
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
        "FATAL": logging.FATAL
    }
    alert_level = "FATAL"

    def __init__(self, log_path="4cat.log", logger_name='4cat', output=False, log_level="INFO"):
        """
        Set up log handler

        :param str|Path filename:  File path that will be written to
        :param str logger_name:  Identifier for logging context
        :param bool output:  Whether to print logs to output
        :param str log_level:  Messages at this level or below will be logged
        """
        if self.logger:
            return
        log_level = self.levels.get(log_level, logging.INFO)

        self.print_logs = output

        if type(log_path) is str:
            core_config = CoreConfigManager()
            log_path = core_config.get("PATH_LOGS").joinpath(log_path)

        if not log_path.parent.exists():
            log_path.parent.mkdir(parents=True)

        self.log_path = log_path
        self.previous_report = time.time()

        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(log_level)

        # this handler manages the text log files
        formatter = logging.Formatter("%(asctime)-15s | %(levelname)s at %(location)s: %(message)s",
                                                   "%d-%m-%Y %H:%M:%S")
        if not self.logger.handlers:
            handler = RotatingFileHandler(self.log_path, maxBytes=(50 * 1024 * 1024), backupCount=1)
            handler.setLevel(log_level)
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

        # to stdout
        if output:
            handler = logging.StreamHandler()
            handler.setLevel(log_level)
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def load_webhook(self, config):
        """
        Load webhook configuration

        The webhook is configured in the database; but the logger may not
        always have access to the database. So instead of setting it up at
        init, this function must be called explicitly to enable it for this
        logger instance.

        :param config:  Configuration reader
        :return:
        """
        if config.get("logging.slack.webhook"):
            slack_handler = SlackLogHandler(config.get("logging.slack.webhook"), config=config)
            slack_handler.setLevel(self.levels.get(config.get("logging.slack.level"), self.alert_level))
            self.logger.addHandler(slack_handler)

    def log(self, message, level=logging.INFO, frame=None):
        """
        Log message

        :param message:  Message to log
        :param level:  Severity level, should be a logger.* constant
        :param frame:  Traceback frame. If no frame is given, it is
        extrapolated
        """
        if type(frame) is traceback.StackSummary:
            # Full stack was provided
            stack = frame
            frame = stack[-1]
        else:
            # Collect the stack (used by Slack)
            stack = traceback.extract_stack()[:-2]

        if frame is None:
            # Use the last frame in the stack
            frame = stack[-1]
        else:
            # Frame was provided; use it
            pass

        # Logging uses the location, Slack uses the full stack
        location = frame.filename.split("/")[-1] + ":" + str(frame.lineno)
        self.logger.log(level, message, extra={"location": location, "frame": frame, "stack": stack})

    def debug2(self, message, frame=None):
        """
        Log DEBUG2 level message

        DEBUG2 is a custom log level, with less priority than the standard DEBUG

        :param message: Message to log
        :param frame:  Traceback frame relating to the error
        """
        self.log(message, 5, frame)

    def debug(self, message, frame=None):
        """
        Log DEBUG level message

        :param message: Message to log
        :param frame:  Traceback frame relating to the error
        """
        self.log(message, logging.DEBUG, frame)

    def info(self, message, frame=None):
        """
        Log INFO level message

        :param message: Message to log
        :param frame:  Traceback frame relating to the error
        """
        self.log(message, logging.INFO)

    def warning(self, message, frame=None):
        """
        Log WARNING level message

        :param message: Message to log
        :param frame:  Traceback frame relating to the error
        """
        self.log(message, logging.WARN, frame)

    def error(self, message, frame=None):
        """
        Log ERROR level message

        :param message: Message to log
        :param frame:  Traceback frame relating to the error
        """
        self.log(message, logging.ERROR, frame)

    def critical(self, message, frame=None):
        """
        Log CRITICAL level message

        :param message: Message to log
        :param frame:  Traceback frame relating to the error
        """
        self.log(message, logging.CRITICAL, frame)

    def fatal(self, message, frame=None):
        """
        Log FATAL level message

        :param message: Message to log
        :param frame:  Traceback frame relating to the error
        """
        self.log(message, logging.FATAL, frame)
