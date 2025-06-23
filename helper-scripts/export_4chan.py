"""

This scripts converts the 4chan data from a 4CAT database
to be exported to a JSON or CSV file.

JSON dumps can be directly imported to Webjutter. 

It exports most data as-is, but also makes some changes.
- Thread data will not be stored in a different table, but as fields of an OP object.
- Deleted post data will be indicated by a 'deleted' field in a post object.
---- Posts in sticky threads will no longer be marked as deleted.
- The keys will be translated to reflect the 4chan API.
- Timestamp validity will be checked because data from the 4plebs dump features incorrect timezone data.
- Missed sticky posts will be marked as such. 
- Some posts that were incorrectly marked as deleted will be reverted and stored as undeleted.
- Homogenise the `author_type_id` so that variations like 'M' and 'mod' are the same.

- correct thread timestamps
- correct number of posts in threads
- correct number of images in threads

"""

import argparse
import json
import csv
import sys
import os
import re

from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/..")
from common.lib.database import Database
from common.lib.logger import Logger
from common.config_manager import config

valid_boards = ("a","b","c","d","e","f","g","gif","h","hr","k","m","o","p","r","s","t",
			"u","v","vg","vm","vmg","vr","vrpg","vst","w","wg","i","ic","r9k","s4s",
			"vip","qa","cm","hm","lgbt","y","3","aco","adv","an","bant","biz","cgl"
			"ck","co","diy","fa","fit","gd","hc","his","int","jp","lit","mlp","mu",
			"n","news","out","po","pol","pw","qst","sci","soc","sp","tg","toy","trv",
			"tv","vp","vt","wsg","wsr","x","xs")

# parse parameters
cli = argparse.ArgumentParser()
cli.add_argument("-o", "--output", required=True, help="JSON or csv file to write to.")
cli.add_argument("-b", "--board", type=str, required=False, help="Board name(s) (separate with comma). If not given, export all available boards.")
cli.add_argument("-c", "--itersize", type=int, required=False, default=100000, help="Iteration size with which to retrieve data from the database.")
cli.add_argument("-d", "--skip_deleted", type=bool, required=False, default=False, help="Whether to skip deleted posts.")

args = cli.parse_args()

if args.output.lower().endswith(".json"):
	filetype = "json"
elif args.output.lower().endswith(".csv"):
	filetype = "csv"
else:
	print("Please provide a valid file type (.csv or .json).")
	sys.exit(1)

# Headers for csv writing
headers =  ("num","resto","board","sub","com","time","time_utc","name","deleted","deleted_on","replies_to","id","capcode","tripcode","filename","tim","md5","w","h","tw","th","fsize","country","country_name","op","replies","images","semantic_url","sticky","closed","archived_on","scraped_on","modified_on","unique_ips","bumplimit","imagelimit","index_positions","unsorted_data")

# Check board validity
if args.board:
	boards = [b.strip().lower() for b in args.board.split(",")]

	for b in boards:
		if b not in valid_boards:
			print("%s is not a valid 4chan board name. Please try again." % b)
			sys.exit(1)

	board_sql = "board IN (" + ",".join(["'" + b + "'" for b in boards]) + ")"

	print("Exporting posts for " + ", ".join(boards) + ".")

else:
	board_sql = "1=1"
	boards = []
	print("Exporting posts for all boards in the database.")

skip_deleted = bool(args.skip_deleted)
if skip_deleted:
	print("Skipping posts that are marked as deleted.")

itersize = int(args.itersize)

# Connect to database
logger = Logger()
db = Database(logger=logger, appname="4chan-export", dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD, host=config.DB_HOST, port=config.DB_PORT)

print("Exporting to %s" % args.output)

# Get min and max thread IDs to query in batches and know when we're done
print("Getting upper and lower boundaries of thread IDs.")
min_thread_id = db.fetchone("SELECT min(id) FROM threads_4chan WHERE %s " % board_sql)["min"]
max_thread_id = db.fetchone("SELECT max(id) FROM threads_4chan WHERE %s " % board_sql)["max"]

def get_posts(min_id, itersize):
	"""
	Returns posts and their timestamp deletion.
	We do this in batches for memory and speed reasons.
	We query full threads so we can write these in their entirety.
	Ordering by thread IDs is crucial for correctly keeping track of data.
	"""
	query = """	SELECT p.*, p_d.timestamp_deleted FROM posts_4chan AS p
				LEFT JOIN posts_4chan_deleted AS p_d ON p.id_seq = p_d.id_seq
				WHERE (thread_id >= %i AND thread_id < %i) AND %s
				ORDER BY board, thread_id, id""" % (min_id, min_id + itersize, board_sql)
	posts = db.fetchall(query)
	return posts

count = 0

with open(args.output, "w", newline="", encoding="utf-8") as out_file:

	# Write headers if we're making a csv file
	if filetype == "csv":
		writer = csv.DictWriter(out_file, fieldnames=headers)
		writer.writeheader()

	print("Iterating through threads...")

	# Loop through all the database posts
	while True:

		if min_thread_id > max_thread_id:
			break

		posts = get_posts(min_thread_id, itersize=itersize)
		min_thread_id = min_thread_id + itersize
		thread_data = []

		for row in posts:

			count += 1
			post = {}

			# Fetch thread data for every new OP
			if row["id"] == row["thread_id"]:

				# If we still have thread data stored,
				# Write away all the old posts first.
				if thread_data:
					for p in thread_data:
						if filetype == "json":
							out_file.write(json.dumps(p) + "\n")
						if filetype == "csv":
							writer.writerow(p)
				thread_data = []
				thread_deleted = False

				# Get thread info from the threads_4chan table
				op_db = db.fetchone("SELECT * FROM threads_4chan WHERE id_seq = %i" % row["id_seq"])

				# Set required OP data
				post = {
					"sub": row["subject"] if row["subject"] is not None else "",
					"replies": 0,
					"images": 0,
					"op": True,
					"semantic_url": row["semantic_url"] if row["semantic_url"] is not None else ""
				}

				# Set optional OP data
				if op_db:
					if op_db["is_sticky"]:
						post["sticky"] = True
					if op_db["is_closed"]:
						post["closed"] = True
					if op_db["timestamp_archived"] > 0:
						post["archived_on"] = op_db["timestamp_archived"]
					if op_db["timestamp_scraped"] > 0:
						post["scraped_on"] = op_db["timestamp_scraped"]
					if op_db["timestamp_modified"] > 0:
						post["modified_on"] = op_db["timestamp_modified"]
					if op_db["num_unique_ips"] > 0:
						post["unique_ips"] = op_db["num_unique_ips"]
					if op_db["limit_bump"]:
						post["bumplimit"] = op_db["limit_bump"]
					if op_db["limit_image"]:
						post["imagelimit"] = op_db["limit_image"]
					if op_db["index_positions"]:
						post["index_positions"] = op_db["index_positions"]

					# Keep track of whether the OP is deleted
					# so we can also mark its replies as deleted.
					# We do not consider removed sticky threads as deleted.
					if (row["timestamp_deleted"] and row["timestamp_deleted"] > 0) and not post.get("is_sticky"):
						post["deleted"] = True
						post["deleted_on"] = row["timestamp_deleted"]
						thread_deleted = True

			# Set the post's deletion timestamp.
			# If this post has no deletion timestamp, but the OP does,
			# set the post's deletion timestamp to that of the OP.
			deleted = True if (row["timestamp_deleted"] and row["timestamp_deleted"] > 0) and not post.get("op") else False
			if (deleted or thread_deleted) and row["id"] != row["thread_id"]:
				post["deleted"] = True
				if not skip_deleted: # Deleted OP data might have been skipped, so we maybe can't get data from `thread_data`
					post["deleted_on"] = row["timestamp_deleted"] if (row["timestamp_deleted"] and row["timestamp_deleted"] > 0) else thread_data[0]["deleted_on"]

			# Skip deleted posts, if indicated
			if skip_deleted and post.get("deleted"):
				continue

			# Set required non OP-specific data
			post["num"] = row["id"]
			post["resto"] = row["thread_id"]
			post["board"] = row["board"]
			post["com"] = row["body"] if row["body"] is not None else ""
			post["time"] = row["timestamp"]
			post["time_utc"] = datetime.strftime(datetime.utcfromtimestamp(row["timestamp"]), "%Y-%m-%d %H:%M:%S")
			post["name"] = row.get("author", "")
			
			# Extract the IDs of posts that this post is replying directly to
			if row["body"] and ">>" in row["body"]:
				replies_to = ",".join(re.findall(r"[>]{2,3}[0-9]{1,15}", row["body"]))
				if replies_to:
					post["replies_to"] = replies_to

			# Set non-required, non-OP specific data
			if row["author_type"]:
				post["id"] = row["author_type"] # The per-thread ID of posters (not always set)
			if row["author_type_id"]:
				# Specific roles, like 'mod'.
				# Do some converstion to homogenise old and new notations.
				author_type_id = row["author_type_id"]
				if author_type_id == "M":
					author_type_id = "mod"
				if author_type_id == "A":
					author_type_id = "admin"
				if author_type_id == "G":
					author_type_id = "manager"
				if author_type_id == "V":
					author_type_id = "verified"
				post["capcode"] = row["author_type_id"]
			if row["author_trip"]:
				post["tripcode"] = row["author_trip"]

			# Image data
			if row["image_file"]:
				post["filename"] = row["image_file"]
			if row["image_4chan"]:
				post["tim"] = row["image_4chan"]
			if row["image_url"]:
				post["file_url"] = row["image_url"]
			if row["image_md5"]:
				post["md5"] = row["image_md5"]
			if row["image_dimensions"]:
				# Reconvert these to 4chan API data
				img_data = json.loads(row["image_dimensions"])
				post["w"] = img_data.get("w", 0)
				post["h"] = img_data.get("h", 0)
				post["tw"] = img_data.get("tw", 0)
				post["th"] = img_data.get("th", 0)
			if row["image_filesize"]:
				post["fsize"] = row["image_filesize"]

			# Country flags.
			# These are slightly different than the 4chan API;
			# 'meme flags' and IP-based 'geo flags' are mixed here.
			# The codes for 'meme flag' will have a 't_' prepended
			# to differentiate them from country codes.
			if row["country_code"]:
				post["country"] = row["country_code"]
			if row["country_name"]:
				post["country_name"] = row["country_name"]

			if row["unsorted_data"] and row["unsorted_data"] != "{}":
				post["unsorted_data"] = row["unsorted_data"]

			# For replies, update OP data
			if row["id"] != row["thread_id"]:
				if thread_data and thread_data[0].get("op"):
					thread_data[0]["replies"] += 1
					if row["image_file"]:
						thread_data[0]["images"] += 1
			
			thread_data.append(post)

			# Keep the people updated
			if count % 100000 == 0:
				print("Wrote %s lines " % count)

		# Write leftover thread data
		if thread_data:
			for p in thread_data:
				if filetype == "json":
					out_file.write(json.dumps(p) + "\n")
				if filetype == "csv":
					writer.writerow(p)
			thread_data = []

	db.close()

print("Finished! Written %s posts to %s." % (count, args.output))