"""
Helper methods and classes for dump importer (see importDump.py)
"""
import psycopg2
import json
import csv
import sys
import re
from psycopg2.extras import execute_values

link_regex = re.compile(">>([0-9]+)")
post_fields = ("id", "timestamp", "timestamp_deleted", "thread_id", "body", "author",
			   "author_type_id", "author_trip", "subject", "country_code", "image_file",
			   "image_4chan", "image_md5", "image_dimensions", "image_filesize",
			   "semantic_url", "unsorted_data")
post_fields_sql = ", ".join(post_fields)


def parse_value(key, value):
	"""
	The csv data is a little peculiar, strip some useless values

	:param value:  Value to process
	:return:  Parsed value
	"""
	if isinstance(value, str):
		value = value.strip()

	if value == "N":
		return ""

	try:
		if "\n" in value:
			return value.replace("\\\n", "\n")
	except TypeError:
		pass

	return value

post_buffer = []
batch_size = 10000
# problematic ID: 23628818 vs 23974771
def process_post(post, db, sequence, threads, board):
	"""
	Add one post to the database

	:param dict post:  Post data
	:param Database db:  Database handler
	:param tuple sequence: tuple(posts to skip, number of posts added)
	:param int posts_added:   Posts added so far
	:param dict threads: Thread info, {id: data}
	:return:
	"""
	global post_buffer

	# skip if needed
	posts_added = sequence[1] + 1
	if posts_added <= sequence[0]:
		return posts_added

	# sanitize post data
	post = dict(post)
	post = {key: parse_value(key, post[key]) for key in post}

	# subnum > 0 is not from 4chan
	if int(post["subnum"]) > 0:
		return posts_added

	# see what we need to do with the thread
	post_thread = post["num"] if post["thread_num"] == 0 else post["thread_num"]
	post_thread = int(post_thread)

	if post_thread in threads:
		# thread already exists

		thread = threads[post_thread]
		updates = {}
		if int(post["timestamp"]) < int(thread["timestamp"]):
			updates["timestamp"] = post["timestamp"]

		if int(post["timestamp"]) > int(thread["timestamp_modified"]):
			updates["timestamp_modified"] = post["timestamp"]

		if int(post["num"]) > int(thread["post_last"]):
			updates["post_last"] = post["num"]

		if post["sticky"] == "1":
			updates["is_sticky"] = True

		if post["locked"] == "1":
			updates["is_closed"] = True

		# only update database if something actually changed
		if updates != {}:
			db.update("4chan_threads", where={"id": thread["id"]}, data=updates, commit=False)
			threads[post_thread] = {**thread, **updates}

	else:
		# insert new thread
		thread_data = {
			"id": post_thread,
			"board": board,
			"timestamp": post["timestamp"],
			"timestamp_scraped": 0,
			"timestamp_modified": 0,
			"post_last": post["num"],
			"index_positions": ""
		}

		db.insert("4chan_threads", data=thread_data, commit=False)
		threads[post_thread] = thread_data

	# add post to database
	post_buffer.append((
		post["num"],  # id
		post["timestamp"],  # timestamp
		post["deleted"] if int(post["deleted"]) > 1 else 0,  # timestamp_deleted
		post_thread,  # thread_id
		post["comment"],  # body
		post["name"],  # author
		post["capcode"],  # author_type_id
		post["trip"],  # author_trip
		post["title"],  # subject
		post["poster_country"],  # country_code
		post["media_filename"],  # image_file
		post["media_orig"],  # image_4chan
		post["media_hash"],  # image_md5
		json.dumps({"w": post["media_w"], "h": post["media_h"]}) if post["media_filename"] != "" else "",  # image_dimensions
		post["media_size"],  # image_filesize
		"",  # semantic_url
		"{}"  # unsorted_data
	))

	# for speed, we only commit every so many posts
	if len(post_buffer) % batch_size == 0:
		print("Committing posts %i-%i to database" % (posts_added - batch_size, posts_added))
		try:
			db.execute_many("INSERT INTO 4chan_posts (" + post_fields_sql + ") VALUES %s", post_buffer)
		except psycopg2.IntegrityError as e:
			# print(repr(post_buffer))
			print(repr(e))
			print(e)
			sys.exit(1)
		db.commit()
		post_buffer = []

	return posts_added


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
