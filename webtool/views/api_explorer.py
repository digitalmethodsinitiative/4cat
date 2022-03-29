"""
4CAT Data API - endpoints to get post and thread data from
"""

import datetime
import config
import json
import csv
import re
import operator
#import markdown
import markdown2

from backend import all_modules

from collections import OrderedDict
from pathlib import Path

from flask import jsonify, abort, send_file, request, render_template
from flask_login import login_required, current_user

from webtool import app, db, log, openapi, limiter
from webtool.lib.helpers import format_chan_post, error
from common.lib.dataset import DataSet
from common.lib.helpers import strip_tags

api_ratelimit = limiter.shared_limit("45 per minute", scope="api")

@app.route('/explorer/dataset/<string:key>/', defaults={'page': 0})
@app.route('/explorer/dataset/<string:key>/<int:page>')
@api_ratelimit
@openapi.endpoint("explorer")
def explorer_dataset(key, page):
	"""
	Show posts from a specific dataset

	:param str dataset_key:  Dataset key

	:return-schema: {type=array,items={type=integer}}

	:return-error 404: If the dataset does not exist.
	"""

	# Get dataset info.
	try:
		dataset = DataSet(key=key, db=db)
	except TypeError:
		return error(404, error="Dataset not found.")

	if dataset.is_private and not (current_user.is_admin or dataset.owner == current_user.get_id()):
		return error(403, error="This dataset is private.")

	if len(dataset.get_genealogy()) > 1:
		return error(404, error="Exporer only available for top-level datasets")

	results_path = dataset.check_dataset_finished()
	if not results_path:
		return error(404, error="This dataset didn't finish executing (yet)")

	# The amount of posts to show on a page
	limit = config.EXPLORER_POSTS_ON_PAGE if hasattr(config, "EXPLORER_POSTS_ON_PAGE") else 50
	
	# The amount of posts that may be included (limit for large datasets)
	max_posts = config.MAX_EXPLORER_POSTS if hasattr(config, "MAX_EXPLORER_POSTS") else 500000
	
	# The offset for posts depending on the current page
	offset = ((page - 1) * limit) if page else 0

	# Load some variables
	parameters = dataset.get_parameters()
	datasource = parameters["datasource"]
	board = parameters.get("board", "")
	post_count = int(dataset.data["num_rows"])
	annotation_fields = dataset.get_annotation_fields()

	# If the dataset is local, we can add some more features
	# (like the ability to navigate to threads)
	is_local = False
	if datasource in list(all_modules.datasources.keys()):
		is_local = True if all_modules.datasources[datasource].get("is_local") else False
	
	# Check if we have to sort the data in a specific way.
	sort_by = request.args.get("sort")
	if sort_by == "dataset-order":
		sort_by = None
	
	# Check if we have to reverse the order.
	descending = request.args.get("desc")
	if descending == "true" or descending == True:
		descending = True
	else:
		descending = False

	# Check if we have to convert the sort value to an integer.
	force_int = request.args.get("int")
	if force_int == "true" or force_int == True:
		force_int = True
	else:
		force_int = False

	# Load posts
	post_ids = []
	posts = []
	count = 0

	first_post = False
	

	for post in iterate_items(results_path, max_rows=max_posts, sort_by=sort_by, descending=descending, force_int=force_int):
		
		count += 1
		
		# Use an offset if we're showing a page beyond the first.
		if count <= offset:
			continue

		# Use an offset if we're showing a page beyond the first.
		if count <= offset:
			continue

		# Attribute column names and collect dataset's posts.
		post_ids.append(post["id"])
		posts.append(post)

		if "link_id" in post:
			if post["link_id"][2] == "_":
				post["link_id"] = post["link_id"][3:]

		# Stop if we exceed the max posts per page.
		if count >= (offset + limit) or count > max_posts:
			break

	# Include custom css if it exists in the datasource's 'explorer' dir.
	# The file's naming format should e.g. be 'reddit-explorer.css'.
	css = get_custom_css(datasource)

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
	return render_template("explorer/explorer.html", key=key, datasource=datasource, board=board, is_local=is_local, parameters=parameters, annotation_fields=annotation_fields, annotations=annotations, posts=posts, custom_css=css, custom_fields=custom_fields, page=page, offset=offset, limit=limit, post_count=post_count, max_posts=max_posts)

@app.route('/explorer/thread/<datasource>/<board>/<string:thread_id>')
@api_ratelimit
@openapi.endpoint("explorer")
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

	# The amount of posts that may be included (limit for large datasets)
	max_posts = config.MAX_EXPLORER_POSTS if hasattr(config, "MAX_EXPLORER_POSTS") else 500000

	# Get the posts with this thread ID.
	posts = get_posts(db, datasource, board=board, ids=tuple([thread_id]), threads=True, order_by=["id"])

	if not posts:
		return error(404, error="No posts available for this thread")

	posts = [strip_html(post) for post in posts]
	posts = [format(post, datasource=datasource) for post in posts]

	# Include custom css if it exists in the datasource's 'explorer' dir.
	# The file's naming format should e.g. be 'reddit-explorer.css'.
	css = get_custom_css(datasource)

	# Include custom fields if it they are in the datasource's 'explorer' dir.
	# The file's naming format should e.g. be 'reddit-explorer.json'.
	custom_fields = get_custom_fields(datasource)

	return render_template("explorer/explorer.html", datasource=datasource, board=board, posts=posts, custom_css=css, custom_fields=custom_fields, limit=len(posts), post_count=len(posts), thread=thread_id, max_posts=max_posts)

@app.route('/explorer/post/<datasource>/<board>/<string:post_id>')
@api_ratelimit
@openapi.endpoint("explorer")
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
	posts = get_posts(db, datasource, board=board, ids=tuple([thread_id]), threads=True, order_by=["id"])

	posts = [strip_html(post) for post in posts]
	posts = [format(post) for post in posts]

	# Include custom css if it exists in the datasource's 'explorer' dir.
	# The file's naming format should e.g. be 'reddit-explorer.css'.
	css = get_custom_css(datasource)

	# Include custom fields if it they are in the datasource's 'explorer' dir.
	# The file's naming format should e.g. be 'reddit-explorer.json'.
	custom_fields = get_custom_fields(datasource)

	return render_template("explorer/explorer.html", datasource=datasource, board=board, posts=posts, custom_css=css, custom_fields=custom_fields, limit=len(posts), post_count=len(posts))

@app.route("/explorer/save_annotation_fields/<string:key>", methods=["POST"])
@api_ratelimit
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

def iterate_items(in_file, max_rows=None, sort_by=None, descending=False, force_int=False):
	"""
	Loop through both csv and NDJSON files.
	:param in_file, str:		The input file to read.
	:param sort_by, str:		The key that determines the sort order.
	:param descending, bool:	Whether to sort by descending values.
	:param force_int, bool:		Whether the sort value should be converted to an 
								integer.
	"""
	
	suffix = in_file.name.split(".")[-1].lower()

	if suffix == "csv":

		with open(in_file, "r", encoding="utf-8") as dataset_file:
		
			# Sort on date by default
			# Unix timestamp integers are not always saved in the same field.
			reader = csv.reader(dataset_file)
			columns = next(reader)
			if sort_by:
				try:
					# Get index number of sort_by value
					sort_by_index = columns.index(sort_by)

					# Generate reader on the basis of sort_by value
					reader = sorted(reader, key=lambda x: to_float(x[sort_by_index], convert=force_int) if len(x) >= sort_by_index else 0, reverse=descending)
			
				except (ValueError, IndexError) as e:
					pass
			
			for item in reader:

				# Add columns
				item = {columns[i]: item[i] for i in range(len(item))}
				
				yield item

	elif suffix == "ndjson":

		# In this format each line in the file is a self-contained JSON
		# file
		with open(in_file, "r", encoding="utf-8") as dataset_file:

			# Unfortunately we can't easily sort here.
			# We're just looping through the file if no sort is given.
			if not sort_by:
				for line in dataset_file:
					item = json.loads(line)
					yield item
			
			# If a sort order is given explicitly, we're sorting anyway.
			else:
				keys = sort_by.split(".")

				if max_rows:
					for item in sorted([json.loads(line) for i, line in enumerate(dataset_file) if i < max_rows], key=lambda x: to_float(get_nested_value(x, keys), convert=force_int), reverse=descending):
							yield item
				else:
					for item in sorted([json.loads(line) for line in dataset_file], key=lambda x: to_float(get_nested_value(x, keys), convert=force_int), reverse=descending):
							yield item

	return Exception("Can't loop through file with extension %s" % suffix)

def get_posts(db, datasource, ids, board="", threads=False, limit=0, offset=0, order_by=["timestamp"]):

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

def get_custom_css(datasource):
	"""
	Check if there's a custom css file for this dataset.
	If so, return the text.
	Custom css files should be placed in an 'explorer' directory in the the datasource folder and named
	'<datasourcename>-explorer.css' (e.g. 'reddit/explorer/reddit-explorer.css').
	See https://github.com/digitalmethodsinitiative/4cat/wiki/Exploring-and-annotating-datasets for more information.
	
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
		#css = Path(config.PATH_ROOT, "datasources", datasource_dir, "explorer", datasource.lower() + "-explorer.css")
	
	return css

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
	# Do some conversion for some imageboard names (4chan, 8chan).
	if datasource.startswith("4"):
		datasource_dir = datasource.replace("4", "four")
	elif datasource.startswith("8"):
		datasource_dir = datasource.replace("8", "eight")
	elif "facebook" in datasource or "instagram" in datasource:
		datasource_dir = "import-from-tool"
		datasource = "import-from-tool"
	else:
		datasource_dir = datasource

	json_path = Path(config.PATH_ROOT, "datasources", datasource_dir, "explorer", datasource.lower() + "-explorer.json")
	print(json_path)
	if json_path.exists():
		with open(json_path, "r", encoding="utf-8") as json_file:
			try:
				custom_fields = json.load(json_file)
			except ValueError:
				return "invalid"
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

def to_float(value, convert=False):
	if convert:
		if not value:
			value = 0
		else:
			value = float(value)
	return value

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