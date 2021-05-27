"""
Queue JSON files in a given folder to be imported into the database directly

This can be used to import, for example, 4chan API output that has been
downloaded elsewhere.
"""
import argparse
import json
import time
import sys
import os

from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/..")
from common.lib.database import Database
from common.lib.logger import Logger

# parse parameters
cli = argparse.ArgumentParser()
cli.add_argument("-i", "--input", required=True, help="Folder to read from, containing JSON files representing threads")
cli.add_argument("-d", "--datasource", type=str, required=True, help="Datasource ID")
cli.add_argument("-b", "--board", type=str, required=True, help="Board name")
args = cli.parse_args()

if not Path(args.input).exists() or not Path(args.input).is_dir():
	print("%s is not a valid folder name." % args.input)
	sys.exit(1)

logger = Logger()
db = Database(logger=logger, appname="queue-folder")
folder = Path(args.input)

for jsonfile in folder.glob("*.json"):
	db.commit()

	try:
		with jsonfile.open() as input:
			posts = json.load(input)["posts"]
	except json.JSONDecodeError:
		print("ERROR PARSING FILE - SKIPPING: %s" % jsonfile)
		continue

	if not posts:
		print("Empy thread %s, skipping." % jsonfile)
		continue

	op = posts[0]
	last_post = max([post["no"] for post in posts if "no" in post])
	thread_id = op["no"]
	thread_exists = db.fetchone("SELECT id FROM threads_4chan WHERE id = %s AND board = %s", (thread_id, args.board))
	if not thread_exists:
		bumplimit = ("bumplimit" in op and op["bumplimit"] == 1) or (
					"bumplocked" in op and op["bumplocked"] == 1)

		db.insert("threads_4chan", {
			"id": thread_id,
			"board": args.board,
			"timestamp": op["time"],
			"timestamp_scraped": int(time.time()),
			"timestamp_modified": op["time"],
			"num_unique_ips": op["unique_ips"] if "unique_ips" in op else -1,
			"num_images": op["images"] if "images" in op else -1,
			"num_replies": len(posts),
			"limit_bump": bumplimit,
			"limit_image": ("imagelimit" in op and op["imagelimit"] == 1),
			"is_sticky": ("sticky" in op and op["sticky"] == 1),
			"is_closed": ("closed" in op and op["closed"] == 1),
			"post_last": last_post
		}, commit=False, safe=True)

	for post in posts:
		# save dimensions as a dumpable dict - no need to make it indexable
		if len({"w", "h", "tn_h", "tn_w"} - set(post.keys())) == 0:
			dimensions = {"w": post["w"], "h": post["h"], "tw": post["tn_w"], "th": post["tn_h"]}
		else:
			dimensions = {}

		post_data = {
			"id": post["no"],
			"board": args.board,
			"thread_id": thread_id,
			"timestamp": post["time"],
			"subject": post.get("sub", ""),
			"body": post.get("com", ""),
			"author": post.get("name", ""),
			"author_trip": post.get("trip", ""),
			"author_type": post["id"] if "id" in post else "",
			"author_type_id": post.get("capcode", ""),
			"country_code": post.get("country", ""),
			"country_name": post.get("country_name", ""),
			"image_file": post["filename"] + post["ext"] if "filename" in post else "",
			"image_4chan": str(post["tim"]) + post["ext"] if "filename" in post else "",
			"image_md5": post.get("md5", ""),
			"image_filesize": post.get("fsize", 0),
			"image_dimensions": json.dumps(dimensions),
			"semantic_url": post.get("semantic_url", "")
		}

		post_data = {k: str(v).replace("\x00", "") for k, v in post_data.items()}
		db.insert("posts_4chan", post_data, commit=False, safe=True)

	db.commit()
	print("Added thread with %i posts from %s" % (len(posts), jsonfile))

print("Done.")