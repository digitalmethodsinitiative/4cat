"""

Script to add the 4archived SQLite dump to the 4CAT 4chan datasets.

Downloadable here: https://archive.org/download/4archive/4archive_dump-sqlite.7z

This contains old data (2014 and 2015) from:

/b/ (21832 threads), /a/ (11260 threads), /v/ (5855 threads), /mu/ (4457 threads), /fa/ (2483 threads), /g/ (2188 threads), /pol/ (906 threads), /s/ (793 threads), /co/ (719 threads), /m/ (626 threads), /vg/ (567 threads), /x/ (448 threads), /fit/ (439 threads), /k/ (422 threads), /vp/ (368 threads), /int/ (327 threads), /mlp/ (321 threads), /d/ (286 threads), /tv/ (282 threads), /h/ (264 threads), /soc/ (222 threads), /tg/ (221 threads), /hc/ (195 threads), /trv/ (187 threads), /e/ (169 threads), /w/ (164 threads), /t/ (158 threads), /sp/ (158 threads), /lit/ (142 threads), /sci/ (126 threads), /hm/ (126 threads), /r/ (121 threads), /toy/ (110 threads), /jp/ (70 threads), /adv/ (63 threads), /o/ (57 threads), /out/ (54 threads), /lgbt/ (52 threads), /c/ (50 threads), /ck/ (46 threads), /y/ (45 threads), /ic/ (41 threads), /diy/ (39 threads), /u/ (35 threads), /qa/ (30 threads), /cgl/ (27 threads), /biz/ (26 threads), /vr/ (22 threads), /i/ (21 threads), /n/ (13 threads), /cm/ (12 threads), /asp/ (12 threads), /an/ (12 threads), and /po/ (5 threads).

"""

import sys
import os
import sqlite3
import argparse
import json
import time

from datetime import datetime, timezone
from pathlib import Path
from psycopg2.errors import UniqueViolation

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/..")
from common.lib.database import Database
from common.lib.logger import Logger

# parse parameters
cli = argparse.ArgumentParser()
cli.add_argument("-i", "--input", required=True, help="File to read from, containing a SQLite archive")
cli.add_argument("-d", "--datasource", type=str, required=True, help="Datasource ID")
cli.add_argument("-t", "--threads_table", type=str, required=True, help="Name of SQLite table containing threads.")
cli.add_argument("-p", "--posts_table", type=str, required=True, help="Name of the SQLite table containing posts.")
cli.add_argument("-b", "--board", type=str, required=True, help="Board name")
args = cli.parse_args()


if not Path(args.input).exists() or not Path(args.input).is_file():
	print("%s is not a valid folder name." % args.input)
	sys.exit(1)

logger = Logger()
db = Database(logger=logger, appname="queue-dump")

seen_post_ids = set()

# Columns from 4archive dumps
posts_columns = ["id", "chan_id", "threads_id", "chan_image_name", "image_size", \
"image_dimensions", "thumb_dimensions", "image_url", "original_image_name", "subject", \
 "name", "chan_user_id", "tripcode", "capcode", "chan_post_date", "body", "available"]
threads_columns = ["id", "thread_id", "board", "archive_date", "update_date", "user_ips", \
"times_updated", "views", "admin_note", "secret", "available", "alive", "takedown_reason", \
"busy", "tweeted"]

conn = sqlite3.connect(args.input)
print("Connected to SQLite database.")

count = 0
skipped = 0
threads_skipped = 0

# To loop
c = conn.cursor()

# Some conversion errors happen for image file names,
# so treat everything as a regular string and encode
# subjects and bodies after.
conn.text_factory = bytes

c.execute("SELECT * FROM %s" % args.posts_table)

threads = {}
posts = []

print("Collecting and converting post and thread data.")

# Loop through all rows
for post in c:

	# Convert tuple to row to make things easier
	post = {posts_columns[i]: item for i, item in enumerate(post)}

	# Encoding shizzle. The dump itself seems to be malformed, so not all is perfect.
	post = {k: (v.decode("latin-1").encode("utf-8").decode("utf-8") if isinstance(v, bytes) else v) for k, v in post.items()}

	# The 4archive post table includes a thread id,
	# but this starts with 0 and increases from there.
	# The threads table does have the 4chan-corresponding
	# thread id, so retrieve it from there.
	c2 = conn.cursor()
	c2.execute("SELECT * FROM threads WHERE id = %s" % post["threads_id"])
	thread = c2.fetchone()

	if thread:
		thread = {threads_columns[i]: item for i, item in enumerate(thread)}
		thread = {k: (v.decode("latin-1").encode("utf-8").decode("utf-8") if isinstance(v, bytes) else v) for k, v in thread.items()}
		chan_thread_id = int(thread["thread_id"])
	
	# The thread data includes the board of the thread.
	# If this doesn't correspond with the user input, skip this post.
	# Also skip if the threads data do not appear in the threads table.
	if not thread or thread["board"] != args.board:
		skipped += 1
		if not thread:
			threads_skipped += 1
		continue

	seen_post_ids.add(post["id"])

	# Image dimensions
	if post["thumb_dimensions"]:
		tw, th = post["thumb_dimensions"].split("x")
		image_dimensions = {"tw": tw, "th": th}

		# Image dimensions don't always occur
		if post["image_dimensions"]:
			w, h = post["image_dimensions"].split("x")
			image_dimensions["w"] = w
			image_dimensions["h"] = h
		else:
			image_dimensions["w"] = tw
			image_dimensions["h"] = th
	else:
		image_dimensions = {}
	
	# Timestamp conversion
	date = datetime.strptime(post["chan_post_date"][:19], "%Y-%m-%d %H:%M:%S")
	timestamp = int(date.replace(tzinfo=timezone.utc).timestamp())
	
	post_data = {
		"id": post["chan_id"],
		"board": args.board,
		"thread_id": chan_thread_id,
		"timestamp": timestamp,
		"subject": post.get("subject", ""),
		"body": post.get("body", ""),
		"author": post.get("name", ""),
		"author_trip": post.get("tripcode", ""),
		"author_type": post["chan_id"] if "chan_id" in post else "",
		"author_type_id": post["capcode"] if post["capcode"] != "" else "N",
		"country_name": "", # Not available in this dump
		"country_code": "", # Not available in this dump
		"image_file": post["original_image_name"],
		"image_4chan": post["chan_image_name"],
		"image_url": post.get("image_url"),
		"image_md5": post.get("media_hash", ""),
		"image_filesize": post.get("image_size", 0),
		"image_dimensions": json.dumps(image_dimensions),
	}

	if chan_thread_id not in threads:
		threads[chan_thread_id] = {
			"id": chan_thread_id,
			"board": args.board,
			"timestamp": 0,
			"timestamp_archived": int(time.time()),
			"timestamp_scraped": 0,
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
	
	# If this is the OP, retrieve and add the thread data.
	if int(post["chan_id"]) == int(chan_thread_id):

		# Timestamp stuff
		threads[chan_thread_id]["timestamp"] = timestamp # Date of OP post

		scraped_date = datetime.strptime(post["chan_post_date"][:19], "%Y-%m-%d %H:%M:%S")
		scraped_timestamp = int(scraped_date.replace(tzinfo=timezone.utc).timestamp())
		threads[chan_thread_id]["timestamp_scraped"] = scraped_timestamp

		if thread["update_date"]:
			modified_date = datetime.strptime(thread["update_date"][:19], "%Y-%m-%d %H:%M:%S")
			modified_timestamp = int(modified_date.replace(tzinfo=timezone.utc).timestamp())

			threads[chan_thread_id]["timestamp_modified"] = modified_timestamp
	
	threads[chan_thread_id]["num_replies"] += 1

	if post_data["image_4chan"]:
		threads[chan_thread_id]["num_images"] += 1

	if timestamp > threads[chan_thread_id]["post_last"]:
		threads[chan_thread_id]["post_last"] = timestamp

	post_data = {k: str(v).replace("\x00", "") for k, v in post_data.items()}

	try:
		new_id = db.insert("posts_4chan", post_data, commit=False, safe=False, return_field="id_seq")
	except UniqueViolation:
		print("Duplicate post with id %s in the SQLite dump, skipping." % post_data["id"])
		db.rollback()
		post_data = {}
		continue

	# Add to the database!
	if count > 0 and count % 10000 == 0:
		print("Committing post %i - %i)" % (count - 10000, count))
		db.commit()
	count += 1

db.commit()

nthreads = 0
for thread in threads.values():
	db.insert("threads_4chan", data=thread, commit=False, safe=False)
	if nthreads > 0 and nthreads % 10000 == 0:
		print("Committing threads %i - %i" % (nthreads - 10000, nthreads))
		db.commit()
	nthreads += 1

db.commit()

print("Done - added %i posts from %s to the 4CAT 4chan dataset" % (count, args.board,))
print("Skipped %i posts from the dump that belonged to other boards." % skipped)
print("(%i posts skipped because their thread data wasn't available)" % threads_skipped)

quit()