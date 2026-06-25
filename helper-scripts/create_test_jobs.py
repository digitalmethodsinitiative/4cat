"""
Enqueue dummy "test datasource" jobs in various states.

This creates datasets/jobs for the development-only `test` datasource (see
`datasources/test/`) so the worker-status / queue admin pages can be exercised
without a real data collection. It can enqueue any combination of:

- complete:  finishes normally (a healthy dataset; not shown as "running")
- forever:   runs indefinitely -> shows as actively running with progress
- crash:     raises an exception -> shows as `is_maybe_crashed` (claimed, no worker)

The backend daemon must ALSO have FOURCAT_ENABLE_TEST_DATASOURCE set (in its
environment) for these jobs to be picked up and run; otherwise the
`test-search` worker is not registered and the jobs sit in the queue.

Usage:
    python helper-scripts/create_test_jobs.py            # one of each
    python helper-scripts/create_test_jobs.py -m forever crash
"""
import argparse
import sys
import os

# make sure the test datasource worker is registered for THIS process, so
# DataSet/ModuleCollector can resolve the `test-search` type while enqueuing
os.environ.setdefault("FOURCAT_ENABLE_TEST_DATASOURCE", "1")

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/..")
from common.lib.database import Database
from common.lib.logger import Logger
from common.lib.queue import JobQueue
from common.lib.dataset import DataSet
from common.lib.job import Job
from common.lib.module_loader import ModuleCollector
from common.config_manager import ConfigManager

cli = argparse.ArgumentParser()
cli.add_argument("-m", "--modes", nargs="+", default=["complete", "forever", "crash"],
                 choices=["complete", "forever", "crash"], help="Which dummy job state(s) to enqueue")
cli.add_argument("-i", "--interval", default=0, type=int, help="Interval between jobs (seconds)")
cli.add_argument("-u", "--user", default="anonymous", help="Username to assign the datasets to")
cli.add_argument("-a", "--amount", type=int, default=5, help="Dummy rows for 'complete' mode")
args = cli.parse_args()

config = ConfigManager()
logger = Logger(log_path=config.get("PATH_LOGS").joinpath("create-test-jobs.log"))
db = Database(logger=logger, dbname=config.get("DB_NAME"), user=config.get("DB_USER"),
             password=config.get("DB_PASSWORD"), host=config.get("DB_HOST"), port=config.get("DB_PORT"),
             appname="create-test-jobs")
config.with_db(db)
modules = ModuleCollector(config)
queue = JobQueue(logger=logger, database=db)

if "test-search" not in modules.workers:
    print("The 'test-search' worker is not registered - cannot enqueue test jobs.")
    print("(This should not happen here since the env var is forced on; check datasources/test/.)")
    sys.exit(1)

worker = modules.workers["test-search"]

for mode in args.modes:
    dataset = DataSet(
        parameters={"datasource": "test", "type": "test-search", "mode": mode, "amount": args.amount},
        db=db,
        type="test-search",
        extension="ndjson",
        is_private=False,
        owner=args.user,
        modules=modules
    )
    dataset.update_label("Test job (%s)" % mode)
    queue.add_job(worker_or_type=worker, dataset=dataset, interval=args.interval)
    job = Job.get_by_remote_ID(dataset.key, db)
    dataset.link_job(job)
    print("Queued '%s' test job: dataset %s" % (mode, dataset.key))

print("Done. Make sure the backend has FOURCAT_ENABLE_TEST_DATASOURCE set so the jobs run.")
