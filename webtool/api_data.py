"""
4CAT Data API - endpoints to get post and thread data from
"""

import datetime
import json
import os
import config

from collections import OrderedDict

from flask import jsonify, abort, send_file, request, render_template

from webtool import app, db, log, openapi, limiter
from webtool.lib.helpers import format_post
from backend.lib.helpers import get_absolute_folder

api_ratelimit = limiter.shared_limit("1 per second", scope="api")

@app.route('/api/<platform>/<board>/thread/<int:thread_id>.json')
@api_ratelimit
@openapi.endpoint
def api_thread(platform, board, thread_id):
	"""
	Emulate 4chan thread.json API endpoint

	:param str platform:  Platform ID
	:param str board:  Board name
	:param int thread_id:  Thread ID

	:request-param str format:  Data format. Can be `json` (default) or `html`.
	:return: Thread data, as a list of `posts`.
	"""
	if platform not in config.PLATFORMS:
		return jsonify({"error": "Invalid platform", "endpoint": request.url_rule.rule})

	thread = db.fetchone("SELECT * FROM threads_" + platform + " WHERE board = %s AND id = %s", (board, thread_id))
	response = get_thread(platform, board, thread, db)

	if not response:
		abort(404)
	elif request.args.get("format", "json") == "html":
		def format(post):
			post["com"] = format_post(post.get("com", "")).replace("\n", "<br>")
			return post
		response["posts"] = [format(post) for post in response["posts"]]
		metadata = {
			"subject": "".join([post.get("sub", "") for post in response["posts"]]),
			"id": response["posts"][0]["no"]
		}
		return render_template("thread.html", platform=platform, board=board, posts=response["posts"], thread=thread, metadata=metadata)
	else:
		return jsonify(response)


@app.route('/api/<platform>/<board>/threads.json')
@api_ratelimit
@openapi.endpoint
def api_board(platform, board):
	"""
	Emulate 4chan API /[board]/threads.json endpoint

    :param str platform:  Platform ID
	:param str board:  Board to get index for
	:return:  Thread index for board, as a list of pages, each page containing
	          a page number `page` and a list of `threads`, each thread having
	          the keys `no` and `last_modified`.
	"""
	if platform not in config.PLATFORMS:
		return jsonify({"error": "Invalid platform", "endpoint": request.url_rule.rule})

	threads = db.fetchall(
		"SELECT * FROM threads_" + platform + " WHERE board = %s ORDER BY is_sticky DESC, timestamp_modified DESC LIMIT 200",
		(board,))

	if not threads:
		abort(404)

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


@app.route('/api/<platform>/<board>/<int:page>.json')
@api_ratelimit
@openapi.endpoint
def api_board_page(platform, board, page):
	"""
	Emulate 4chan API /[board]/[page].json endpoint

    :param str platform:  Platform ID
	:param str board:  Board to get index for
	:param int page:  Page to show
	:return:  A page containing a list of `threads`, each thread a list of
	          `posts`.
	"""
	if platform not in config.PLATFORMS:
		return jsonify({"error": "Invalid platform", "endpoint": request.url_rule.rule})

	try:
		page = int(page)
	except ValueError:
		return jsonify({"error": "Invalid page number", "endpoint": request.url_rule.rule})

	limit = "LIMIT 15 OFFSET %i" % ((int(page) - 1) * 15)
	threads = db.fetchall(
		"SELECT * FROM threads_" + platform + " WHERE board = %s ORDER BY is_sticky DESC, timestamp_modified DESC " + limit,
		(board,))

	if not threads:
		abort(404)

	response = {
		"threads": [
			get_thread(platform, board, thread, db) for thread in threads
		]
	}

	return jsonify(response)


@app.route('/api/<platform>/<board>/catalog.json')
@api_ratelimit
@openapi.endpoint
def api_board_catalog(platform, board):
	"""
	Emulate 4chan API /[board]/catalog.json endpoint

    :param str platform:  Platform ID
	:param str board:  Board to get index for
	:return:  Board catalog, up to 150 threads divided over a list of
	          20-thread pages, each page having a `page` number and a
	          list of `threads`, each thread containing the first post.
	"""
	if platform not in config.PLATFORMS:
		return jsonify({"error": "Invalid platform", "endpoint": request.url_rule.rule})

	threads = db.fetchall(
		"SELECT * FROM threads_" + platform + " WHERE board = %s ORDER BY is_sticky DESC, timestamp_modified DESC LIMIT 150",
		(board,))

	if not threads:
		abort(404)

	response = []
	page = 1
	while len(threads) > 0:
		threads = threads[20:]
		page_threads = []

		for thread in threads:
			thread = get_thread(platform, board, thread, db, limit=6)
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


@app.route('/api/<platform>/<board>/archive.json')
@api_ratelimit
@openapi.endpoint
def get_archive(platform, board):
	"""
	Emulate 4chan API /[board]/archive.json endpoint

	hello

	:param str platform:  Platform ID
	:param board: Board to get list of archived thread IDs for
	:return:  Thread archive, a list of threads IDs of threads within this
	          board.
	"""
	if platform not in config.PLATFORMS:
		return jsonify({"error": "Invalid platform", "endpoint": request.url_rule.rule})

	threads = db.fetchall(
		"SELECT id FROM threads_" + platform + " WHERE board = %s AND timestamp_archived > 0 ORDER BY timestamp_archived ASC",
		(board,))
	return jsonify([thread["id"] for thread in threads])


@app.route('/api/<platform>/boards.json')
@api_ratelimit
@openapi.endpoint
def get_boards(platform):
	"""
	Get available boards in platform

	:param platform:  The platform for which to acquire the list of available
	                  boards.
	:return:  A list containing a list of `boards`, as string IDs.
	"""
	if platform not in config.PLATFORMS:
		return jsonify({"error": "Invalid platform", "endpoint": request.url_rule.rule})

	boards = db.fetchall("SELECT DISTINCT board FROM threads_" + platform)
	return jsonify({"boards": [{"board": board["board"]} for board in boards]})


def get_thread(platform, board, thread, db, limit=0):
	limit = "" if not limit or limit <= 0 else " LIMIT %i" % int(limit)
	posts = db.fetchall("SELECT * FROM posts_" + platform + " WHERE thread_id = %s ORDER BY timestamp ASC" + limit,
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
			"now": datetime.datetime.fromtimestamp(post["timestamp"]).strftime("%m/%d/%y(%a)%H:%I")
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


@app.route('/api/image/<img_hash>')
@api_ratelimit
def get_image(img_hash, limit=0):
	"""
	Returns an image based on the hexadecimal hash.
	Request should hex the md5 hashes first (e.g. with hexdigest())

	"""
	limit = "" if not limit or limit <= 0 else " LIMIT %i" % int(limit)
	print(img_hash)
	for file in os.listdir(get_absolute_folder(config.PATH_IMAGES) + '/'):
		if img_hash in file:
			image = config.PATH_IMAGES + '/' + file
			filename = file.split('/')
			filename = filename[len(filename) - 1]
			print(filename)
			filetype = filename.split('.')[1]

			if app.debug == True:
				print('debugging')
				file = '../../data/' + filename

				if filetype == 'webm':
					return send_file(file, mimetype='video/' + filetype)
				else:
					return send_file(file, mimetype='image/' + filetype)

			if filetype == 'webm':
				return send_file(image, mimetype='video/' + filetype)
			else:
				return send_file(image, mimetype='image/' + filetype)
	abort(404)
