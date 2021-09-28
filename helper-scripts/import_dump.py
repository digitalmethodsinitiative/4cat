"""
Import 4chan data from Archived.moe csv dumps.

Several of these are downloadable here: https://archive.org/details/archivedmoe_db_201908

"""

import argparse
import json
import time
import csv
import sys
import os
import re

from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/..")
from common.lib.database import Database
from common.lib.logger import Logger

# parse parameters
cli = argparse.ArgumentParser()
cli.add_argument("-i", "--input", required=True, help="File to read from, containing a CSV dump")
cli.add_argument("-d", "--datasource", type=str, required=True, help="Datasource ID")
cli.add_argument("-b", "--board", type=str, required=True, help="Board name")
cli.add_argument("-s", "--skip_duplicates", type=str, required=True, help="If duplicate posts should be skipped (useful if there's already data in the table)")
cli.add_argument("-o", "--offset", type=int, required=False, help="How many rows to skip")
args = cli.parse_args()

if not Path(args.input).exists() or not Path(args.input).is_file():
	print("%s is not a valid folder name." % args.input)
	sys.exit(1)

logger = Logger()
db = Database(logger=logger, appname="queue-dump")

csvnone = re.compile(r"^N$")

safe = False
if args.skip_duplicates:
	print("Skipping duplicate rows (ON CONFLICT DO NOTHING).")
	safe = True

with open(args.input, encoding="utf-8") as inputfile:

	if args.board == "v":
		# The /v/ dump has slightly different columns
		fieldnames = ("doc_id", "media_id", "poster_ip", "num", "subnum", "thread_num", "op", "timestamp", "timestamp_expired", "preview_orig", "preview_w", "preview_h", "media_filename", "media_w", "media_h", "media_size", "media_hash", "media_orig", "spoiler", "deleted", "capcode", "email", "name", "trip", "title", "comment", "delpass", "sticky", "locked", "poster_hash", "poster_country", "exif")
	else:
		fieldnames = ("num", "subnum", "thread_num", "op", "timestamp", "timestamp_expired", "preview_orig", "preview_w", "preview_h", "media_filename", "media_w", "media_h", "media_size", "media_hash", "media_orig", "spoiler", "deleted", "capcode", "email", "name", "trip", "title", "comment", "sticky", "locked", "poster_hash", "poster_country", "exif")
	reader = csv.DictReader(inputfile, fieldnames=fieldnames, doublequote=False, escapechar="\\", strict=True)
	
	# Skip header
	next(reader, None)

	posts = 0
	threads = {}
	duplicates = 0

	# Show status
	if args.offset:
		print("Skipping %s rows." % args.offset)

	for post in reader:

		post = {k: csvnone.sub("", post[k]) if post[k] else None for k in post}

		# We collect thread data first, even though we might skip this post
		if post["thread_num"] not in threads:
			threads[post["thread_num"]] = {
				"id": post["thread_num"],
				"board": args.board,
				"timestamp": 0,
				"timestamp_scraped": int(time.time()),
				"timestamp_modified": 0,
				"num_unique_ips": -1,
				"num_images": 0,
				"num_replies": 0,
				"limit_bump": False,
				"limit_image": False,
				"is_sticky": False,
				"is_closed": False,
				"post_last": 0
			}
		
		if post["op"] == "1":
			threads[post["thread_num"]]["timestamp"] = post["timestamp"]
			threads[post["thread_num"]]["is_sticky"] = post["sticky"] == "1"
			threads[post["thread_num"]]["is_closed"] = post["locked"] == "1"

		if post["media_filename"]:
			threads[post["thread_num"]]["num_images"] += 1

		threads[post["thread_num"]]["num_replies"] += 1
		threads[post["thread_num"]]["post_last"] = post["num"]
		threads[post["thread_num"]]["timestamp_modified"] = post["timestamp"]

		posts += 1
		
		# Skip rows if needed. Can be useful when importing didn't go correctly.
		if args.offset and posts < args.offset:
			continue
		
		
		if post["media_filename"] and len({"media_w", "media_h", "preview_h", "preview_w"} - set(post.keys())) == 0:
			dimensions = {"w": post["media_w"], "h": post["media_h"], "tw": post["preview_w"], "th": post["preview_h"]}
		else:
			dimensions = {}

		if post["subnum"] != "0":
			# ghost post
			continue

		post_data = {
			"id": post["num"],
			"board": args.board,
			"thread_id": post["thread_num"],
			"timestamp": post["timestamp"],
			"subject": post.get("title", ""),
			"body": post.get("comment", ""),
			"author": post.get("name", ""),
			"author_trip": post.get("trip", ""),
			"author_type": post["id"] if "id" in post else "",
			"author_type_id": post["capcode"] if post["capcode"] != "" else "N",
			"country_name": "",
			"country_code": post.get("poster_country", ""),
			"image_file": post["media_filename"],
			"image_4chan": post["media_orig"],
			"image_md5": post.get("media_hash", ""),
			"image_filesize": post.get("media_size", 0),
			"image_dimensions": json.dumps(dimensions)
		}

		post_data = {k: str(v).replace("\x00", "") for k, v in post_data.items()}
		new_id = db.insert("posts_4chan", post_data, commit=False, safe=safe, return_field="id_seq")

		if post["deleted"] != "0":
			db.insert("posts_4chan_deleted", {"id_seq": new_id, "timestamp_deleted": post["deleted"]})

		if posts > 0 and posts % 10000 == 0:
			print("Committing %i - %i post " % (posts - 10000, posts), end="")
			db.commit()

			# Commit threads that are at least two months older than the last encountered post. We use this gap to ensure thread data is up-to-date, even if the archive is only roughly ordered by time.
			# We do it this way to prevent RAM hogging.
			threads_added = set()
			for thread in threads.values():
				if (int(post["timestamp"]) - int(thread["timestamp_modified"])) > 5259487:
					db.insert("threads_4chan", data=thread, commit=False, safe=safe)
					threads_added.add(thread["id"])
			print("and %i threads" % len(threads_added), end="")
			for thread_added in threads_added:
				threads.pop(thread_added)
			print(" (%i threads waiting to commit)" % len(threads))
			db.commit()

	# Add the last threads as well
	print("Adding leftover threads")
	for thread in threads.values():
		db.insert("threads_4chan", data=thread, commit=False, safe=safe)

	db.commit()

print("Done")