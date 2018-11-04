import datetime
import psutil
import json
import os
import config
import hashlib
import base64
import glob

from collections import OrderedDict

from flask import jsonify, abort, send_file
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from fourcat import app
from backend.lib.database import Database
from backend.lib.queue import JobQueue
from backend.lib.logger import Logger
from backend.lib.helpers import get_absolute_folder

log = Logger()
limiter = Limiter(app, key_func=get_remote_address)
api_ratelimit = limiter.shared_limit("1 per second", scope="api")

API_SUCCESS = 200
API_FAIL = 404


@app.route('/api/')
@api_ratelimit
def api_main():
	"""
	API Index

	No data here - just a reference to the documentation

	:return: Flask JSON response
	"""
	response = {
		"code": API_SUCCESS,
		"items": [
			"Refer to https://4cat.oilab.nl/api.md for API documentation."
		]
	}

	return jsonify(response)


@app.route('/api/status.json')
@api_ratelimit
def api_status():
	"""
	Get service status

	:return: Flask JSON response
	"""

	# get job stats
	db = Database(logger=log)
	queue = JobQueue(logger=log, database=db)
	jobs = queue.get_all_jobs()
	jobs_count = len(jobs)
	jobs_types = set([job["jobtype"] for job in jobs])
	jobs_sorted = {jobtype: len([job for job in jobs if job["jobtype"] == jobtype]) for jobtype in jobs_types}
	jobs_sorted["total"] = jobs_count
	db.close()

	# determine if backend is live by checking if the process is running

	lockfile = get_absolute_folder(config.PATH_LOCKFILE) + "/4cat.pid"
	if os.path.isfile(lockfile):
		with open(lockfile) as pidfile:
			pid = pidfile.read()
			backend_live = int(pid) in psutil.pids()
	else:
		backend_live = False

	response = {
		"code": API_SUCCESS,
		"items": {
			"backend": {
				"live": backend_live,
				"queued": jobs_sorted
			},
			"frontend": {
				"live": True  # duh
			}
		}
	}

	return jsonify(response)


@app.route('/api/<board>/thread/<thread_id>.json')
@api_ratelimit
def api_thread(board, thread_id):
	"""
	Emulate 4chan thread.json API endpoint

	:param str board:  Board name
	:param int thread_id:  Thread ID
	:return: JSONified thread data
	"""
	db = Database(logger=log)
	thread = db.fetchone("SELECT * FROM threads WHERE board = %s AND id = %s", (board, thread_id))
	response = get_thread(board, thread, db)
	db.close()

	if not response:
		abort(404)
	else:
		return jsonify(response)


@app.route('/api/<board>/threads.json')
@api_ratelimit
def api_board(board):
	"""
	Emulate 4chan API /[board]/threads.json endpoint

	:param str board:  Board to get index for
	:return:  JSONified thread index
	"""
	db = Database(logger=log)
	threads = db.fetchall(
		"SELECT * FROM threads WHERE board = %s ORDER BY is_sticky DESC, timestamp_modified DESC LIMIT 200", (board,))
	db.close()
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


@app.route('/api/<board>/<page>.json')
@api_ratelimit
def api_board_page(board, page):
	"""
	Emulate 4chan API /[board]/[page].json endpoint

	:param str board:  Board to get index for
	:param int page:  Page to show
	:return:  JSONified thread index
	"""
	db = Database(logger=log)
	limit = "LIMIT 15 OFFSET %i" % ((int(page) - 1) * 15)
	threads = db.fetchall(
		"SELECT * FROM threads WHERE board = %s ORDER BY is_sticky DESC, timestamp_modified DESC " + limit, (board,))

	if not threads:
		db.close()
		abort(404)

	response = {
		"threads": [
			get_thread(board, thread, db) for thread in threads
		]
	}

	db.close()

	return jsonify(response)


@app.route('/api/<board>/catalog.json')
@api_ratelimit
def api_board_catalog(board):
	"""
	Emulate 4chan API /[board]/catalog.json endpoint

	:param str board:  Board to get index for
	:return:  JSONified thread index
	"""
	db = Database(logger=log)
	threads = db.fetchall(
		"SELECT * FROM threads WHERE board = %s ORDER BY is_sticky DESC, timestamp_modified DESC LIMIT 150", (board,))

	if not threads:
		db.close()
		abort(404)

	response = []
	page = 1
	while len(threads) > 0:
		chunk = threads[:20]
		threads = threads[20:]
		page_threads = []

		for thread in threads:
			thread = get_thread(board, thread, db, limit=6)["posts"]
			first_post = thread[0]
			if len(thread) > 1:
				first_post["last_replies"] = thread[1:6]

			page_threads.append(first_post)

		response.append({
			"page": page,
			"threads": page_threads
		})

	db.close()
	return jsonify(response)

@app.route('/api/<board>/archive.json')
@api_ratelimit
def get_archive(board):
	"""
	Emulate 4chan API /[board]/archive.json endpoint

	:param board: Board to get list of archived thread IDs for
	:return:  Simple list of thread IDs, oldest first
	"""
	db = Database(logger=log)

	threads = db.fetchall("SELECT id FROM threads WHERE board = %s AND timestamp_archived > 0 ORDER BY timestamp_archived ASC", (board,))
	return jsonify([thread["id"] for thread in threads])

@app.route('/api/boards.json')
@api_ratelimit
def get_boards():
	db = Database(logger=log)
	boards = db.fetchall("SELECT DISTINCT board FROM threads")
	return jsonify({"boards": [{"board": board["board"]} for board in boards]})


def get_thread(board, thread, db, limit=0):
	limit = "" if not limit or limit <= 0 else " LIMIT %i" % int(limit)
	posts = db.fetchall("SELECT * FROM posts WHERE thread_id = %s ORDER BY timestamp ASC" + limit, (thread["id"],))
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
			response_post["w"] = dimensions["w"]
			response_post["h"] = dimensions["h"]
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