"""
Tests for which log messages are sent to Slack

Messages at or above the configured alert level are sent. A message can also be
sent whatever its level, with `force_slack=True`, e.g. to report that a problem
that was alerted about has been resolved.
"""
import traceback
import logging

import pytest

from common.lib.logger import Logger, SlackAlertFilter


def make_record(level, **extra):
    record = logging.LogRecord("4cat", level, __file__, 1, "message", None, None)
    record.__dict__.update(extra)
    return record


@pytest.fixture
def slack_log(tmp_path):
    """
    Logger with a stand-in for the Slack handler, which collects the messages
    that would be sent to Slack

    Loggers are shared by the whole process, so the handlers are removed and
    closed again afterwards.
    """
    log = Logger(log_path=tmp_path / "4cat.log", logger_name="test-force-slack")

    sent = []
    slack = logging.Handler()
    slack.emit = sent.append
    slack.addFilter(SlackAlertFilter(logging.WARNING))
    log.logger.addHandler(slack)

    yield log, sent

    for handler in list(log.logger.handlers):
        log.logger.removeHandler(handler)
        handler.close()


def test_messages_at_alert_level_or_above_are_sent():
    alert_filter = SlackAlertFilter(logging.WARNING)

    assert alert_filter.filter(make_record(logging.WARNING))
    assert alert_filter.filter(make_record(logging.ERROR))
    assert not alert_filter.filter(make_record(logging.INFO))


def test_forced_messages_are_sent_whatever_their_level():
    alert_filter = SlackAlertFilter(logging.WARNING)

    assert alert_filter.filter(make_record(logging.INFO, force_slack=True))
    assert not alert_filter.filter(make_record(logging.INFO, force_slack=False))


def test_logger_passes_force_slack_on(slack_log):
    """
    `force_slack` given to the logger reaches the filter
    """
    log, sent = slack_log

    log.info("not sent")
    log.info("sent", force_slack=True)
    log.warning("also sent")

    assert [record.getMessage() for record in sent] == ["sent", "also sent"]


def test_info_uses_the_frame_it_is_given(slack_log):
    """
    A message logged with a frame is reported as coming from that frame, also
    for info messages
    """
    log, sent = slack_log

    log.info("sent", frame=traceback.FrameSummary("crawler.py", 42, "crawl"), force_slack=True)

    assert sent[0].location == "crawler.py:42"
