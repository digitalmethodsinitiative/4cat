"""
4CAT Explorer views - pages that display datasets akin to
the 'native' appearance of the platform they were retrieved from.
"""

import datetime
import json
import csv
import re
import operator
#import markdown
import markdown2

from backend import all_modules

from pathlib import Path

from flask import jsonify, abort, send_file, request, render_template
from flask_login import login_required, current_user

from webtool import app, db, openapi, limiter, config
from webtool.lib.helpers import format_chan_post, error, setting_required
from common.lib.dataset import DataSet
from common.lib.helpers import strip_tags, convert_to_float
from common.lib.exceptions import DataSetException

from common.config_manager import ConfigWrapper
config = ConfigWrapper(config, user=current_user, request=request)
api_ratelimit = limiter.shared_limit("45 per minute", scope="api")

@app.route('/results/<string:key>/explorer/', defaults={'page': 1})
@app.route('/results/<string:key>/explorer/page/<int:page>')
@api_ratelimit
@login_required
@setting_required("privileges.can_use_explorer")
@openapi.endpoint("explorer")
def explorer_dataset(key, page=1):
	"""
	Show posts from a dataset

	:param str dataset_key:  Dataset key

	:return-schema: {type=array,items={type=integer}}

	:return-error 404: If the dataset does not exist.
	"""

	# Get dataset info.
	try:
		dataset = DataSet(key=key, db=db)
	except DataSetException:
		return error(404, error="Dataset not found.")
	
	# Load some variables
	parameters = dataset.get_parameters()
	datasource = parameters["datasource"]
	post_count = int(dataset.data["num_rows"])
	annotation_fields = dataset.get_annotation_fields()

	# See if we can actually serve this page
	if dataset.is_private and not (config.get("privileges.can_view_all_datasets") or dataset.is_accessible_by(current_user)):
		return error(403, error="This dataset is private.")

	if len(dataset.get_genealogy()) > 1:
		return error(404, error="Only available for top-level datasets.")

	results_path = dataset.check_dataset_finished()
	if not results_path:
		return error(404, error="This dataset didn't finish executing.")

	if not config.get("explorer.config", {}).get(datasource,{}).get("enabled"):
		return error(404, error="Explorer functionality disabled for %s." % datasource)

	datasource_config = config.get("explorer.config", {}).get(datasource,{})

	# The amount of posts to show on a page
	posts_per_page = config.get("explorer.posts_per_page", 50)

	# The amount of posts that may be included (limit for large datasets)
	max_posts = config.get('explorer.max_posts', 500000)

	# The offset for posts depending on the current page
	offset = ((page - 1) * posts_per_page) if page else 0

	# If the dataset is generated from an API-accessible database, we can add 
	# extra features like the ability to navigate across posts.
	has_database = False # INTEGRATE LATER /////////////////////

	# Check if we have to sort the data.
	sort = request.args.get("sort")
	if sort == "dataset-order":
		sort = None

	# Check if we have to reverse the order.
	reverse = True if request.args.get("order") == "reverse" else False

	# Load posts
	post_ids = []
	posts = []
	count = 0

	# If we're sorting, we need to iterate over the entire
	# dataset first. Else we can simply use `iterate_items`.
	if not sort:
		for row in dataset.iterate_items(warn_unmappable=False):

			count += 1

			# Use an offset if we're showing a page beyond the first.
			if count <= offset:
				continue

			# Attribute column names and collect dataset's posts.
			post_ids.append(row["id"])
			posts.append(row)

			# Stop if we exceed the allowed posts per page or max posts.
			if count >= (offset + posts_per_page) or count > max_posts:
				break
	else:
		for row in sort_and_iterate_items(dataset, sort, reverse=reverse, warn_unmappable=False):
			count += 1
			if count <= offset:
				continue
			post_ids.append(row["id"])
			posts.append(row)
			if count >= (offset + posts_per_page) or count > max_posts:
				break

	# Include custom fields if it they are in the datasource's 'explorer' dir.
	# The file's naming format should e.g. be 'reddit-explorer.json'.
	# For some datasources (e.g. Twitter) we also have to explicitly set
	# what data type we're working with.
	filetype = dataset.get_extension()
	custom_fields = get_custom_fields(datasource, filetype=filetype)

	# Convert posts from markdown to HTML
	if custom_fields and "markdown" in custom_fields and custom_fields.get("markdown"):
		posts = [convert_markdown(post) for post in posts]
	# Clean up HTML
	else:
		posts = [strip_html(post) for post in posts]
		posts = [format(post, datasource=datasource) for post in posts]

	if not posts:
		return error(404, error="No posts available for this datasource")

	# Check whether there's already annotations inserted already.
	# If so, also pass these to the template.
	annotations = db.fetchone("SELECT * FROM annotations WHERE key = %s", (key,))
	if not annotations or not annotations.get("annotations"):
		annotations = None
	else:
		annotations = json.loads(annotations["annotations"])

	# Generate the HTML page
	return render_template("explorer/explorer.html", dataset=dataset, datasource=datasource, has_database=has_database, parameters=parameters, posts=posts, annotation_fields=annotation_fields, annotations=annotations, datasource_config=datasource_config, custom_fields=custom_fields, page=page, offset=offset, posts_per_page=posts_per_page, post_count=post_count, max_posts=max_posts)

@app.route('/results/<datasource>/<string:thread_id>/explorer')
@api_ratelimit
@login_required
@setting_required("privileges.can_use_explorer")
@openapi.endpoint("explorer")
def explorer_database_thread(datasource, board, thread_id):
	"""
	Show a thread from an API-accessible database.

	:param str datasource:  Data source ID
	:param str board:  Board name
	:param int thread_id:  Thread ID

	:return-error 404:  If the thread ID does not exist for the given data source.
	"""

	if not datasource:
		return error(404, error="No datasource provided")
	if datasource not in config.get('datasources.enabled'):
		return error(404, error="Invalid data source")
	if not board:
		return error(404, error="No board provided")
	if not thread_id:
		return error(404, error="No thread ID provided")

	# The amount of posts that may be included (limit for large datasets)
	max_posts = config.get('explorer.max_posts', 500000)

	# Get the posts with this thread ID.
	posts = get_local_posts(db, datasource, board=board, ids=tuple([thread_id]), threads=True, order_by=["id"])

	if not posts:
		return error(404, error="No posts available for this thread")

	posts = [strip_html(post) for post in posts]
	posts = [format(post, datasource=datasource) for post in posts]

	# Include custom fields if it they are in the datasource's 'explorer' dir.
	# The file's naming format should e.g. be 'reddit-explorer.json'.
	custom_fields = get_custom_fields(datasource)

	return render_template("explorer/explorer.html", datasource=datasource, board=board, posts=posts, datasource_config=datasource_config, custom_fields=custom_fields, posts_per_page=len(posts), post_count=len(posts), thread=thread_id, max_posts=max_posts)

@app.route('/explorer/post/<datasource>/<board>/<string:post_id>')
@api_ratelimit
@login_required
@setting_required("privileges.can_use_explorer")
@openapi.endpoint("explorer")
def explorer_database_posts(datasource, board, thread_id):
	"""
	Show posts from an API-accessible database.

	:param str datasource:  Data source ID
	:param str board:  Board name
	:param int thread_id:  Thread ID

	:return-error 404:  If the thread ID does not exist for the given data source.
	"""

	if not datasource:
		return error(404, error="No datasource provided")
	if datasource not in config.get('datasources.enabled'):
		return error(404, error="Invalid data source")
	if not board:
		return error(404, error="No board provided")
	if not thread_id:
		return error(404, error="No thread ID provided")

	# Get the posts with this thread ID.
	posts = get_database_posts(db, datasource, board=board, ids=tuple([thread_id]), threads=True, order_by=["id"])

	posts = [strip_html(post) for post in posts]
	posts = [format(post) for post in posts]

	# Include custom fields if it they are in the datasource's 'explorer' dir.
	# The file's naming format should e.g. be 'reddit-explorer.json'.
	custom_fields = get_custom_fields(datasource)

	return render_template("explorer/explorer.html", datasource=datasource, board=board, posts=posts, datasource_config=datasource_config, custom_fields=custom_fields, posts_per_page=len(posts), post_count=len(posts))

@app.route("/explorer/save_annotation_fields/<string:key>", methods=["POST"])
@api_ratelimit
@login_required
@setting_required("privileges.can_run_processors")
@setting_required("privileges.can_use_explorer")
@openapi.endpoint("explorer")
def save_annotation_fields(key):
	"""
	Save the annotation fields of a dataset to the datasets table.
	If the changes to the annotation fields affect existing annotations,
	this function also updates or deleted those old values.

	:param str key:  The dataset key

	:return-error 404:  If the dataset ID does not exist.
	"""

	if not key:
		return error(404, error="No dataset key provided")

	# Do some preperations
	new_fields = request.get_json()
	new_field_ids = set(new_fields.keys())
	text_fields = ["textarea", "text"]
	option_fields = set()

	# Get dataset info.
	dataset = db.fetchone("SELECT key, annotation_fields FROM datasets WHERE key = %s;", (key,))

	if not dataset:
		return error(404, error="Dataset not found")

	# We're saving the annotation fields as-is
	db.execute("UPDATE datasets SET annotation_fields = %s WHERE key = %s;", (json.dumps(new_fields), key))

	# If fields and annotations were saved before, we must also check whether we need to
	# change old annotation data, for instance when a field is deleted or its label has changed.

	# Get the annotation fields that were already saved to check what's changed.
	old_fields = dataset.get("annotation_fields")
	if old_fields:
		old_fields = json.loads(old_fields)

	# Get the annotations
	if old_fields:
		annotations = db.fetchone("SELECT annotations FROM annotations WHERE key = %s;", (key,))
		if annotations and "annotations" in annotations:
			if not annotations["annotations"]:
				annotations = None
			else:
				annotations = json.loads(annotations["annotations"])

	# If there's old fields *and* annotations saved, we need to check if we need to update stuff.
	if old_fields and annotations:

		fields_to_delete = set()
		labels_to_update = {}
		options_to_delete = set()
		options_to_update = {}

		for field_id, field in old_fields.items():

			# We'll delete all prior annotations for a field if its input field is deleted
			if field_id not in new_field_ids:

				# Labels are used as keys in the annotations table
				# They should already be unique, so that's okay.
				fields_to_delete.add(field["label"])
				continue

			# If the type has changed, also delete prior references (except between text and textarea)
			new_type = new_fields[field_id]["type"]
			if field["type"] != new_type:

				if not field["type"] in text_fields and not new_type in text_fields:
					fields_to_delete.add(field["label"])
					continue

			# If the label has changed, change it in the old annotations
			old_label = old_fields[field_id]["label"]
			new_label = new_fields[field_id]["label"]

			if old_label != new_label:
				labels_to_update[old_label] = new_label

			# Check if the options for dropdowns or checkboxes have changed
			if new_type == "checkbox" or new_type == "dropdown":

				if "options" in old_fields[field_id]:

					option_fields.add(old_fields[field_id]["label"])
					new_options = new_fields[field_id]["options"]

					new_ids = [list(v.keys())[0] for v in new_options]
					new_ids = [list(v.keys())[0] for v in new_options]

					# If it's a dropdown or checkbox..
					for option in old_fields[field_id]["options"]:
						option_id = list(option.keys())[0]
						option_label = list(option.values())[0]

						# If this ID is not present anymore, delete it
						if option_id not in new_ids:
							options_to_delete.add(option_label)
							continue

						# Change the label if it has changed. Bit ugly but it works.
						new_label = [list(new_option.values())[0] for i, new_option in enumerate(new_options) if list(new_options[i].keys())[0] == option_id][0]

						if option_label != new_label:
							options_to_update[option_label] = new_label

		# Loop through the old annotations if things need to be changed
		if fields_to_delete or labels_to_update or options_to_update or options_to_delete:

			for post_id in list(annotations.keys()):

				for field_label in list(annotations[post_id].keys()):

					# Delete the field entirely
					if field_label in fields_to_delete:
						del annotations[post_id][field_label]
						continue

					# Update the label
					if field_label in labels_to_update:
						annotations[post_id][labels_to_update[field_label]] = annotations[post_id].pop(field_label)
						field_label = labels_to_update[field_label]

					# Update or delete option values
					if field_label in option_fields:
						options_inserted = annotations[post_id][field_label]

						# We can just delete/change the entire annotation if its a string
						if type(options_inserted) == str:

							# Delete the option if it's not present anymore
							if options_inserted in options_to_delete:
								del annotations[post_id][field_label]

							# Update the option label if it has changed
							elif options_inserted in options_to_update:
								annotations[post_id][field_label] = options_to_update[options_inserted]

						# For lists (i.e. checkboxes), we have to loop
						elif type(options_inserted) == list:

							for option_inserted in options_inserted:

								# Delete the option if it's not present anymore
								if option_inserted in options_to_delete:
									annotations[post_id][field_label].remove(option_inserted)

								# Update the option label if it has changed
								elif option_inserted in options_to_update:
									annotations[post_id][field_label] = options_to_update[option_inserted]

				# Delete entire post dict if there's nothing left
				if not annotations[post_id]:
					del annotations[post_id]

			# Save annotations as an empty string if there's none.
			if not annotations:
				annotations = ""
			else:
				annotations = json.dumps(annotations)

			# Insert into the annotations table.
			db.execute("INSERT INTO annotations(key, annotations) VALUES(%s, %s) ON CONFLICT (key) DO UPDATE SET annotations = %s ", (key, annotations, annotations))

	return "success"

@app.route("/explorer/save_annotations/<string:key>", methods=["POST"])
@api_ratelimit
@login_required
@setting_required("privileges.can_run_processors")
@setting_required("privileges.can_use_explorer")
@openapi.endpoint("explorer")
def save_annotations(key):
	"""
	Save the annotations of a dataset to the annotations table.

	:param str key:  The dataset key

	:return-error 404:  If the dataset ID does not exist.
	"""

	if not key:
		return error(404, error="No dataset key provided")

	new_annotations = request.get_json()

	# If there were already annotations added, we need to make sure
	# we're not incorrectly overwriting any.
	# We also need to check whether any of the input fields have changed.
	# If so, we're gonna edit or remove their old values.
	old_annotations = db.fetchone("SELECT annotations FROM annotations WHERE key = %s;", (key,))

	if old_annotations:

		if "annotations" in old_annotations and old_annotations["annotations"]:
			old_annotations = json.loads(old_annotations["annotations"])

			# Loop through all new annotations and add/overwrite them
			# with the old annotations dict.
			for post_id in list(new_annotations.keys()):
				old_annotations[post_id] = new_annotations[post_id]
				if not old_annotations[post_id]:
					del old_annotations[post_id]

			new_annotations = old_annotations

	if not new_annotations:
		new_annotations = ""
	else:
		new_annotations = json.dumps(new_annotations)

	# We're saving all annotations as a JSON string in one go
	db.execute("INSERT INTO annotations(key, annotations) VALUES(%s, %s) ON CONFLICT (key) DO UPDATE SET annotations = %s ", (key, new_annotations, new_annotations))

	return "success"

@app.route('/api/<datasource>/boards.json')
@api_ratelimit
@login_required
@setting_required("privileges.can_use_explorer")
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
	if datasource not in config.get('datasources.enabled'):
		return error(404, error="Invalid data source")

	boards = db.fetchall("SELECT DISTINCT board FROM threads_" + datasource)
	return jsonify({"boards": [{"board": board["board"]} for board in boards]})

@app.route('/api/image/<img_file>')
@app.route('/api/imagefile/<img_file>')
@login_required
@setting_required("privileges.can_use_explorer")
def get_image_file(img_file):
	"""
	Returns an image based on filename
	Request should hex the md5 hashes first (e.g. with hexdigest())

	"""
	if not re.match(r"([a-zA-Z0-9]+)\.([a-z]+)", img_file):
		abort(404)

	image_path = Path(config.get('PATH_ROOT'), config.get('PATH_IMAGES'), img_file)
	if not image_path.exists():
		abort(404)

	return send_file(str(image_path))

def sort_and_iterate_items(dataset, sort=None, reverse=False, **kwargs):
	"""
	Loop through both csv and NDJSON files.
	This is basically a wrapper function for `iterate_items()` with the
	added functionality of sorting a dataset. Because the Explorer is (currently)
	the only feature that requires sorting, we define it here.
	This first iterates through the entire file (with a max limit) to determine
	an order. Then it yields items based on this order.

	:param key, str:			The dataset object.
	:param sort_by, str:		The item key that determines the sort order.
	:param reverse, bool:		Whether to sort by largest values first.
	"""

	# Storing posts in the right order here
	sorted_posts = []

	try:
		for item in sorted(dataset.iterate_items(**kwargs), key=lambda x: x[sort], reverse=reverse):
			sorted_posts.append(item)
	except TypeError:
		# Dataset fields can contain integers and empty strings.
		# Since these cannot be compared, we will convert every
		# empty string to 0.
		for item in sorted(dataset.iterate_items(**kwargs), key=lambda x: convert_to_float(x[sort]), reverse=reverse):
			sorted_posts.append(item)

	for post in sorted_posts:
		yield post

def get_database_posts(db, datasource, ids, board="", threads=False, limit=0, offset=0, order_by=["timestamp"]):
	"""
	Retrieve posts by ID from a database-accessible data source.
	"""

	if not ids:
		return None

	if board:
		board = " AND board = '" + board + "' "

	id_field = "id" if not threads else "thread_id"
	order_by = " ORDER BY " + ", ".join(order_by)
	limit = "" if not limit or limit <= 0 else " LIMIT %i" % int(limit)
	offset = " OFFSET %i" % int(offset)

	posts = db.fetchall("SELECT * FROM posts_" + datasource + " WHERE " + id_field + " IN %s " + board + order_by + " ASC" + limit + offset,
						(ids,))
	if not posts:
		return False

	return posts

def get_custom_fields(datasource, filetype=None):
	"""
	Check if there are custom fields that need to be showed for this datasource.
	If so, return a dictionary of those fields.
	Custom field json files should be placed in an 'explorer' directory in the the datasource folder and named
	'<datasourcename>-explorer.json' (e.g. 'reddit/explorer/reddit-explorer.json').
	See https://github.com/digitalmethodsinitiative/4cat/wiki/Exploring-and-annotating-datasets for more information.

	:param datasource, str: Datasource name
	:param filetype, str:	The filetype that is handled. This can fluctuate
							between e.g. NDJSON and csv files.

	:return: Dictionary of custom fields that should be shown.
	"""

	# Set the directory name of this datasource.
	if datasource == "twitter":
		datasource_dir = "twitter-import"
		datasource = "twitter-import"
	else:
		datasource_dir = datasource

	json_path = Path(config.get('PATH_ROOT'), "datasources", datasource_dir, "explorer", datasource.lower() + "-explorer.json")
	read = False

	if json_path.exists():
		read = True
	else:
		# Allow both hypens and underscores in datasource name (to avoid some legacy issues)
		json_path = re.sub(datasource, datasource.replace("-", "_"), str(json_path.absolute()))
		if Path(json_path).exists():
			read = True
	
	if read:
		with open(json_path, "r", encoding="utf-8") as json_file:
			try:
				custom_fields = json.load(json_file)
			except ValueError as e:
				return ("invalid", e)
	else:
		custom_fields = None

	filetype = filetype.replace(".", "")
	if filetype and custom_fields:
		if filetype in custom_fields:
			custom_fields = custom_fields[filetype]
	else:
		custom_fields = None
		
	return custom_fields

def get_nested_value(di, keys):
	"""
	Gets a nested value on the basis of a dictionary and a list of keys.
	"""

	for key in keys:
		di = di.get(key)
		if not di:
			return 0
	return di

def strip_html(post):
	post["body"] = strip_tags(post.get("body", ""))
	return post

def format(post, datasource=""):
	if "chan" in datasource or datasource == "8kun":
		post["body"] = format_chan_post(post.get("body", ""))
	post["body"] = post.get("body", "").replace("\n", "<br>")
	return post

def convert_markdown(post):
	post["body"] = post.get("body", "").replace("\n", "\n\n").replace("&gt;", ">").replace("] (", "](")
	post["body"] = markdown2.markdown(post.get("body", ""), extras=["nofollow","target-blank-links"])
	return post
