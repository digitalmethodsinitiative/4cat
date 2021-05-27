"""
Insert Usenet posts into 4CAT database

Uses an SQLite database with Usenet posts as its source. This database can
created from original Usenet mail files with the following script:

https://github.com/stijn-uva/usenet-import
"""
import argparse
import sqlite3
import time
import sys
import os

from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/..")
from common.lib.database import Database
from common.lib.logger import Logger

cli = argparse.ArgumentParser()
cli.add_argument("--input", "-i", help="SQLite database file to use as input", required=True)
cli.add_argument("--limit", "-l", help="Amount of posts to import (default: import all)", default=0)
cli.add_argument("--truncate", "-t", help="Truncate database before adding new posts (default: true)", default=True)

args = cli.parse_args()
args.truncate = bool(args.truncate)
limit = int(args.limit)

sourcefile = Path(args.input)
if not sourcefile.exists():
	print("The file %s does not exist" % sourcefile)
	exit(1)

dbconn = sqlite3.connect(args.input)
dbconn.row_factory = sqlite3.Row
cursor = dbconn.cursor()

db = Database(logger=Logger())
db.execute(open("database.sql").read())
if args.truncate:
	db.execute("TRUNCATE posts_usenet")
	db.execute("TRUNCATE threads_usenet")
	db.execute("TRUNCATE groups_usenet")
db.commit()

post_to_threads = {}
posts = cursor.execute("SELECT * FROM postsdata")

print("Loading posts....")
done = 0
while posts:
	post = posts.fetchone()
	if not post or (limit and done > limit):
		break

	post = dict(post)
	headers = post.get("headers", "").split("\n")
	headers = {header.split(":")[0].strip(): ":".join(header.split(":")[1:]).strip() for header in headers}
	key = "References" if "references" not in headers else "references"

	references = [ref.strip() for ref in headers.get(key, "").split(" ") if ref.strip() and ref.strip() != "<>"]
	if not references:
		done += 1
		post_to_threads[post["msgid"]] = {post["msgid"]}
		continue

	post_to_threads[post["msgid"]] = set(references)

	done += 1
	if done % 5000 == 0:
		print("Loaded %i posts..." % done)

print("Reducing thread references...")
while True:
	num_reduced = 0

	for post in post_to_threads:
		if post_to_threads[post] == [post]:
			continue

		reduced = set()
		for reference in post_to_threads[post]:
			if reference in post_to_threads \
				and len(post_to_threads[reference]) == 1 \
				and reference not in post_to_threads[reference]:
				reduced.add(list(post_to_threads[reference])[0])
				num_reduced += 1
			else:
				reduced.add(reference)

		post_to_threads[post] = reduced

	if num_reduced == 0:
		break
	else:
		print("Reduced %i references in this iteration." % num_reduced)

print("Thread links reduced. Ready to add posts to 4CAT database.")
print("Fetching post data from SQLite...")
posts = cursor.execute("SELECT p.*, d.*, ( SELECT GROUP_CONCAT(\"group\") FROM postsgroup AS g WHERE g.msgid = p.msgid ) AS groups FROM posts AS p LEFT JOIN postsdata AS d ON p.msgid = d.msgid")
threads = {}
done = 0
while True:
	print("Processing posts %i-%i..." % (done, done + 5000))
	many = posts.fetchmany(5000)
	if not many:
		break

	for post in many:
		if not post or (limit and done > limit):
			break

		thread_id = list(post_to_threads[post["msgid"]])[0]

		postdata = {
			"id": post["msgid"].replace("\x00", ""),
			"thread_id": thread_id,
			"timestamp": post["timestamp"],
			"subject": post["subject"].replace("\x00", ""),
			"author": post["from"].replace("\x00", ""),
			"body": post["message"].replace("\x00", ""),
			"headers": post["headers"].replace("\x00", ""),
			"groups": post["groups"]
		}

		db.insert("posts_usenet", postdata, commit=False)
		for group in post["groups"].split(","):
			if group:
				db.insert("groups_usenet", {"post_id": post["msgid"], "group": group}, commit=False)

		if thread_id not in threads:
			threads[thread_id] = {"timestamp": time.time(), "num_replies": 0, "post_last": "", "post_first": "", "post_last_timestamp": 0 - time.time(), "post_first_timestamp": time.time()}
			db.insert("threads_usenet", {
				"id": thread_id,
				"board": "",
				"timestamp": 0,
				"num_replies": 0,
				"post_last": "",
				"post_first": ""
			}, commit=False)

		threads[thread_id]["num_replies"] += 1
		threads[thread_id]["timestamp"] = min(threads[thread_id]["timestamp"], post["timestamp"])
		if post["timestamp"] < threads[thread_id]["post_first_timestamp"]:
			threads[thread_id]["post_first"] = post["msgid"]
			threads[thread_id]["post_first_timestamp"] = post["timestamp"]

		if post["timestamp"] > threads[thread_id]["post_last_timestamp"]:
			threads[thread_id]["post_last"] = post["msgid"]
			threads[thread_id]["post_last_timestamp"] = post["timestamp"]

		done += 1

	db.commit()
	if limit and done > limit:
		break

print("Updating thread metadata...")
db.commit()
for thread_id, data in threads.items():
	del data["post_last_timestamp"]
	del data["post_first_timestamp"]

	db.update("threads_usenet", data=data, where={"id": thread_id}, commit=False)

print("Committing thread updates to database...")
db.commit()

print("Done!")
