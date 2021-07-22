"""
Import 4chan data from 4plebs data dumps
"""
import argparse
import psycopg2
import json
import time
import sys
import csv
import re
import os
import pickle

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/..")
from common.lib.database import Database
from common.lib.logger import Logger


class FourPlebs(csv.Dialect):
	"""
	CSV Dialect as used in 4plebs database dumps - to be used with Python CSV functions
	"""
	delimiter = ","
	doublequote = False
	escapechar = "\\"
	lineterminator = "\n"
	quotechar = '"'
	quoting = csv.QUOTE_ALL
	skipinitialspace = False
	strict = True

	columns = ["num", "subnum", "thread_num", "op", "timestamp", "timestamp_expired", "preview_orig", "preview_w",
			   "preview_h", "media_filename", "media_w", "media_h", "media_size", "media_hash", "media_orig", "spoiler",
			   "deleted", "capcode", "email", "name", "trip", "title", "comment", "sticky", "locked", "poster_hash",
			   "poster_country", "exif"]


def sanitize(post):
	"""
	Sanitize post data

	:param dict post:  Post data, from a DictReader
	:return dict:  Post data, but cleaned and sanitized
	"""
	if isinstance(post, dict):
		return {key: sanitize(post[key]) for key in post}
	else:
		if isinstance(post, str):
			post = post.strip()
			post = post.replace("\\\\", "\\")

		if post == "N":
			post = ""

		return post


def commit(posts, post_fields, db, datasource, fast=False):
	if fast:
		post_fields_sql = ", ".join(post_fields)
		try:
			db.execute_many("INSERT INTO posts_" + datasource + " (" + post_fields_sql + ") VALUES %s", posts)
			db.commit()
		except psycopg2.IntegrityError as e:
			print(repr(e))
			print(e)
			sys.exit(1)

	else:
		db.execute("START TRANSACTION")
		for post in posts:
			db.insert("posts_" + datasource, data={post_fields[i]: post[i] for i in range(0, len(post))}, safe=True, commit=False)
		db.commit()


# set up
link_regex = re.compile(">>([0-9]+)")
post_fields = ("id", "timestamp", "timestamp_deleted", "thread_id", "body", "author",
			   "author_type_id", "author_trip", "subject", "country_name", "country_code", "image_file",
			   "image_4chan", "image_md5", "image_dimensions", "image_filesize",
			   "semantic_url", "unsorted_data")

# parse parameters
cli = argparse.ArgumentParser()
cli.add_argument("-i", "--input", required=True, help="CSV file to read from - should be a 4plebs data dump")
cli.add_argument("-b", "--board", required=True, help="What board the posts belong to, e.g. 'pol'")
cli.add_argument("-a", "--batch", type=int, default=1000000,
				 help="Size of post batches; every so many posts, they are saved to the database")
cli.add_argument("-s", "--skip", type=int, default=0, help="How many posts to skip")
cli.add_argument("-e", "--end", type=int, default=sys.maxsize,
				 help="At which post to stop processing. Starts counting at 0 (so not affected by --skip)")
cli.add_argument("-d", "--datasource", type=str, default="4chan", help="Data source ID")
cli.add_argument("-f", "--fast", default=False, type=bool,
				 help="Use batch queries instead of inserting posts individually. This is far faster than 'slow' mode, "
					  "but will crash if trying to insert a duplicate post, so it should only be used on an empty "
					  "database or when you're sure datasets don't overlap.")
args = cli.parse_args()

if not os.path.exists(args.input):
	print("File not found: %s" % args.input)
	sys.exit(1)

db = Database(logger=Logger(), appname="4chan-import")

print("Opening %s." % args.input)
if args.skip > 0:
	print("Skipping %i posts." % args.skip)

if args.fast:
	print("Fast mode enabled.")

with open(args.input, encoding="utf-8") as inputfile:
	postscsv = csv.DictReader(inputfile, fieldnames=FourPlebs.columns, dialect=FourPlebs)

	postbuffer = []
	threads = {}
	posts = 0
	skipped = 0

	for csvpost in postscsv:
		posts += 1

		if posts < args.skip:
			continue

		if posts >= args.end:
			break

		print("\rPost %s" % posts, end="")
		if int(csvpost["subnum"]) > 0:
			# skip ghost posts
			continue

		post = csvpost
		if post["thread_num"] not in threads:
			threads[post["thread_num"]] = {
				"timestamp": int(time.time()),
				"timestamp_modified": 0,
				"timestamp_archived": 0,
				"is_sticky": 0,
				"is_closed": 0,
				"post_last": 0
			}

		try:
			threads[post["thread_num"]]["post_last"] = max(threads[post["thread_num"]]["post_last"], int(post["num"]))
			threads[post["thread_num"]]["is_sticky"] = max(threads[post["thread_num"]]["is_sticky"],
														   int(post["sticky"]))
			threads[post["thread_num"]]["is_closed"] = max(threads[post["thread_num"]]["is_closed"],
														   1 if post["locked"] != "0" else 0)
			threads[post["thread_num"]]["timestamp_modified"] = max(threads[post["thread_num"]]["timestamp_modified"],
																	int(post["timestamp"]))
			threads[post["thread_num"]]["timestamp_archived"] = max(threads[post["thread_num"]]["timestamp_archived"],
																	int(post["timestamp_expired"]))
			threads[post["thread_num"]]["timestamp"] = max(threads[post["thread_num"]]["timestamp"],
														   int(post["timestamp"]))
		except ValueError:
			print(post)
			sys.exit(1)

		post_id = int(post["num"])
		postdata = (
			post["num"],  # id
			post["timestamp"],  # timestamp
			post["deleted"] if int(post["deleted"]) > 1 else 0,  # timestamp_deleted
			post["thread_num"],  # thread_id
			post["comment"],  # body
			post["name"],  # author
			post["capcode"],  # author_type_id
			post["trip"],  # author_trip
			post["title"],  # subject
			post["poster_country"],  # country_code
			post["media_filename"],  # image_file
			post["media_orig"],  # image_4chan
			post["media_hash"],  # image_md5
			json.dumps({"w": post["media_w"], "h": post["media_h"]}) if post["media_filename"] != "" else "",
			# image_dimensions
			post["media_size"],  # image_filesize
			"",  # semantic_url
			"{}"  # unsorted_data
		)
		postbuffer.append(postdata)

		# for speed, we only commit every so many posts
		if len(postbuffer) % args.batch == 0:
			print("\nCommitting posts %i-%i to database." % (posts - args.batch, posts))
			commit(postbuffer, post_fields, db, args.datasource, fast=args.fast)
			postbuffer = []

	# commit remainder
	print("\nSkipped %i post IDs that were already known." % skipped)
	print("Committing final posts.")
	commit(postbuffer, post_fields, db, args.datasource, fast=args.fast)

pickle.dump(threads, open("threads.p", "wb"))

# update threads
print("Updating threads.")
for thread_id in threads:
	thread = threads[thread_id]

	thread["id"] = thread_id
	thread["board"] = args.board
	thread["timestamp_scraped"] = -1
	thread["num_unique_ips"] = -1
	thread["num_replies"] = 0
	thread["num_images"] = 0

	thread["is_sticky"] = True if thread["is_sticky"] == 1 else False
	thread["is_closed"] = True if thread["is_closed"] == 1 else False
	exists = db.fetchone("SELECT * FROM threads_" + args.datasource + " WHERE id = %s", (thread_id,))

	if not exists:
		db.insert("threads_" + args.datasource, thread)

	else:
		if thread["timestamp"] < exists["timestamp"]:
			thread["is_sticky"] = exists["is_sticky"]
			thread["is_closed"] = exists["is_closed"]
		thread["post_last"] = max(int(thread.get("post_last") or 0), int(exists.get("post_last") or 0))
		thread["timestamp_modified"] = max(int(thread.get("timestamp_modified") or 0), int(exists.get("timestamp_modified") or 0))
		thread["timestamp_modified"] = max(int(thread.get("timestamp_archived") or 0), int(exists.get("timestamp_archived") or 0))
		thread["timestamp"] = min(int(thread.get("timestamp") or 0), int(exists.get("timestamp") or 0))

		db.update("threads_" + args.datasource, data=thread, where={"id": thread_id})

print("Updating thread statistics.")
db.execute(
	"UPDATE threads_" + args.datasource + " AS t SET num_replies = ( SELECT COUNT(*) FROM posts_" + args.datasource + " AS p WHERE p.thread_id = t.id) WHERE t.id IN %s",
	(tuple(threads.keys()),))
db.execute(
	"UPDATE threads_" + args.datasource + " AS t SET num_images = ( SELECT COUNT(*) FROM posts_" + args.datasource + " AS p WHERE p.thread_id = t.id AND image_file != '') WHERE t.id IN %s",
	(tuple(threads.keys()),))
