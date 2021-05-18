"""
Queue JSON files in a given folder to be processed by 4CAT's scrapers

This can be used to import, for example, 4chan API output that has been
downloaded elsewhere.
"""
import argparse
import time
import sys
import os

from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/..")
from common.lib.database import Database
from common.lib.logger import Logger
from common.lib.queue import JobQueue

# parse parameters
cli = argparse.ArgumentParser()
cli.add_argument("-i", "--input", required=True, help="Folder to read from, containing JSON files representing threads")
cli.add_argument("-d", "--datasource", type=str, required=True, help="Datasource ID")
cli.add_argument("-b", "--board", type=str, required=True, help="Board name")
args = cli.parse_args()

if not Path(args.input).exists() or not Path(args.input).is_dir():
	print("%s is not a valid folder name." % args.input)
	sys.exit(1)

input = Path(args.input).resolve()
jsons = input.glob("*.json")

print("Initialising queue...")
logger = Logger()
queue = JobQueue(logger=logger, database=Database(logger=logger, appname="queue-folder"))

print("Adding files to queue...")
files = 0
deadline = time.time()
for file in jsons:
	files += 1
	file = str(file)
	queue.add_job(args.datasource + "-thread", remote_id=file, details={"board": args.board, "file": str(file)}, claim_after=int(deadline))
	deadline += 0.1

print("Queued %i files." % files)