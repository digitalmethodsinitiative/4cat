"""
Import 4chan data from 4plebs data dumps
"""
import argparse
import psycopg2
import json
import time
import sys
import csv
import json
import re
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/..")
from common.lib.database import Database
from common.lib.logger import Logger
from chan_flags import get_country_name, get_troll_names


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
	posts_added = 0
	
	if fast:
		post_fields_sql = ", ".join(post_fields)
		try:
			db.execute_many("INSERT INTO posts_" + datasource + " (" + post_fields_sql + ") VALUES %s", replacements=posts)
			db.commit()
		except psycopg2.IntegrityError as e:
			print(repr(e))
			print(e)
			sys.exit(1)		
		posts_added = len(posts)

	else:

		db.execute("START TRANSACTION")
		for post in posts:
			new_post = db.insert("posts_" + datasource, data={post_fields[i]: post[i] for i in range(0, len(post))}, safe=True, constraints=("id", "board"), commit=False)
			if new_post:
				posts_added += 1

		db.commit()

	return posts_added

# set up
link_regex = re.compile(">>([0-9]+)")
post_fields = ("id", "thread_id", "board", "timestamp", "body", "author",
			   "author_type_id", "author_trip", "subject", "country_code", "country_name", "image_file",
			   "image_4chan", "image_md5", "image_dimensions", "image_filesize",
			   "semantic_url", "unsorted_data")

boards = ("a","b","c","d","e","f","g","gif","h","hr","k","m","o","p","r","s","t",
			"u","v","vg","vm","vmg","vr","vrpg","vst","w","wg","i","ic","r9k","s4s",
			"vip","qa","cm","hm","lgbt","y","3","aco","adv","an","bant","biz","cgl"
			"ck","co","diy","fa","fit","gd","hc","his","int","jp","lit","mlp","mu",
			"n","news","out","po","pol","pw","qst","sci","soc","sp","tg","toy","trv",
			"tv","vp","vt","wsg","wsr","x","xs")

# parse parameters
cli = argparse.ArgumentParser()
cli.add_argument("-i", "--input", required=True, help="CSV file to read from - should be a 4plebs data dump")
cli.add_argument("-d", "--datasource", type=str, default="4chan", help="Data source ID")
cli.add_argument("-b", "--board", required=True, help="What board the posts belong to, e.g. 'pol'")
cli.add_argument("-a", "--batch", type=int, default=1000000,
				 help="Size of post batches; every so many posts, they are saved to the database")
cli.add_argument("-s", "--skip", type=int, default=0, help="How many posts to skip")
cli.add_argument("-e", "--end", type=int, default=sys.maxsize,
				 help="At which post to stop processing. Starts counting at 0 (so not affected by --skip)")
cli.add_argument("-f", "--fast", default=False, type=bool,
				 help="Use batch queries instead of inserting posts individually. This is far faster than 'slow' mode, "
					  "but will crash if trying to insert a duplicate post, so it should only be used on an empty "
					  "database or when you're sure datasets don't overlap.")
args = cli.parse_args()

if not os.path.exists(args.input):
	print("File not found: %s" % args.input)
	sys.exit(1)

if args.board not in boards:
	print("%s is not a valid 4chan board name." % args.board)
	sys.exit(1)

db = Database(logger=Logger(), appname="4chan-import")

print("Opening %s." % args.input)
if args.skip > 0:
	print("Skipping %i posts." % args.skip)

if args.fast:
	print("Fast mode enabled.")

if args.board in ("pol"):
	troll_names = get_troll_names()

with open(args.input, encoding="utf-8") as inputfile:
	postscsv = csv.DictReader(inputfile, fieldnames=FourPlebs.columns, dialect=FourPlebs)

	postbuffer = []
	deleted_ids = set() # We insert deleted posts separately because we
						# need their `id_seq` for the posts_{datasource}_deleted table
	threads = {} # To insert thread information to the threads_{datasource} table
	posts = 0
	threads_added = 0
	posts_added = 0

	for csvpost in postscsv:

		posts += 1

		if posts < args.skip:
			if posts % 1000000 == 0:
				print("Skipped %s/%s rows (%.2f%%)..." % (posts, args.skip, (posts / args.skip) * 100))
			continue

		if posts >= args.end:
			break

		post = sanitize(csvpost)

		if int(csvpost["subnum"]) > 0:
			# skip ghost posts
			continue

		# We collect thread data first
		if post["thread_num"] not in threads:
			threads_added += 1
			threads[post["thread_num"]] = {
				"id": post["thread_num"],
				"board": args.board,
				"timestamp": 0,
				"timestamp_scraped": int(time.time()),
				"timestamp_modified": 0,
				"timestamp_deleted": 0,
				"timestamp_archived": 0,
				"num_unique_ips": -1,
				"num_images": 0,
				"num_replies": 0,
				"limit_bump": False,
				"limit_image": False,
				"is_sticky": False,
				"is_closed": False,
				"post_last": 0
			}
		thread = threads[post["thread_num"]]

		# Update thread data
		thread["post_last"] = max(thread["post_last"], int(post["num"]))
		thread["timestamp_modified"] = max(thread["timestamp_modified"], int(post["timestamp"]))
		thread["timestamp_archived"] = max(thread["timestamp_archived"], int(post["timestamp_expired"]))
		
		# Set OP data
		if post["thread_num"] == post["num"]:
			thread["timestamp"] = int(post["timestamp"])
			thread["is_sticky"] = True if int(post["sticky"]) != 0 else False
			thread["is_closed"] = True if int(post["locked"]) != 0 else False

			# Mark thread as deleted if the OP was deleted. This doesn't count for stickies.
			if int(post["deleted"]) == 1 and not int(post["sticky"]):
				thread["timestamp_deleted"] = max(int(thread.get("timestamp_modified") or 0), int(post["timestamp"]))

		threads[post["thread_num"]] = thread

		post_id = int(post["num"])
		
		# Set country name of post. This is a bit tricky because we have to differentiate
		# on troll and geo flags. These also change over time.
		country_code = post["poster_country"]
		country_name = ""

		if args.board in ("pol"):

			exif = json.loads(post["exif"]) if post.get("exif") else ""
			
			if post["poster_country"] or (exif and exif.get("troll_country")):
								
				if not post["poster_country"]:
					country_code = exif["troll_country"]

				# Older entries don't always have exif data, so let's extract the country name ourselves.
				if int(post["timestamp"]) < 1418515200:
					country_name = get_country_name(country_code, post["timestamp"], args.board)

				# We can assume it's a troll country if it's in "troll country"
				elif "troll_country" in exif:
					country_name = get_country_name("t_" + country_code, post["timestamp"], args.board)

				# For the leftover geo codes we're going to get the names straight away.
				# This might cause some ambiguous country codes to be misallocated (e.g.
				# TR as "Tree Hugger" instead of "Turkey", but there doesn't seem to be 
				# another way apart from querying the 4plebs API.
				else:
					country_name = get_country_name(country_code, post["timestamp"], args.board)

				# We're prepending a `t_` to troll codes to avoid ambiguous codes
				if country_name in troll_names:
					country_code = "t_" + country_code

		elif country_code and args.board in ("bant", "int"):
			country_name = get_country_name(country_code)

		postdata = (
			post["num"],  # id
			post["thread_num"],  # thread_id
			args.board, # board
			post["timestamp"],  # timestamp
			post["comment"],  # body
			post["name"],  # author
			post["capcode"],  # author_type_id
			post["trip"],  # author_trip
			post["title"],  # subject
			country_code,  # country_code
			country_name,  # country_name
			post["media_filename"],  # image_file
			post["media_orig"],  # image_4chan
			post["media_hash"],  # image_md5
			json.dumps({"w": post["media_w"], "h": post["media_h"]}) if post["media_filename"] != "" else "",
			# image_dimensions
			post["media_size"],  # image_filesize
			"",  # semantic_url
			"{}"  # unsorted_data
		)

		# If the post is deleted, we're going to add it to the post_{datasource}_deleted table
		# which is used to filter out deleted posts. 4plebs sees comments over 1000 replies for
		# sticky threads as "deleted", which we don't want, so we're skipping replies to sticky OPs for now.
		if int(post["deleted"]):
			if not (int(post["op"]) == 1 and int(thread["is_sticky"]) == 1):
				deleted_ids.add(int(post["num"]))
		
		postbuffer.append(postdata)

		# For speed, we only commit every so many posts
		if len(postbuffer) % args.batch == 0:
			new_posts = commit(postbuffer, post_fields, db, args.datasource, fast=args.fast)
			posts_added += new_posts
			print("Row %i - %i. %i new posts added." % (posts - args.batch, posts, posts_added))
			postbuffer = []

# commit remainder
print("Committing final posts.")
commit(postbuffer, post_fields, db, args.datasource, fast=args.fast)

# Insert deleted posts, and get their id_seq to use in the posts_{datasource}_deleted table
if deleted_ids:
	print("Also committing %i deleted posts to posts_%s_deleted table." % (len(deleted_ids), args.datasource))
	for deleted_id in deleted_ids:
		result = db.fetchone("SELECT id_seq, timestamp FROM posts_" + args.datasource + " WHERE id = %s AND board = '%s' " % (deleted_id, args.board))
		db.insert("posts_" + args.datasource + "_deleted", {"id_seq": result["id_seq"], "timestamp_deleted": result["timestamp"]}, safe=True)
	deleted_ids = set()

# update threads
print("Updating %s threads." % len(threads))
threads_comitted = 0
thread_ids = set(threads.keys())

for thread_id in thread_ids:
	threads_comitted += 1
	thread = threads[thread_id]

	# Check if the thread exists first.
	# If so, we might need to change some data.
	exists = db.fetchone("SELECT * FROM threads_" + args.datasource + " WHERE id = %s AND board = %s", (thread_id, args.board,))

	if not exists:
		db.insert("threads_" + args.datasource, thread)

	# We don't know if we have all the thread data here (things might be cutoff)
	# so do some quick checks if values are higher/newer than before
	else:

		if thread["timestamp"] == 0 or int(exists["timestamp"]) == 0:
			thread["timestamp"] = max(thread["timestamp"], int(exists["timestamp"]))
		else:
			thread["timestamp"] = min(thread["timestamp"], int(exists["timestamp"]))


		if thread["timestamp_scraped"] == 0 or int(exists["timestamp_scraped"]) == 0:
			thread["timestamp_scraped"] = max(thread["timestamp_scraped"], int(exists["timestamp_scraped"]))
		else:
			thread["timestamp_scraped"] = min(thread["timestamp_scraped"], int(exists["timestamp_scraped"]))
		
		thread["is_sticky"] = True if thread["is_sticky"] else exists["is_sticky"]
		thread["is_closed"] = True if thread["is_closed"] else exists["is_closed"]

		thread["post_last"] = max(int(thread.get("post_last") or 0), int(exists.get("post_last") or 0))
		thread["timestamp_deleted"] = max(int(thread.get("timestamp_deleted") or 0), int(exists.get("timestamp_deleted") or 0))
		thread["timestamp_archived"] = max(int(thread.get("timestamp_archived") or 0), int(exists.get("timestamp_archived") or 0))
		thread["timestamp_modified"] = max(int(thread.get("timestamp_modified") or 0), int(exists.get("timestamp_modified") or 0))

		db.update("threads_" + args.datasource, data=thread, where={"id": thread_id, "board": args.board})

	# Delete threads from dictionary to free up some RAM
	del threads[thread_id]

	if threads_comitted % 100000 == 0:
		print("%s threads committed" % threads_comitted)
		db.commit()

db.commit()

print("Updating thread statistics.")
db.execute(
	"UPDATE threads_" + args.datasource + " AS t SET num_replies = ( SELECT COUNT(*) FROM posts_" + args.datasource + " AS p WHERE p.thread_id = t.id) WHERE t.id IN %s AND board = %s",
	(tuple(thread_ids), args.board,))
db.execute(
	"UPDATE threads_" + args.datasource + " AS t SET num_images = ( SELECT COUNT(*) FROM posts_" + args.datasource + " AS p WHERE p.thread_id = t.id AND image_file != '') WHERE t.id IN %s AND board = %s",
	(tuple(thread_ids), args.board,))

db.commit()
print("Done!")