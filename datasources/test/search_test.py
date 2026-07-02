"""
Test datasource search worker (development only)

This worker only registers itself when the ``FOURCAT_ENABLE_TEST_DATASOURCE``
environment variable is set to a truthy value, so it never loads on a normal or
production instance. It produces dummy datasets in one of three deliberately
distinct states, selected via the ``mode`` parameter:

- ``complete``:  writes a few dummy rows and finishes normally
- ``forever``:   runs indefinitely (until interrupted), updating progress
- ``crash``:     raises a generic exception; because an unhandled exception
                 leaves the job claimed but releases no worker, this reproduces
                 the ``is_maybe_crashed`` state (claimed job, no live worker)

Use ``helper-scripts/create_test_jobs.py`` to enqueue one of each. Note that the
backend daemon must also have ``FOURCAT_ENABLE_TEST_DATASOURCE`` set for the
jobs to actually be picked up and run.
"""
import os
import time

from backend.lib.search import Search
from common.lib.user_input import UserInput
from common.lib.item_mapping import MappedItem
from common.lib.exceptions import ProcessorInterruptedException, ProcessorException
from common.lib.outputs import Datasource

# only make this worker available when explicitly enabled, so it never loads on
# a normal/production instance (the datasource folder is always discovered, but
# without this class there is no `test-search` worker and nothing can run)
TEST_DATASOURCE_ENABLED = os.environ.get("FOURCAT_ENABLE_TEST_DATASOURCE", "").lower() in ("1", "true", "yes", "on")

if TEST_DATASOURCE_ENABLED:

    class SearchTest(Search):
        """
        Dummy search worker for exercising the worker/queue status pages
        """
        type = "test-search"  # job ID
        category = "Search"  # category
        title = "Test datasource (dev only)"  # title displayed in UI
        description = "Development-only datasource that creates dummy datasets in various states (complete, forever, crash) to exercise admin status pages."
        extension = "ndjson"  # extension of result file
        output = Datasource()

        # not offered as a processor for existing datasets
        accepts = [None]

        @classmethod
        def get_queue_id(cls, remote_id, details, dataset) -> str:
            # one queue per job so the dummy jobs run concurrently instead of
            # serialising behind one another (a 'forever' job would otherwise block
            # the rest).
            return f"{cls.type}-{remote_id}"

        @classmethod
        def get_options(cls, parent_dataset=None, config=None):
            return {
                "mode": {
                    "type": UserInput.OPTION_CHOICE,
                    "help": "Test mode",
                    "options": {
                        "complete": "Complete normally (writes dummy rows)",
                        "forever": "Run forever (until interrupted)",
                        "crash": "Crash (raise an exception)",
                    },
                    "default": "complete",
                },
                "amount": {
                    "type": UserInput.OPTION_TEXT,
                    "help": "Number of dummy rows (complete mode)",
                    "coerce_type": int,
                    "default": 5,
                    "min": 0,
                },
            }

        def get_items(self, query):
            """
            Generate dummy items, or run forever, or crash - depending on mode

            :param dict query:  Query parameters, expects a `mode` key
            :return:  Iterable of dummy items (complete mode) or None (forever)
            """
            mode = query.get("mode", "complete")

            if mode == "crash":
                # leaves the job claimed with no live worker once the thread
                # ends -> shows up as `is_maybe_crashed` on the status page
                self.dataset.update_status("Test datasource: about to raise an exception")
                raise Exception("Test datasource intentional crash (mode=crash)")

            if mode == "forever":
                # block here until interrupted; this holds a worker slot so the
                # job shows up as actively running with a moving progress bar
                tick = 0
                while True:
                    if self.interrupted:
                        raise ProcessorInterruptedException("Interrupted while running forever (mode=forever)")
                    tick += 1
                    self.dataset.update_status("Test datasource: running forever (tick %i)" % tick)
                    # oscillate progress 0..1 so the bar is visibly active
                    self.dataset.update_progress((tick % 20) / 20)
                    time.sleep(2)

            if self.job.is_recurring:
                # recurring jobs are not expected to produce any items, so don't
                # return any; just update the status and progress so the job
                # shows up as active on the status page.
                self.dataset.update_status("Test datasource: recurring job (mode=%s)" % mode)
                self.dataset.update_progress(0.5)
                raise ProcessorException("Recurring jobs are not expected to produce DataSets; this is a test datasource.")

            # mode == "complete": write some dummy rows and finish
            amount = query.get("amount", 5)
            items = []
            for i in range(amount):
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while generating dummy data (mode=complete)")
                self.dataset.update_progress((i + 1) / amount if amount else 1)
                items.append({
                    "id": str(i),
                    "thread_id": str(i),
                    "subject": "Dummy item %i" % i,
                    "body": "This is dummy test item %i." % i,
                    "author": "test_user",
                    "timestamp": "1970-01-01 00:00:00",
                })

            return items

        @staticmethod
        def map_item(item):
            return MappedItem({
                "id": item.get("id", ""),
                "thread_id": item.get("thread_id", ""),
                "subject": item.get("subject", ""),
                "body": item.get("body", ""),
                "author": item.get("author", ""),
                "timestamp": item.get("timestamp", "1970-01-01 00:00:00"),
            })
