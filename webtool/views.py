"""
4CAT Web Tool views - pages to be viewed by the user
"""
import os
import re
import csv
import json
import glob
import config
import markdown

from pathlib import Path

import backend

from flask import render_template, jsonify, abort, request, redirect, send_from_directory, flash, get_flashed_messages
from flask_login import login_required, current_user
from webtool import app, db, queue, openapi
from webtool.lib.helpers import Pagination, get_preview

from backend.lib.dataset import DataSet
from backend.lib.helpers import UserInput

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
	stats_path = Path(config.PATH_ROOT, "stats.json")
	if stats_path.exists():
		with stats_path.open() as stats_file:
			stats = stats_file.read()
		try:
			stats = json.loads(stats)
		except json.JSONDecodeError:
			stats = None
	else:
		stats = None

	return render_template("frontpage.html", stats=stats, datasources=config.DATASOURCES)

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
			"chart_type": "multi-line"
		},
		"bigrams": {
			"type": "two-column",
			"title": "Most-occurring bigrams",
			"chart_type": "multi-line"
		}
	}

	# define graphs: each graph type can have multiple independent graphs,
	# one for each board that is tracked
	graphs = {}
	for type in graph_types:
		data_type = graph_types[type]["type"]
		extension = "csv" if data_type == "two-column" else "txt"

		# files are stored as timestamp-datasource-board-graphtype.csv
		# so we can extract the board names here, as well as sort by filename,
		# which we need because the graph is over-time
		files = sorted(set(glob.glob(config.PATH_SNAPSHOTDATA + "/*-" + type + "." + extension)))
		boards = sorted(set(["-".join(file.split("/")[-1].split("-")[1:-1]) for file in files]))

		data = {}
		times = {}

		# calculate per-board data
		for board in boards:
			# if we match by just the board, "europe" will match both "europe"
			# and "european", but if we sandwich it between dashes it will
			# always match the correct files only
			board_match = "-" + board + "-"
			board_files = [file for file in files if board_match in file]

			if data_type == "two-column":
				data[board] = [csv_to_list(file) for file in board_files]
			else:
				data[board] = [[["posts", int(open_and_read(file).strip())]] for file in board_files]

			# only show last two weeks
			data[board] = data[board][-14:]

			# no data? don't include this, no graph will be available
			if not data[board] or not any([any(item) for item in data[board]]):
				del data[board]
				continue

			times[board] = [int(file.split("/")[-1].split("-")[0]) for file in board_files][-14:]

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

@app.route('/create-dataset/')
@login_required
def show_index():
	"""
	Main tool frontend
	"""
	return render_template('create-dataset.html', datasources=backend.all_modules.datasources)


@app.route('/get-boards/<string:datasource>/')
@login_required
def getboards(datasource):
	if datasource not in config.DATASOURCES or "boards" not in config.DATASOURCES[datasource]:
		result = False
	else:
		result = config.DATASOURCES[datasource]["boards"]

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
	Get dataset result file

	:param str query_file:  name of the result file
	:return:  Result file
	:rmime: text/csv
	"""

	# Return localhost URL when debugging locally
	if app.debug:
		return redirect("http://localhost/fourcat/data/" + query_file)

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

	num_datasets = db.fetchone("SELECT COUNT(*) AS num FROM queries WHERE " + where, tuple(replacements))["num"]

	replacements.append(page_size)
	replacements.append(offset)
	datasets = db.fetchall("SELECT * FROM queries WHERE " + where + " ORDER BY timestamp DESC LIMIT %s OFFSET %s", tuple(replacements))

	if not datasets and page != 1:
		abort(404)

	pagination = Pagination(page, page_size, num_datasets)
	filtered = []
	processors = backend.all_modules.processors

	for dataset in datasets:
		dataset["parameters"] = json.loads(dataset["parameters"])
		dataset["children"] = []

		children = db.fetchall("SELECT * FROM queries WHERE key_parent = %s ORDER BY timestamp ASC", (dataset["key"],))
		for child in children:
			child["parameters"] = json.loads(child["parameters"])
			if child["type"] not in processors:
				continue
			child["processor"] = processors[child["type"]]
			dataset["children"].append(child)

		filtered.append(dataset)

	return render_template("results.html", filter={"filter": query_filter, "all_results": all_results}, queries=filtered, pagination=pagination)


@app.route('/results/<string:key>/')
@app.route('/results/<string:key>/processors/')
@login_required
def show_result(key):
	"""
	Show result page

	The page contains dataset details and a download link, but also shows a list
	of finished and available processors.

	:param key:  Result key
	:return:  Rendered template
	"""
	try:
		dataset = DataSet(key=key, db=db)
	except TypeError:
		abort(404)

	# child datasets are not available via a separate page
	if dataset.key_parent:
		abort(404)

	# load list of processors compatible with this dataset
	is_processor_running = False

	# show preview
	if dataset.is_finished() and dataset.num_rows > 0:
		preview = get_preview(dataset)
	else:
		preview = None

	# we can either show this view as a separate page or as a bunch of html
	# to be retrieved via XHR
	standalone = "processors" not in request.url
	template = "result.html" if standalone else "result-details.html"
	return render_template(template, preview=preview, dataset=dataset, processors=backend.all_modules.processors,
						   is_processor_running=is_processor_running, messages=get_flashed_messages())

@app.route("/preview-csv/<string:key>/")
@login_required
def preview_csv(key):
	"""
	Preview a CSV file

	Simply passes the first 25 rows of a dataset's csv result file to the
	template renderer.

	:param str key:  Dataset key
	:return:  HTML preview
	"""
	try:
		dataset = DataSet(key=key, db=db)
	except TypeError:
		abort(404)

	try:
		with dataset.get_results_path().open(encoding="utf-8") as csvfile:
			rows = []
			reader = csv.reader(csvfile)
			while len(rows) < 25:
				try:
					row = next(reader)
					rows.append(row)
				except StopIteration:
					break
	except FileNotFoundError:
		abort(404)

	return render_template("result-csv-preview.html", rows=rows, filename=dataset.get_results_path().name)

@app.route('/results/<string:key>/processors/queue/<string:processor>/', methods=["GET", "POST"])
@login_required
def queue_processor(key, processor, is_async=False):
	"""
	Queue a new processor

	:param str key:  Key of dataset to queue the processor for
	:param str processor:  ID of the processor to queue
	:return:  Either a redirect, or a JSON status if called asynchronously
	"""
	if not is_async:
		is_async = request.args.get("async", "no") != "no"

	# cover all bases - can only run processor on "parent" dataset
	try:
		dataset = DataSet(key=key, db=db)
	except TypeError:
		if is_async:
			return jsonify({"error": "Not a valid dataset key."})
		else:
			abort(404)

	# check if processor is available for this dataset
	if processor not in dataset.processors:
		if is_async:
			return jsonify({"error": "This processor is not available for this dataset or has already been run."})
		else:
			abort(404)

	# create a dataset now
	options = {}
	for option in dataset.processors[processor]["options"]:
		settings = dataset.processors[processor]["options"][option]
		choice = request.values.get("option-" + option, None)
		options[option] = UserInput.parse(settings, choice)

	analysis = DataSet(parent=dataset.key, parameters=options, db=db,
					   extension=dataset.processors[processor]["extension"], type=processor)
	if analysis.is_new:
		# analysis has not been run or queued before - queue a job to run it
		job = queue.add_job(jobtype=processor, remote_id=analysis.key)
		analysis.link_job(job)
		analysis.update_status("Queued")
	else:
		flash("This analysis (%s) is currently queued or has already been run with these parameters." %
			  dataset.processors[processor]["name"])

	if is_async:
		return jsonify({
			"status": "success",
			"container": dataset.key + "-sub",
			"key": analysis.key,
			"html": render_template("result-child.html", child=analysis, dataset=dataset,
									processors=backend.all_modules.processors) if analysis.is_new else "",
			"messages": get_flashed_messages()
		})
	else:
		return redirect("/results/" + analysis.top_key() + "/")