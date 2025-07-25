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

from common.config_manager import CoreConfigManager

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
        if record.stack:
            # this is the stack where the log was called
            frames = record.stack
        else:
            # the last 9 frames are not specific to the exception (general logging code etc)
            # the frame before that is where the exception was raised
            frames = traceback.extract_stack()[:-9]
        location = "`%s`" % "` → `".join([frame.filename.split("/")[-1] + ":" + str(frame.lineno) for frame in frames])

        # prepare slack webhook payload
        fields = [{
            "title": "Stack trace:",
            "value": location,
            "short": False
        }]

        # try to read some metadata from the offending file
        try:
            with Path(record.frame.filename).open() as infile:
                fields.append({
                    "title": "Code (`" + record.frame.filename.split("/")[-1] + ":" + str(record.frame.lineno) + "`):",
                    "value": "```" + infile.readlines()[record.frame.lineno - 1].strip() + "```",
                    "short": False
                })
        except (IndexError, AttributeError):
            # the file is not readable, or the line number is out of bounds
            pass

        return {
            "text": ":bell: 4CAT %s logged on `%s`:" % (record.levelname.lower(), platform.uname().node),
            "mrkdwn_in": ["text"],
            "attachments": [{
                "color": color,
                "text": record.message,
                "fields": fields
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
        if not self.logger.handlers:
            handler = RotatingFileHandler(self.log_path, maxBytes=(50 * 1024 * 1024), backupCount=1)
            handler.setLevel(log_level)
            handler.setFormatter(logging.Formatter("%(asctime)-15s | %(levelname)s at %(location)s: %(message)s",
                                                   "%d-%m-%Y %H:%M:%S"))
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
            slack_handler = SlackLogHandler(config.get("logging.slack.webhook"))
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
            # Full strack was provided
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
