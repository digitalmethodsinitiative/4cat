"""
4CAT Data API - endpoints to get post and thread data from
"""

import datetime
import config
import json
import re

from collections import OrderedDict
from pathlib import Path

from flask import jsonify, abort, send_file, request, render_template

from webtool import app, db, log, openapi, limiter
from webtool.lib.helpers import format_post, error
from common.lib.helpers import strip_tags

api_ratelimit = limiter.shared_limit("45 per minute", scope="api")


@app.route('/api/<datasource>/<board>/thread/<int:thread_id>.json')
@api_ratelimit
@openapi.endpoint("data")
def api_thread(datasource, board, thread_id):
	"""
	Emulate 4chan thread.json API endpoint

	:param str datasource:  Data source ID
	:param str board:  Board name
	:param int thread_id:  Thread ID

	:request-param str format:  Data format. Can be `json` (default) or `html`.

	:return: Thread data, as a list of `posts`.

	:return-schema: {type=object,properties={posts={type=object,additionalProperties={}}}}

	:return-error 404:  If the thread ID does not exist for the given data source.
	"""
	if datasource not in config.DATASOURCES:
		return error(404, error="Invalid data source")

	thread = db.fetchone("SELECT * FROM threads_" + datasource + " WHERE board = %s AND id = %s", (board, thread_id))

	if thread == None:
		return "Thread is not anymore available on the server."

	response = get_thread(datasource, board, thread, db)

	def strip_html(post):
		post["com"] = strip_tags(post.get("com", ""))
		return post

	response["posts"] = [strip_html(post) for post in response["posts"]]

	if not response:
		return error(404, error="No posts available for this datasource")

	elif request.args.get("format", "json") == "html":
		def format(post):
			post["com"] = format_post(post.get("com", "")).replace("\n", "<br>")
			return post

		response["posts"] = [format(post) for post in response["posts"]]
		metadata = {
			"subject": "".join([post.get("sub", "") for post in response["posts"]]),
			"id": response["posts"][0]["no"]
		}
		return render_template("thread.html", datasource=datasource, board=board, posts=response["posts"],
							   thread=thread, metadata=metadata)
	else:
		return jsonify(response)


@app.route('/api/<datasource>/<board>/threads.json')
@api_ratelimit
@openapi.endpoint("data")
def api_board(datasource, board):
	"""
	Emulate 4chan API /[board]/threads.json endpoint

    :param str datasource:  Data source ID
	:param str board:  Board to get index for
	:return:  Thread index for board, as a list of pages, each page containing
	          a page number `page` and a list of `threads`, each thread having
	          the keys `no` and `last_modified`.

	:return-schema:{type=array,items={type=object,properties={
		page={type=integer},
		threads={type=array,items={type=object,properties={
			no={type=integer},
			last_modified={type=integer},
			replies={type=integer}
		}}}
	}}}

	:return-error 404:  If the board does not exist for the given datasource.
	"""
	if datasource not in config.DATASOURCES:
		return error(404, error="Invalid data source")

	threads = db.fetchall(
		"SELECT * FROM threads_" + datasource + " WHERE board = %s ORDER BY is_sticky DESC, timestamp_modified DESC LIMIT 200",
		(board,))

	if not threads:
		return error(404, error="No threads available for this datasource")

	response = []
	page = 1
	while len(threads) > 0:
		chunk = threads[:20]
		threads = threads[20:]

		response.append({
			"page": page,
			"threads": [{
				"no": thread["id"],
				"last_modified": thread["timestamp_modified"]
			} for thread in chunk]
		})

		page += 1

	return jsonify(response)


@app.route('/api/<datasource>/<board>/<int:page>.json')
@api_ratelimit
@openapi.endpoint("data")
def api_board_page(datasource, board, page):
	"""
	Emulate 4chan API /[board]/[page].json endpoint

    :param str datasource:  Data source ID
	:param str board:  Board to get index for
	:param int page:  Page to show
	:return:  A page containing a list of `threads`, each thread a list of
	          `posts`.

	:return-schema:{type=object,properties={
		threads={type=array,items={type=object,properties={
			posts={type=array,items={type=object,additionalProperties={}}}
		}}}
	}}

	:return-error 404:  If the board does not exist for the given datasource.
	"""
	if datasource not in config.DATASOURCES:
		return error(404, error="Invalid data source")

	try:
		page = int(page)
	except ValueError:
		return error(404, error="Invalid page number")

	limit = "LIMIT 15 OFFSET %i" % ((int(page) - 1) * 15)
	threads = db.fetchall(
		"SELECT * FROM threads_" + datasource + " WHERE board = %s ORDER BY is_sticky DESC, timestamp_modified DESC " + limit,
		(board,))

	if not threads:
		return error(404, error="No threads available for this datasource")

	response = {
		"threads": [
			get_thread(datasource, board, thread, db) for thread in threads
		]
	}

	return jsonify(response)


@app.route('/api/<datasource>/<board>/catalog.json')
@api_ratelimit
@openapi.endpoint("data")
def api_board_catalog(datasource, board):
	"""
	Emulate 4chan API /[board]/catalog.json endpoint

    :param str datasource:  Data source ID
	:param str board:  Board to get index for
	:return:  Board catalog, up to 150 threads divided over a list of
	          20-thread pages, each page having a `page` number and a
	          list of `threads`, each thread containing the first post.

	:return-schema:{type=array,items={type=object,properties={
		page={type=integer},
		threads={type=array,items={type=object,properties={
			no={type=integer},
			last_modified={type=integer},
			replies={type=integer}
		}}}
	}}}

	:return-error 404:  If the board does not exist for the given datasource.
	"""
	if datasource not in config.DATASOURCES:
		return error(404, error="Invalid data source")

	threads = db.fetchall(
		"SELECT * FROM threads_" + datasource + " WHERE board = %s ORDER BY is_sticky DESC, timestamp_modified DESC LIMIT 150",
		(board,))

	if not threads:
		return error(404, error="No threads available for this datasource")

	response = []
	page = 1
	while len(threads) > 0:
		threads = threads[20:]
		page_threads = []

		for thread in threads:
			thread = get_thread(datasource, board, thread, db, limit=6)
			if not thread:
				log.error("Thread %s is in database and was requested via API but has no posts." % thread)
				continue

			thread = thread["posts"]
			first_post = thread[0]
			if len(thread) > 1:
				first_post["last_replies"] = thread[1:6]

			page_threads.append(first_post)

		response.append({
			"page": page,
			"threads": page_threads
		})

	return jsonify(response)


@app.route('/api/<datasource>/<board>/archive.json')
@api_ratelimit
@openapi.endpoint("data")
def get_archive(datasource, board):
	"""
	Emulate 4chan API /[board]/archive.json endpoint

	:param str datasource:  Data source ID
	:param board: Board to get list of archived thread IDs for
	:return:  Thread archive, a list of threads IDs of threads within this
	          board.

	:return-schema: {type=array,items={type=integer}}

	:return-error 404: If the datasource does not exist.
	"""
	if datasource not in config.DATASOURCES:
		return error(404, error="Invalid data source")

	threads = db.fetchall(
		"SELECT id FROM threads_" + datasource + " WHERE board = %s AND timestamp_archived > 0 ORDER BY timestamp_archived ASC",
		(board,))
	return jsonify([thread["id"] for thread in threads])


@app.route('/api/<datasource>/boards.json')
@api_ratelimit
@openapi.endpoint("data")
def get_boards(datasource):
	"""
	Get available boards in datasource

	:param datasource:  The datasource for which to acquire the list of available
	                  boards.
	:return:  A list containing a list of `boards`, as string IDs.

	:return-schema: {type=object,properties={
		boards={type=array,items={type=object,properties={
			board={type=string}
		}}}
	}}

	:return-error 404: If the datasource does not exist.
	"""
	if datasource not in config.DATASOURCES:
		return error(404, error="Invalid data source")

	boards = db.fetchall("SELECT DISTINCT board FROM threads_" + datasource)
	return jsonify({"boards": [{"board": board["board"]} for board in boards]})


def get_thread(datasource, board, thread, db, limit=0):
	limit = "" if not limit or limit <= 0 else " LIMIT %i" % int(limit)
	posts = db.fetchall("SELECT * FROM posts_" + datasource + " WHERE thread_id = %s ORDER BY timestamp ASC" + limit,
						(thread["id"],))
	if not posts:
		return False

	response = {"posts": []}

	first_post = True
	for post in posts:

		# add data that is present for every single post
		response_post = OrderedDict({
			"resto": 0 if first_post else int(thread["id"]),
			"no": post["id"],
			"time": post["timestamp"],
			"now": datetime.datetime.utcfromtimestamp(post["timestamp"]).strftime("%m/%d/%y(%a)%H:%I")
		})

		# first post has some extra data as well that is never present for replies
		if first_post:
			if thread["is_sticky"]:
				response_post["sticky"] = 1
			if thread["is_closed"]:
				response_post["closed"] = 1

			response_post["imagelimit"] = 1 if thread["limit_image"] else 0
			response_post["bumplimit"] = 1 if thread["limit_bump"] else 0

			if thread["timestamp_archived"] > 0:
				response_post["archived"] = 1
				response_post["archived_on"] = thread["timestamp_archived"]

			response_post["unique_ips"] = thread["num_unique_ips"]
			response_post["replies"] = thread["num_replies"] - 1  # OP doesn't count as reply
			response_post["images"] = thread["num_images"]

		# there are a few fields that are only present if an image was attached
		if post["image_file"]:
			response_post["tim"] = int(post["image_4chan"].split(".")[0])
			response_post["ext"] = "." + post["image_4chan"].split(".").pop()
			response_post["md5"] = post["image_md5"]
			response_post["filename"] = ".".join(post["image_file"].split(".")[:-1])
			response_post["fsize"] = post["image_filesize"]

			dimensions = json.loads(post["image_dimensions"])
			if "w" in dimensions and "h" in dimensions:
				response_post["w"] = dimensions["w"]
				response_post["h"] = dimensions["h"]
			if "tw" in dimensions and "th" in dimensions:
				response_post["tn_w"] = dimensions["tw"]
				response_post["tn_h"] = dimensions["th"]

		# for the rest, just add it if not empty
		if post["subject"]:
			response_post["sub"] = post["subject"]

		if post["body"]:
			response_post["com"] = post["body"]

		if post["author"]:
			response_post["name"] = post["author"]

		if post["author_trip"]:
			response_post["trip"] = post["author_trip"]

		if post["author_type"]:
			response_post["id"] = post["author_type"]

		if post["author_type_id"]:
			response_post["capcode"] = post["author_type_id"]

		if post["semantic_url"]:
			response_post["semantic_url"] = post["semantic_url"]

		response["posts"].append(response_post)
		first_post = False

	return response


@app.route('/api/image/<img_file>')
@app.route('/api/imagefile/<img_file>')
def get_image_file(img_file, limit=0):
	"""
	Returns an image based on filename
	Request should hex the md5 hashes first (e.g. with hexdigest())

	"""
	if not re.match(r"([a-zA-Z0-9]+)\.([a-z]+)", img_file):
		abort(404)

	image_path = Path(config.PATH_ROOT, config.PATH_IMAGES, img_file)
	if not image_path.exists():
		abort(404)

	return send_file(str(image_path))
