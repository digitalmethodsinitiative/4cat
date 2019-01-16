# Import the dump supplied by qanon.news into the 8chan corpus database
# The dump is a combination of 4chan and 8chan posts, but it's more useful to
# have them available in one place, and 8chan makes sense there as the new
# "home" of Q

import argparse
import psycopg2
import glob
import json
import sys
import os
import re

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/..")
from lib.logger import Logger
from lib.database import Database

# parse parameters
cli = argparse.ArgumentParser()
cli.add_argument("-f", "--folder", required=True, help="Path to folder containing QAnon data dump (as JSON files)")
cli.add_argument("-s", "--skip", default=0, help="Files to skip")
args = cli.parse_args()

# set up
db = Database(logger=Logger())
db.commit()
link_regex = re.compile(">>([0-9]+)")

# Look for the JSON files
os.chdir(args.folder)
files = sorted(glob.glob("*.json"))
files = files[int(args.skip):]
print("Resetting sequence counters...")
thread_seq = db.fetchone("SELECT COUNT(*) AS num FROM threads_8chan WHERE board LIKE 'qanon-%'")["num"]
post_seq = db.fetchone("SELECT COUNT(*) AS num FROM posts_8chan WHERE thread_id IN ( SELECT id FROM threads_8chan WHERE board LIKE 'qanon-%' )")["num"]
imported = 0

# read files sequentially
for file in files:
	threadbuffer = []
	imported += 1

	# each JSON file is a separate thread (probably?)
	with open(file, "rb") as thread:
		print("Importing %s (%s)" % (file, imported))
		postbuffer = []

		# not everything is encoded the same way, which is super annoying
		raw_json = thread.read()
		try:
			posts = json.loads(raw_json.decode("utf-8"))
		except UnicodeDecodeError:
			posts = json.loads(raw_json.decode("windows-1252"))

		# thread data template (will be amended later)
		thread_seq += 1
		thread_data = {
			"id": thread_seq,
			"board": "qanon",
			"platform": "8chan",
			"timestamp": 0,
			"timestamp_scraped": 0,
			"timestamp_deleted": 0,
			"timestamp_modified": 0,
			"post_last": 0,
			"num_unique_ips": -1,
			"num_replies": -1,
			"num_images": -1,
			"limit_bump": False,
			"limit_image": False,
			"is_sticky": False,
			"is_closed": False
		}

		# these are also updated further down the line
		thread_source = ""
		thread_last_timestamp = 0

		# first collect all posts - these may be nested
		for post in posts:
			postbuffer.append(post)
			if "references" in post:
				for reference in post["references"]:
					postbuffer.append(reference)

		# now parse them one by one
		posts_parsed = []
		for post in postbuffer:
			if "source" in post and post["source"]:
				thread_source = post["source"]

			timestamp = post["last_modified"]
			thread_data["timestamp"] = min(timestamp, thread_data["timestamp"])
			thread_data["timestamp_modified"] = max(timestamp, thread_data["timestamp_modified"])

			if thread_last_timestamp < timestamp:
				thread_last_timestamp = timestamp
				thread_data["post_last"] = post["no"]

			# determine whether enough image data is available to save something
			has_image = "tim" in post and post["tim"] and post["ext"] and post["md5"]
			if has_image:
				if "w" in post:
					dimensions = {"w": post["w"], "h": post["h"], "tw": post["tn_w"], "th": post["tn_h"]}
				else:
					dimensions = {"w": post["tn_w"], "h": post["tn_h"], "tw": post["tn_w"], "th": post["tn_h"]}
			else:
				dimensions = ""

			# collect all post data - the ID is faked but this is necessary since we have posts
			# from multiple forums in here, so there may be ID clashes if we use the original one
			post_id = "q-%s-%s" % (post["no"], post_seq)
			posts_parsed.append({
				"id": post_id,
				"thread_id": "q%s" % thread_seq,
				"timestamp": timestamp,
				"timestamp_deleted": 0,
				"subject": str(post["sub"]).replace("\x00", "") if "sub" in post and post["sub"] else "",
				"body": str(post["com"]).replace("\x00", "") if post["com"] else str(post["text"]).replace("\x00", ""),
				"author": str(post["name"]).replace("\x00", ""),
				"author_type": "",
				"author_type_id": "",
				"author_trip": str(post["trip"]).replace("\x00", "") if "trip" in post else "",
				"country_code": "",
				"country_name": "",
				"image_file": post["filename"].replace("\x00", "") + post["ext"].replace("\x00",
																						 "") if has_image else False,
				"image_4chan": post["tim"].replace("\x00", "") + post["ext"].replace("\x00",
																					 "") if has_image else False,
				"image_md5": post["md5"].replace("\x00", "") if has_image else False,
				"image_dimensions": json.dumps(dimensions) if has_image else "",
				"image_filesize": post["fsize"] if has_image else 0,
				"semantic_url": "",
				"unsorted_data": ""
			})
			post_seq += 1

		# see whether we can know where the thread came from
		if thread_source == "":
			thread_source = "unknown"

		thread_data["board"] += "-%s" % thread_source

		# count images and replies in the thread
		images = 0
		for post in posts_parsed:
			if post["image_md5"]:
				images += 1
			thread_data["num_replies"] += 1

			mentioned_posts = []
			if not post["body"]:
				continue

		# update or create a record for the thread this file represents
		try:
			db.insert("threads_8chan", thread_data)
		except psycopg2.IntegrityError:
			db_thread = db.fetchone("SELECT * FROM threads_8chan WHERE id = %s" % (thread_data["id"]))
			db.update("threads_8chan", where={"id": thread_data["id"]}, data={
				"post_last": max(thread_data["post_last"], db_thread["post_last"]),
				"timestamp": min(thread_data["timestamp"], db_thread["timestamp"]),
				"timestamp_modified": max(thread_data["timestamp_modified"], db_thread["timestamp_modified"])
			})

		# finally, insert the posts
		for post in posts_parsed:
			db.insert("posts_8chan", post, safe=True)


# update counters and IDs so everything is consistent
db.query("UPDATE threads_8chan SET id = CONCAT('q', id) WHERE id NOT LIKE 'q%' AND board LIKE 'qanon-%'")
db.query("UPDATE threads_8chan SET post_last = CONCAT('q', post_last) WHERE post_last NOT LIKE 'q%' AND board LIKE 'qanon-%'")
db.query("UPDATE threads_8chan SET id = CONCAT('q', id) WHERE id NOT LIKE 'q%' AND board LIKE 'qanon-%'")
db.query("UPDATE threads_8chan AS threads SET num_replies = ( SELECT COUNT(*) FROM posts_8chan WHERE thread_id = threads.id )")
db.query("UPDATE threads_8chan AS threads SET num_images = ( SELECT COUNT(*) FROM posts_8chan WHERE thread_id = threads.id AND image_md5 IS NOT NULL )")

# fin
db.commit()