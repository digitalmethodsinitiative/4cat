"""
4CAT Web Tool views - pages to be viewed by the user
"""
import os
import re
import json
import config
import datetime
import markdown

from flask import render_template, jsonify, abort, request, redirect, send_from_directory, flash, get_flashed_messages
from flask_login import login_required, current_user
from webtool import app, db, queue, openapi
from webtool.lib.helpers import Pagination, get_preview

from backend.lib.query import DataSet
from backend.lib.helpers import get_absolute_folder, UserInput, load_postprocessors


@app.template_filter('datetime')
def _jinja2_filter_datetime(date, fmt=None):
	date = datetime.datetime.fromtimestamp(date)
	format = "%d-%m-%Y" if not fmt else fmt
	return date.strftime(format)


@app.template_filter('numberify')
def _jinja2_filter_numberify(number):
	try:
		number = int(number)
	except TypeError:
		return number

	if number > 1000000:
		return str(int(number / 1000000)) + "m"
	elif number > 1000:
		return str(int(number / 1000)) + "k"

	return str(number)


@app.template_filter('markdown')
def _jinja2_filter_markdown(text):
	return markdown.markdown(text)

@app.route("/robots.txt")
def robots():
	with open(os.path.dirname(os.path.abspath(__file__)) + "/static/robots.txt") as robotstxt:
		return robotstxt.read()

@app.route("/access-tokens/")
@login_required
def show_access_tokens():
	user = current_user.get_id()

	if user == "autologin":
		abort(403)

	tokens = db.fetchall("SELECT * FROM access_tokens WHERE name = %s", (user,))

	return render_template("access-tokens.html", tokens=tokens)

@app.route('/')
@login_required
def show_frontpage():
	"""
	Index page: news and introduction

	:return:
	"""

	# load corpus stats that are generated daily, if available
	stats_path = get_absolute_folder(os.path.dirname(__file__)) + "/../stats.json"
	if os.path.exists(stats_path):
		with open(stats_path) as stats_file:
			stats = stats_file.read()
		try:
			stats = json.loads(stats)
		except json.JSONDecodeError:
			stats = None
	else:
		stats = None

	return render_template("frontpage.html", stats=stats, boards=config.PLATFORMS)


@app.route('/tool/')
@login_required
def show_index():
	"""
	Main tool frontend
	"""
	return render_template('tool.html', boards=config.PLATFORMS)


@app.route('/get-boards/<string:platform>/')
@login_required
def getboards(platform):
	if platform not in config.PLATFORMS or "boards" not in config.PLATFORMS[platform]:
		result = False
	else:
		result = config.PLATFORMS[platform]["boards"]

	return jsonify(result)


@app.route('/page/<string:page>/')
def show_page(page):
	"""
	Display a markdown page within the 4CAT UI

	To make adding static pages easier, they may be saved as markdown files
	in the pages subdirectory, and then called via this view. The markdown
	will be parsed to HTML and displayed within the layout template.

	:param page: ID of the page to load, should correspond to a markdown file
	in the pages/ folder (without the .md extension)
	:return:  Rendered template
	"""
	page = re.sub(r"[^a-zA-Z0-9-_]*", "", page)
	page_class = "page-" + page
	page_folder = os.path.dirname(os.path.abspath(__file__)) + "/pages"
	page_path = page_folder + "/" + page + ".md"

	if not os.path.exists(page_path):
		abort(404)

	with open(page_path) as file:
		page_raw = file.read()
		page_parsed = markdown.markdown(page_raw)
		page_parsed = re.sub(r"<h2>(.*)</h2>", r"<h2><span>\1</span></h2>", page_parsed)

	return render_template("page.html", body_content=page_parsed, body_class=page_class, page_name=page)


@app.route('/result/<string:query_file>/')
@login_required
@openapi.endpoint
def get_result(query_file):
	"""
	Get query result file

	:param str query_file:  name of the result file
	:return:  Result file
	:rmime: text/csv
	"""

	# Return localhost URL when debugging locally
	if app.debug:
		return redirect("http://localhost/fourcat/data/" + query_file)
	
	return send_from_directory(query.get_results_path().replace("\\", "/"), query.get_results_path().replace("\\", "/").split("/").pop())

@app.route('/results/', defaults={'page': 1})
@app.route('/results/page/<int:page>/')
@login_required
def show_results(page):
	"""
	Show results overview

	For each result, available analyses are also displayed.

	:return:  Rendered template
	"""
	page_size = 20
	offset = (page - 1) * page_size
	all_results = request.args.get("all_results", False)

	if all_results:
		num_queries = db.fetchone("SELECT COUNT(*) AS num FROM queries WHERE key_parent = ''")["num"]
		queries = db.fetchall("SELECT * FROM queries WHERE key_parent = '' ORDER BY timestamp DESC LIMIT %s OFFSET %s",
							  (page_size, offset))
	else:
		num_queries = \
			db.fetchone("SELECT COUNT(*) AS num FROM queries WHERE key_parent = '' AND parameters::json->>'user' = %s",
						(current_user.get_id(),))["num"]
		queries = db.fetchall(
			"SELECT * FROM queries WHERE key_parent = '' AND parameters::json->>'user' = %s ORDER BY timestamp DESC LIMIT %s OFFSET %s",
			(current_user.get_id(), page_size, offset))

	if not queries and page != 1:
		abort(404)

	pagination = Pagination(page, page_size, num_queries)
	filtered = []
	postprocessors = load_postprocessors()

	for query in queries:
		query["parameters"] = json.loads(query["parameters"])
		query["subqueries"] = []

		subqueries = db.fetchall("SELECT * FROM queries WHERE key_parent = %s ORDER BY timestamp ASC", (query["key"],))
		for subquery in subqueries:
			subquery["parameters"] = json.loads(subquery["parameters"])
			if subquery["type"] not in postprocessors:
				continue
			subquery["postprocessor"] = postprocessors[subquery["type"]]
			query["subqueries"].append(subquery)

		filtered.append(query)

	return render_template("results.html", queries=filtered, pagination=pagination, all_results=all_results)


@app.route('/results/<string:key>/')
@app.route('/results/<string:key>/postprocessors/')
@login_required
def show_result(key):
	"""
	Show result page

	The page contains query details and a download link, but also shows a list
	of finished and available post-processors.

	:param key:  Result key
	:return:  Rendered template
	"""
	try:
		query = DataSet(key=key, db=db)
	except TypeError:
		abort(404)

	# subqueries are not available via a separate page
	if query.key_parent:
		abort(404)

	# load list of post-processors compatible with this query result
	is_postprocessor_running = False

	# show preview
	if query.is_finished() and query.num_rows > 0:
		preview = get_preview(query)
	else:
		preview = None

	# we can either show this view as a separate page or as a bunch of html
	# to be retrieved via XHR
	standalone = "postprocessors" not in request.url
	template = "result.html" if standalone else "result-details-extended.html"
	return render_template(template, preview=preview, query=query, postprocessors=load_postprocessors(),
						   is_postprocessor_running=is_postprocessor_running, messages=get_flashed_messages())

@app.route('/results/<string:key>/postprocessors/queue/<string:postprocessor>/', methods=["GET", "POST"])
@login_required
def queue_postprocessor(key, postprocessor, is_async=False):
	"""
	Queue a new post-processor

	:param str key:  Key of query to queue the post-processor for
	:param str postprocessor:  ID of the post-processor to queue
	:return:  Either a redirect, or a JSON status if called asynchronously
	"""
	if not is_async:
		is_async = request.args.get("async", "no") != "no"

	# cover all bases - can only run postprocessor on "parent" query
	try:
		query = DataSet(key=key, db=db)
	except TypeError:
		if is_async:
			return jsonify({"error": "Not a valid query key."})
		else:
			abort(404)

	# check if post-processor is available for this query
	if postprocessor not in query.postprocessors:
		if is_async:
			return jsonify({"error": "Not a valid post-processor ID"})
		else:
			abort(404)

	# create a query now
	options = {}
	for option in query.postprocessors[postprocessor]["options"]:
		settings = query.postprocessors[postprocessor]["options"][option]
		choice = request.values.get("option-" + option, None)
		options[option] = UserInput.parse(settings, choice)

	analysis = DataSet(parent=query.key, parameters=options, db=db,
						   extension=query.postprocessors[postprocessor]["extension"], type=postprocessor)
	if analysis.is_new:
		# analysis has not been run or queued before - queue a job to run it
		job = queue.add_job(jobtype=postprocessor, remote_id=analysis.key)
		analysis.link_job(job)
		analysis.update_status("Queued")
	else:
		flash("This analysis (%s) is currently queued or has already been run with these parameters." %
			  query.postprocessors[postprocessor]["name"])

	if is_async:
		return jsonify({
			"status": "success",
			"container": query.key + "-sub",
			"key": analysis.key,
			"html": render_template("result-subquery-extended.html", subquery=analysis,
									postprocessors=load_postprocessors()) if analysis.is_new else "",
			"messages": get_flashed_messages()
		})
	else:
		return redirect("/results/" + analysis.top_key() + "/")