#!/usr/bin/python3

# Munin plugin for 4CAT - Max non-recurring job age in queue
# Reports the age of the oldest job in the queue that is not a recurring job.
# This can be used to check for jobs that are stuck or to assess whether more
# workers should be added for a particular job type.

import psycopg2
import psycopg2.extras
import time
import sys
import os

os.chdir("/opt/4cat")
from config import DATASOURCES, DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT

connection = psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, host=DB_HOST, port=DB_PORT)
cursor = connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
query = "SELECT id, interval, timestamp_lastclaimed, jobtype, timestamp_after, timestamp FROM jobs WHERE timestamp_claimed = 0"

cursor.execute(query)
data = cursor.fetchall()

if len(sys.argv) > 1 and sys.argv[1] == "config":
	print("graph_title 4CAT Oldest non-recurring job in queue")
	print("graph_args -l 0")
	print("graph_vlabel Age (seconds)")
	print("graph_category 4cat")
	print("graph_info Age of oldest non-recurring job that is queued, in seconds")
	print("overall.warning :800")
	print("overall.critical :1800")
	print("overall.label Overall")
	types = sorted(set([job["jobtype"] for job in data]))
	for type in types:
		print("worker-%s.label %s" % (type, type))
	sys.exit(0)

oldest = {"overall": 0}
for row in data:
	if row["timestamp_after"] > time.time():
		continue

	typename = "worker-%s" % row["jobtype"]
	if typename not in oldest:
		oldest[typename] = 0

	if row["interval"] > 0:
		if row["timestamp_lastclaimed"] + row["interval"] > time.time():
			continue
		age = time.time() - row["timestamp_lastclaimed"] + row["interval"]
	elif row["timestamp_after"] > 0:
		age = time.time() - row["timestamp_after"]
	else:
		age = time.time() - row["timestamp"]

	oldest["overall"] = max(oldest["overall"], int(age))
	oldest[typename] = max(oldest[typename], int(age))

for type in oldest:
	print("%s.value %i" % (type, oldest[type]))