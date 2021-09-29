"""
4CAT Web Tool views - pages to be viewed by the user
"""
import io
import os
import re
import csv
import json
import glob
import config
import markdown

from pathlib import Path

import backend

from flask import render_template, jsonify, abort, request, redirect, send_from_directory, flash, get_flashed_messages, \
	url_for, stream_with_context
from flask_login import login_required, current_user

from webtool import app, db, log
from webtool.lib.helpers import Pagination, error

from webtool.api_tool import delete_dataset, toggle_favourite, queue_processor

from common.lib.dataset import DataSet
from common.lib.queue import JobQueue

csv.field_size_limit(1024 * 1024 * 1024)

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

	news_path = Path(config.PATH_ROOT, "news.json")
	if news_path.exists():
		with news_path.open() as news_file:
			news = news_file.read()
		try:
			news = json.loads(news)
			for item in news:
				if "time" not in item or "text" not in item:
					raise RuntimeError()
		except (json.JSONDecodeError, RuntimeError):
			news = None
	else:
		news = None

	datasources = backend.all_modules.datasources


	return render_template("frontpage.html", stats=stats, news=news, datasources=datasources)


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

	with open(page_path, encoding="utf-8") as file:
		page_raw = file.read()
		page_parsed = markdown.markdown(page_raw)
		page_parsed = re.sub(r"<h2>(.*)</h2>", r"<h2><span>\1</span></h2>", page_parsed)

		if config.ADMIN_EMAILS:
			# replace this one explicitly instead of doing a generic config
			# filter, to avoid accidentally exposing config values
			admin_email = config.ADMIN_EMAILS[0] if config.ADMIN_EMAILS else "4cat-admin@example.com"
			page_parsed = page_parsed.replace("%%ADMIN_EMAIL%%", admin_email)

	return render_template("page.html", body_content=page_parsed, body_class=page_class, page_name=page)


@app.route('/result/<string:query_file>/')
def get_result(query_file):
	"""
	Get dataset result file

	:param str query_file:  name of the result file
	:return:  Result file
	:rmime: text/csv
	"""
	directory = config.PATH_ROOT + "/" + config.PATH_DATA
	return send_from_directory(directory=directory, filename=query_file)


@app.route('/mapped-result/<string:key>/')
@login_required
def get_mapped_result(key):
	"""
	Get mapped result

	Some result files are not CSV files. CSV is such a central file format that
	it is worth having a generic 'download as CSV' function for these. If the
	processor of the dataset has a method for mapping its data to CSV, then this
	route uses that to convert the data to CSV on the fly and serve it as such.

	:param str key:  Dataset key
	"""
	try:
		dataset = DataSet(key=key, db=db)
	except TypeError:
		abort(404)

	if dataset.get_extension() == ".csv":
		# if it's already a csv, just return the existing file
		return url_for(get_result, query_file=dataset.get_results_path().name)

	if not hasattr(dataset.get_own_processor(), "map_item"):
		# cannot map without a mapping method
		abort(404)

	mapper = dataset.get_own_processor().map_item

	def map_response():
		"""
		Yield a CSV file line by line

		Pythons built-in csv library, which we use, has no real concept of
		this, so we cheat by using a StringIO buffer that we flush and clear
		after each CSV line is written to it.
		"""
		writer = None
		buffer = io.StringIO()
		with dataset.get_results_path().open() as infile:
			for line in infile:
				mapped_item = mapper(json.loads(line))
				if not writer:
					writer = csv.DictWriter(buffer, fieldnames=tuple(mapped_item.keys()))
					writer.writeheader()
					yield buffer.getvalue()
					buffer.truncate(0)
					buffer.seek(0)

				writer.writerow(mapped_item)
				yield buffer.getvalue()
				buffer.truncate(0)
				buffer.seek(0)

	disposition = 'attachment; filename="%s"' % dataset.get_results_path().with_suffix(".csv").name
	return app.response_class(stream_with_context(map_response()), mimetype="text/csv", headers={"Content-Disposition": disposition})

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

	where = ["(key_parent = '' OR key_parent IS NULL)"]
	replacements = []

	query_filter = request.args.get("filter", "")

	depth = request.args.get("depth", "own")
	if depth not in ("own", "favourites", "all"):
		depth = "own"

	if depth == "own":
		where.append("parameters::json->>'user' = %s")
		replacements.append(current_user.get_id())

	if depth == "favourites":
		where.append("key IN ( SELECT key FROM users_favourites WHERE name = %s )")
		replacements.append(current_user.get_id())

	if query_filter:
		where.append("query LIKE %s")
		replacements.append("%" + query_filter + "%")

	where = " AND ".join(where)

	num_datasets = db.fetchone("SELECT COUNT(*) AS num FROM datasets WHERE " + where, tuple(replacements))["num"]

	replacements.append(page_size)
	replacements.append(offset)
	datasets = db.fetchall("SELECT key FROM datasets WHERE " + where + " ORDER BY timestamp DESC LIMIT %s OFFSET %s",
						   tuple(replacements))

	if not datasets and page != 1:
		abort(404)

	pagination = Pagination(page, page_size, num_datasets)
	filtered = []

	for dataset in datasets:
		filtered.append(DataSet(key=dataset["key"], db=db))

	favourites = [row["key"] for row in
				  db.fetchall("SELECT key FROM users_favourites WHERE name = %s", (current_user.get_id(),))]

	return render_template("results.html", filter={"filter": query_filter}, depth=depth, datasets=filtered,
						   pagination=pagination, favourites=favourites)


@app.route('/results/<string:key>/processors/')
@app.route('/results/<string:key>/')
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

	# child datasets are not available via a separate page - redirect to parent
	if dataset.key_parent:
		genealogy = dataset.get_genealogy()
		nav = ",".join([family.key for family in genealogy])
		url = "/results/%s/#nav=%s" % (genealogy[0].key, nav)
		return redirect(url)

	# load list of processors compatible with this dataset
	is_processor_running = False

	is_favourite = (db.fetchone("SELECT COUNT(*) AS num FROM users_favourites WHERE name = %s AND key = %s",
								(current_user.get_id(), dataset.key))["num"] > 0)

	# if the datasource is configured for it, this dataset may be deleted at some point
	datasource = dataset.parameters.get("datasource", "")
	if datasource in backend.all_modules.datasources and backend.all_modules.datasources[datasource].get("expire-datasets", None):
		timestamp_expires = dataset.timestamp + int(backend.all_modules.datasources[datasource].get("expire-datasets"))
	else:
		timestamp_expires = None

	# we can either show this view as a separate page or as a bunch of html
	# to be retrieved via XHR
	standalone = "processors" not in request.url
	template = "result.html" if standalone else "result-details.html"

	return render_template(template, dataset=dataset, parent_key=dataset.key, processors=backend.all_modules.processors,
						   is_processor_running=is_processor_running, messages=get_flashed_messages(),
						   is_favourite=is_favourite, timestamp_expires=timestamp_expires)


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
		return error(404, "Dataset not found.")

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


@app.route("/result/<string:key>/toggle-favourite/")
@login_required
def toggle_favourite_interactive(key):
	"""
	Toggle dataset 'favourite' status

	Uses code from corresponding API endpoint, but redirects to a normal page
	rather than returning JSON as the API does, so this can be used for
	'normal' links.

	:param str key:  Dataset key
	:return:
	"""
	success = toggle_favourite(key)
	if not success.is_json:
		return success

	if success.json["success"]:
		if success.json["favourite_status"]:
			flash("Dataset added to favourites.")
		else:
			flash("Dataset removed from favourites.")

		return redirect("/results/" + key + "/")
	else:
		return render_template("error.html", message="Error while toggling favourite status for dataset %s." % key)


@app.route("/result/<string:key>/restart/")
@login_required
def restart_dataset(key):
	"""
	Run a dataset's query again

	Deletes all underlying datasets, marks dataset as unfinished, and queues a
	job for it.

	:param str key:  Dataset key
	:return:
	"""
	try:
		dataset = DataSet(key=key, db=db)
	except TypeError:
		return error(404, message="Dataset not found.")

	if current_user.get_id() != dataset.parameters.get("user", "") and not current_user.is_admin:
		return error(403, message="Not allowed.")

	if not dataset.is_finished():
		return render_template("error.html", message="This dataset is not finished yet - you cannot re-run it.")

	if "type" not in dataset.parameters:
		return render_template("error.html",
							   message="This is an older dataset that unfortunately lacks the information necessary to properly restart it.")

	for child in dataset.children:
		child.delete()

	dataset.unfinish()
	queue = JobQueue(logger=log, database=db)
	queue.add_job(jobtype=dataset.parameters["type"], remote_id=dataset.key)

	flash("Dataset queued for re-running.")
	return redirect("/results/" + dataset.key + "/")


@app.route("/result/<string:key>/delete/")
@login_required
def delete_dataset_interactive(key):
	"""
	Delete dataset

	Uses code from corresponding API endpoint, but redirects to a normal page
	rather than returning JSON as the API does, so this can be used for
	'normal' links.

	:param str key:  Dataset key
	:return:
	"""
	try:
		dataset = DataSet(key=key, db=db)
	except TypeError:
		return error(404, message="Dataset not found.")

	top_key = dataset.top_parent().key

	success = delete_dataset(key)

	if not success.is_json:
		return success
	else:
		# If it's a child processor, refresh the page.
		# Else go to the results overview page.
		if key == top_key:
			return redirect(url_for('show_results'))
		else:
			return redirect(url_for('show_result', key=top_key))


@app.route('/results/<string:key>/processors/queue/<string:processor>/', methods=["GET", "POST"])
@login_required
def queue_processor_interactive(key, processor):
	"""
	Queue a new processor

	:param str key:  Key of dataset to queue the processor for
	:param str processor:  ID of the processor to queue
	:return:  Either a redirect, or a JSON status if called asynchronously
	"""
	result = queue_processor(key, processor)

	if not result.is_json:
		return result

	if result.json["status"] == "success":
		return redirect("/results/" + key + "/")
