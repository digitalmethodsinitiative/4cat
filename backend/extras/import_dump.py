"""
Imports 4plebs database dumps
"""
import sqlite3
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/..")
from csv import DictReader
from lib.logger import Logger
from lib.database import Database
from lib.import_helpers import FourPlebs, process_post

#
# Interpret and validate command line arguments
#
skip = 0
for i in range(0, len(sys.argv)):
	if sys.argv[i][:7] == "--skip=":
		skip = int(sys.argv[i][7:])
		del sys.argv[i]
		break

# show manual if needed
if len(sys.argv) < 2 or not os.path.isfile(sys.argv[1]):
	print("Please provide a file to import.")
	print()
	print("Usage: python3 importDump.py [--skip=n] <sourcefile> [boardname]")
	print("Where sourcefile is either:")
	print("- a path to a 4plebs CSV dump")
	print("- a path to an SQLite database with a 'posts' table with columns matching the")
	print("  columns in the 4plebs dumps")
	print("And boardname is the name of the board contained within. If boardname is")
	print("omitted, the first word in the file name is used as the board name (e.g. pol for")
	print("pol.dump.csv)")
	print()
	print("Arguments:")
	print("--skip=n    : skip first n posts")
	print()
	sys.exit(1)

sourcefile = sys.argv[1]
board = sourcefile.split("/").pop().split(".")[0] if len(sys.argv) < 3 else sys.argv[2]
ext = sourcefile.split(".").pop()
if ext.lower() not in ["csv", "db"]:
	print("Source file should be a CSV file or SQlite3 database")
	sys.exit(1)

print("Importing from: %s" % sourcefile)
print("Board to be imported: %s" % board)
if skip > 0:
	print("Skipping first %i posts." % skip)

#
# Init database - we need the thread data to know whether to insert a new thread for a post
#
db = Database(logger=Logger())
threads = {thread["id"]: thread for thread in
		   db.fetchall("SELECT id, timestamp, timestamp_modified, post_last FROM threads")}

#
# Start importing posts
#
if ext.lower() == "csv":
	# import from CSV dump
	posts_added = 0

	db.execute("TRUNCATE TABLE posts; TRUNCATE TABLE threads; TRUNCATE TABLE posts_mention; ALTER SEQUENCE posts_id_seq_seq RESTART; ALTER SEQUENCE threads_id_seq_seq RESTART;")
	db.commit()

	with open(sourcefile) as csvdump:
		reader = DictReader(csvdump, fieldnames=FourPlebs.columns, dialect=FourPlebs)
		for post in reader:
			post["board"] = board
			posts_added = process_post(post, db=db, sequence=(skip, posts_added), threads=threads, board=board)
else:
	# import from SQLite3 database
	sqlite = sqlite3.connect(sourcefile)
	sqlite.row_factory = sqlite3.Row
	cursor = sqlite.cursor()

	# find table name
	table = cursor.execute("SELECT * FROM sqlite_master WHERE type = 'table'").fetchone()[1]

	posts_added = skip
	posts = cursor.execute("SELECT * FROM " + table + " LIMIT -1 OFFSET " + str(skip))
	post = posts.fetchone()
	while post:
		posts_added = process_post(post, db=db, sequence=(0, posts_added), threads=threads, board=board)
		post = posts.fetchone()

print("Done! Committing final transaction...")
db.commit()
print("Done!")

#
# Update thread stats that we can derive ourselves
#
print("Updating thread statistics...")
threads_updated = 0
for thread in threads:
	posts = db.fetchone("SELECT COUNT(*) AS num FROM posts WHERE thread_id = %s", (thread,))["num"]
	images = db.fetchone("SELECT COUNT(*) AS num FROM posts WHERE image_file != '' AND thread_id = %s", (thread,))[
		"num"]
	posts_deleted = \
		db.fetchone("SELECT COUNT(*) AS num FROM posts WHERE thread_id = %s AND timestamp_deleted > 0", (thread,))[
			"num"]

	update = {"num_replies": posts, "num_images": images}

	# if all posts are deleted, then the thread is deleted - mark thread as such
	if posts_deleted == posts:
		last_post = db.fetchone("SELECT MAX(timestamp) as deleted_time FROM posts WHERE thread_id = %s", (thread,))
		update["timestamp_deleted"] = last_post["deleted_time"]

	db.update("threads", data={"num_replies": posts, "num_images": images}, where={"id": thread}, commit=False)

	threads_updated += 1
	if threads_updated % 1000 == 0:
		print("Updated threads %i-%i of %i" % (threads_updated - 1000, threads_updated, len(threads)))

# finalize last bits
print("Committing changes...")
db.commit()
print("Done!")
