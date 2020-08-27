#!/usr/bin/python3

# Munin plugin for 4CAT - Posts scraped per hour
# Reports the amount of posts scraped for all platforms that are actively
# scraped (in practice, this is probably 4chan and/or 8chan)

import psycopg2
import psycopg2.extras
import time
import sys
import os

os.chdir("/opt/4cat")
sys.path.append("/opt/4cat")
from config import DATASOURCES, DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT

if len(sys.argv) > 1 and sys.argv[1] == "config":
	print("graph_title 4CAT Posts scraped per hour")
	print("graph_args -l 0")
	print("graph_vlabel scraped")
	print("graph_category 4cat")
	print("graph_info The amount of posts scraped per hour")
	print("total.warning 500:20000")
	print("total.critical 250:30000")
	for platform in DATASOURCES:
		if "interval" not in DATASOURCES[platform]:
			continue
		print("platform-%s.label %s" % (platform, platform))
	print("total.label Total")
	sys.exit(0)

cutoff = int(time.time()) - 3600
queries = []
for platform in DATASOURCES:
	if "interval" not in DATASOURCES[platform]:
		continue
	queries.append("(SELECT COUNT(*) FROM posts_%s WHERE timestamp > %i) AS scraped_%s" % (platform, cutoff, platform))

connection = psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, host=DB_HOST, port=DB_PORT)
cursor = connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
query = "SELECT " + ", ".join(queries)

cursor.execute(query)
data = cursor.fetchone()

total = 0
for column in data.keys():
	total += int(data[column])
	platform = "_".join(column.split("_")[1:])
	print("platform-%s.value %i" % (platform, int(data[column])))

print("total.value %i" % total)