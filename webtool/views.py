"""
4CAT Web Tool views - pages to be viewed by the user
"""
import os
import re
import csv
import json
import glob
import config
import datetime
import markdown

from urllib.parse import urlencode

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

@app.template_filter("http_query")
def _jinja2_filter_httpquery(data):
	return urlencode(data)


@app.template_filter('markdown')
def _jinja2_filter_markdown(text):
	return markdown.markdown(text)

@app.template_filter('json')
def _jinja2_filter_json(data):
	return json.dumps(data)

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

@app.route("/overview/")
@login_required
def show_overview():
	# some quick helper functions to read the snapshot data with, either as
	# plain text or from a csv
	def open_and_read(file):
		with open(file) as handle:
			return "\n".join(handle.readlines()).strip()

	def csv_to_list(file):
		with open(file) as handle:
			reader = csv.reader(handle)
			try:
				# skip header
				reader.__next__()
			except StopIteration:
				return []
			data = []
			for row in reader:
				data.append(row)

		return data

	# graph configuration here
	# todo: move this to an external file or the database
	graph_types = {
		"countries": {
			"type": "two-column",
			"title": "Overall activity",
			"chart_type": "stacked-bar"
		},
		"neologisms": {
			"type": "two-column",
			"title": "Most-used non-standard words",
			"chart_type": "alluvial"
		}
	}

	# define graphs: each graph type can have multiple independent graphs,
	# one for each board that is tracked
	graphs = {}
	for type in graph_types:
		data_type = graph_types[type]["type"]
		extension = "csv" if data_type == "two-column" else "txt"
		files = set(sorted(glob.glob(config.PATH_SNAPSHOTDATA + "/*-" + type + "." + extension)))
		boards = set(sorted(["-".join(file.split("/")[-1].split("-")[1:-1]) for file in files]))

		data = {}
		times = {}

		# calculate per-board data
		for board in boards:
			if data_type == "two-column":
				items = [csv_to_list(file) for file in files if board in file]

				# potentially this is a list of empty lists, which means we're not interested
				if not [item for item in items if item]:
					continue

				data[board] = items
			else:
				data[board] = [[["posts", int(open_and_read(file).strip())]] for file in files if board in file]

			# only show last two weeks
			data[board] = data[board][0:14]

			# no data? don't include this, no graph will be available
			if not data[board]:
				del data[board]
				continue

			times[board] = [int(file.split("/")[-1].split("-")[0]) for file in files if board in file]

		if not data:
			continue

		# this is the data that will be passed to the template
		graphs[type] = {
			"title": graph_types[type]["title"],
			"data": data,
			"times": times,
			"type": graph_types[type]["chart_type"]
		}

	return render_template("overview.html", graphs=graphs)

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
	query_filter = request.args.get("filter", "")

	where = ["key_parent = ''"]
	replacements = []

	if not all_results:
		where.append("parameters::json->>'user' = %s")
		replacements.append(current_user.get_id())

	if query_filter:
		where.append("query LIKE %s")
		replacements.append("%" + query_filter + "%")

	where = " AND ".join(where)

	num_queries = db.fetchone("SELECT COUNT(*) AS num FROM queries WHERE " + where, tuple(replacements))["num"]

	replacements.append(page_size)
	replacements.append(offset)
	queries = db.fetchall("SELECT * FROM queries WHERE " + where + " ORDER BY timestamp DESC LIMIT %s OFFSET %s", tuple(replacements))

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

	return render_template("results.html", filter={"filter": query_filter, "all_results": all_results}, queries=filtered, pagination=pagination)


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