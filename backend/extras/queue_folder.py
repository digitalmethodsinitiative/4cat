import argparse
import glob
import time
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/../..")
from backend.lib.database import Database
from backend.lib.logger import Logger
from backend.lib.queue import JobQueue

# parse parameters
cli = argparse.ArgumentParser()
cli.add_argument("-i", "--input", required=True, help="Folder to read from, containing JSON files representing threads")
cli.add_argument("-p", "--platform", type=str, required=True, help="Datasource ID")
cli.add_argument("-b", "--board", type=str, required=True, help="Board name")
args = cli.parse_args()

if not os.path.exists(args.input) or not os.path.isdir(args.input):
	print("%s is not a valid folder name." % args.input)
	sys.exit(1)

input = os.path.realpath(args.input)
jsons = glob.glob(input + "/*.json")

print("Initialising queue...")
logger = Logger()
queue = JobQueue(logger=logger, database=Database(logger=logger))

print("Adding files to queue...")
deadline = int(time.time()) + 1
for file in jsons:
	file = file.split("/").pop()
	path = input + "/" + file
	queue.add_job(args.platform + "-thread", remote_id=file, details={"board": args.board, "file": path}, claim_after=deadline)
	deadline += 1

print("Queued %i files." % len(jsons))