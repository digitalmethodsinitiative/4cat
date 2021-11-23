"""
4CAT Data API - endpoints to get post and thread data from
"""

import datetime
import config
import json
import csv
import re

from backend import all_modules

from collections import OrderedDict
from pathlib import Path

from flask import jsonify, abort, send_file, request, render_template

from webtool import app, db, log, openapi, limiter
from webtool.lib.helpers import format_post, error
from common.lib.helpers import strip_tags

api_ratelimit = limiter.shared_limit("45 per minute", scope="api")


@app.route('/api/<datasource>/<board>/thread/<string:thread_id>.json')
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

	posts = get_posts(db, datasource, board, ids=tuple([thread_id]), threads=True, order_by=["id"])

	posts = [strip_html(post) for post in posts]

	if not posts:
		return error(404, error="No posts available for this thread")

	elif request.args.get("format", "json") == "html":
		
		posts = [format(post) for post in posts]
		return render_template("explorer/explorer.html", datasource=datasource, board=board, posts=posts, limit=len(posts), post_count=len(posts), thread=thread_id)
	else:
		return jsonify(posts)


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


@app.route('/explorer/dataset/<key>/', defaults={'page': 0})
@app.route('/explorer/dataset/<key>/<int:page>')
@api_ratelimit
@openapi.endpoint("data")
def explorer_dataset(key, page):
	"""
	Show posts from a specific dataset

	:param str dataset_key:  Dataset key

	:return-schema: {type=array,items={type=integer}}

	:return-error 404: If the dataset does not exist.
	"""

	# Get dataset info.
	dataset = db.fetchone("SELECT * FROM datasets WHERE key = %s", (key,))

	# The amount of posts to show on a page
	limit = 100

	# The offset for posts depending on the current page
	offset = ((page - 1) * limit) if page else 0

	# Do come catching
	if not dataset:
		return error(404, error="Invalid data source")

	if dataset["key_parent"]:
		return error(404, error="Exporer only available for top-level datasets")

	if not dataset["result_file"] or not dataset["is_finished"]:
		return error(404, error="This dataset didn't finish executing (yet)")

	# Load some variables
	parameters = json.loads(dataset["parameters"])
	datasource = parameters["datasource"]
	board = parameters["board"]
	annotation_fields = json.loads(dataset["annotation_fields"]) if dataset["annotation_fields"] else None

	# If the dataset is local, we can add some more features
	# (like the ability to navigate to threads)
	is_local = True if all_modules.datasources[datasource].get("is_local") else False
	
	# Check if the dataset in fact exists
	dataset_path = Path(config.PATH_ROOT, config.PATH_DATA, dataset["result_file"])
	if not dataset_path.exists():
		abort(404)

	# Load posts
	post_ids = []
	posts = []
	count = 0
	with open(dataset_path, "r", encoding="utf-8") as dataset_file:
		reader = csv.reader(dataset_file)
		
		# Get the column names (varies per datasource).
		columns = next(reader)

		for post in reader:

			# Use an offset if we're showing a page beyond the first.
			count += 1
			if count <= offset:
				continue

			# Attribute column names and collect dataset's posts.
			post = {columns[i]: post[i] for i in range(len(post))}
			post_ids.append(post["id"])
			posts.append(post)

			# Stop if we exceed the max posts per page.
			if count >= (offset + limit):
				break

	# Clean up HTML
	posts = [strip_html(post) for post in posts]
	posts = [format(post) for post in posts]

	# Include custom css if it exists in the datasource's 'explorer' dir.
	# The file's naming format should e.g. be 'reddit-explorer.css'.
	css = get_custom_css(datasource)

	# Include custom fields if it they are in the datasource's 'explorer' dir.
	# The file's naming format should e.g. be 'reddit-explorer.json'.
	custom_fields = get_custom_fields(datasource)

	if not posts:
		return error(404, error="No posts available for this datasource")

	# Generate the HTML page
	return render_template("explorer/explorer.html", key=key, datasource=datasource, board=board, is_local=is_local, parameters=parameters, annotation_fields=annotation_fields, posts=posts, css=css, custom_fields=custom_fields, page=page, offset=offset, limit=limit, post_count=int(dataset["num_rows"]))

@app.route('/explorer/thread/<datasource>/<board>/<string:thread_id>')
@api_ratelimit
@openapi.endpoint("data")
def explorer_thread(datasource, board, thread_id):
	"""
	Show a thread in the explorer

	:param str datasource:  Data source ID
	:param str board:  Board name
	:param int thread_id:  Thread ID

	:return-error 404:  If the thread ID does not exist for the given data source.
	"""

	if not datasource:
		return error(404, error="No datasource provided")
	if datasource not in config.DATASOURCES:
		return error(404, error="Invalid data source")
	if not board:
		return error(404, error="No board provided")
	if not thread_id:
		return error(404, error="No thread ID provided")

	# Get the posts with this thread ID.
	posts = get_posts(db, datasource, board, ids=tuple([thread_id]), threads=True, order_by=["id"])

	posts = [strip_html(post) for post in posts]

	if not posts:
		return error(404, error="No posts available for this thread")

	posts = [format(post) for post in posts]
	return render_template("explorer/explorer.html", datasource=datasource, board=board, posts=posts, limit=len(posts), post_count=len(posts), thread=thread_id)

@app.route('/explorer/post/<datasource>/<board>/<string:post_id>')
@api_ratelimit
@openapi.endpoint("data")
def explorer_post(datasource, board, thread_id):
	"""
	Show a thread in the explorer

	:param str datasource:  Data source ID
	:param str board:  Board name
	:param int thread_id:  Thread ID

	:return-error 404:  If the thread ID does not exist for the given data source.
	"""

	if not datasource:
		return error(404, error="No datasource provided")
	if datasource not in config.DATASOURCES:
		return error(404, error="Invalid data source")
	if not board:
		return error(404, error="No board provided")
	if not thread_id:
		return error(404, error="No thread ID provided")

	# Get the posts with this thread ID.
	posts = get_posts(db, datasource, board, ids=tuple([thread_id]), threads=True, order_by=["id"])

	posts = [strip_html(post) for post in posts]

	if not posts:
		return error(404, error="No posts available for this thread")

	posts = [format(post) for post in posts]
	return render_template("explorer/explorer.html", datasource=datasource, board=board, posts=posts, limit=len(posts), post_count=len(posts), thread=thread_id)

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

def get_posts(db, datasource, board, ids, threads=False, limit=0, offset=0, order_by=["timestamp"]):

	if not ids:
		return None

	id_field = "id" if not threads else "thread_id"
	order_by = " ORDER BY " + ", ".join(order_by)
	limit = "" if not limit or limit <= 0 else " LIMIT %i" % int(limit)
	offset = " OFFSET %i" % int(offset)

	posts = db.fetchall("SELECT * FROM posts_" + datasource + " WHERE " + id_field + " IN %s " + order_by + " ASC" + limit + offset,
						(ids,))
	if not posts:
		return False

	return posts

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

def get_custom_css(datasource):
	"""
	Check if there's a custom css file for this dataset.
	If so, return the text.
	Custom css files should be placed in an 'explorer' directory in the the datasource folder and named '<datasourcename>-explorer.css' (e.g. 'reddit/explorer/reddit-explorer.css').
	
	:param datasource, str: Datasource name

	:return: The css as string.
	"""

	# Set the directory name of this datasource.
	# Do some conversion for some imageboard names (4chan, 8chan).
	if datasource.startswith("4"):
		datasource_dir = datasource.replace("4", "four")
	elif datasource.startswith("8"):
		datasource_dir = datasource.replace("8", "eight")
	else:
		datasource_dir = datasource
	
	css_path = Path(config.PATH_ROOT, "datasources", datasource_dir, "explorer", datasource.lower() + "-explorer.css")
	if css_path.exists():
		with open(css_path, "r", encoding="utf-8") as css:
			css = css.read()
	else:
		css = None
	return css

def get_custom_fields(datasource):
	"""
	Check if there are custom fields that need to be showed for this datasource.
	If so, return a dictionary of those fields.
	Custom field json files should be placed in an 'explorer' directory in the the datasource folder and named '<datasourcename>-explorer.json' (e.g. 'reddit/explorer/reddit-explorer.json').

	:param datasource, str: Datasource name

	:return: Dictionary of custom fields that should be shown.
	"""

	# Set the directory name of this datasource.
	# Do some conversion for some imageboard names (4chan, 8chan).
	if datasource.startswith("4"):
		datasource_dir = datasource.replace("4", "four")
	elif datasource.startswith("8"):
		datasource_dir = datasource.replace("8", "eight")
	else:
		datasource_dir = datasource

	json_path = Path(config.PATH_ROOT, "datasources", datasource_dir, "explorer", datasource.lower() + "-explorer.json")
	if json_path.exists():
		with open(json_path, "r", encoding="utf-8") as json_file:
			custom_fields = json.load(json_file)
	else:
		custom_fields = None
	return custom_fields

def strip_html(post):
	post["body"] = strip_tags(post.get("body", ""))
	return post

def format(post):
	post["body"] = format_post(post.get("body", "")).replace("\n", "<br>")
	return post