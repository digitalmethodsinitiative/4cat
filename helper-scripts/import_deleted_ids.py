"""
Imports IDs of deleted posts.

Requires a text file with deleted post IDs on every line.
This script inserts these into the database if they're not
there already. Registers IDs to posts_{datasource}_deleted as
well as threads_{datasource} if it concerns a deleted OP.

The text file should have an ID on every line, with an optional
timestamp of deletion after a space (e.g. '349543818 1637922696').

"""

import os
import sys
import argparse

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/..")

from common.lib.database import Database
from common.lib.logger import Logger
from common.config_manager import config

# parse parameters
cli = argparse.ArgumentParser()
cli.add_argument("-i", "--input", required=True, help="text file to read from - should have a post ID on every line, "
						"and optionally a timestamp of deletion after a space (e.g. '349543818 1637922696').")
cli.add_argument("-b", "--board", required=True, help="What board the post IDs belong to, e.g. 'mu'")
cli.add_argument("-d", "--datasource", required=True, type=str, default="4chan", help="Data source ID")
args = cli.parse_args()

db = Database(logger=Logger(), appname="4chan-import", dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD, host=config.DB_HOST, port=config.DB_PORT)

posts = 0
posts_not_found = 0
threads = 0
batch = 100000

if not os.path.exists(args.input):
	print("File not found: %s" % args.input)
	sys.exit(1)

print("Opening %s." % args.input)

with open(args.input, "r", encoding="utf-8") as in_txt:

	for line in in_txt.readlines():
		
		post_id = line

		posts += 1

		timestamp_deleted = ""
		if " " in line:
			post_id, timestamp_deleted = line.split(" ")

		post = db.fetchone("SELECT id_seq, id, thread_id, timestamp FROM posts_" + args.datasource + " WHERE id = %s AND board = '%s'" % (post_id, args.board,))

		# If the post id not yet in the database, skip - 
		# we don't need to know about IDs that we haven't
		# encountered in the first place, and we need an `id_seq` field.
		if not post:
			posts_not_found += 1
		else:
			if not timestamp_deleted:
				timestamp_deleted = post["timestamp"]

			id_seq = post["id_seq"]
			db.insert("posts_" + args.datasource + "_deleted", data={"id_seq": id_seq, "timestamp_deleted": timestamp_deleted}, safe=True, commit=False)
			
			# Also check the threads_{datasource} table if we're dealing with an OP
			if post["id"] == post["thread_id"]:
				threads += 1
				db.execute("UPDATE threads_" + args.datasource + " SET timestamp_deleted = GREATEST(timestamp_deleted, %s) WHERE id = %s AND board = '%s'" % (int(timestamp_deleted), post_id, args.board,))

		# Commit every 100.000 lines
		if posts % batch == 0:
			print("Inserting/updating deleted post IDs %s/%s" % (posts - batch, posts), end="")
			if threads:
				print(" and %s deleted thread IDs" % threads, end="")
			if posts_not_found:
				print(". %s posts not found in the database." % posts_not_found, end="")
			print("")
			db.commit()
			threads = 0

print("Done")