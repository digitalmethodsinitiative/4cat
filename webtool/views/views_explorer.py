"""
4CAT Explorer views - pages that display datasets in a legible
format and lets users annotate the data.
"""

from pathlib import Path

from flask import request, render_template, jsonify
from flask_login import login_required, current_user
from webtool import app, db, openapi, limiter, config, fourcat_modules
from webtool.lib.helpers import error, setting_required
from common.lib.dataset import DataSet
from common.lib.helpers import convert_to_float, hash_to_md5
from common.lib.exceptions import DataSetException, AnnotationException
from common.config_manager import ConfigWrapper

config = ConfigWrapper(config, user=current_user, request=request)
api_ratelimit = limiter.shared_limit("45 per minute", scope="api")


@app.route("/results/<string:dataset_key>/explorer/", defaults={"page": 1})
@app.route("/results/<string:dataset_key>/explorer/page/<int:page>")
@api_ratelimit
@login_required
@setting_required("privileges.can_use_explorer")
@openapi.endpoint("explorer")
def explorer_dataset(dataset_key: str, page=1):
	"""
	Show items from a dataset

	:param str dataset_key:		Dataset key
	:param str page:			Page number
	:return-schema: {type=array,items={type=integer}}

	:return-error 404: If the dataset does not exist.
	"""

	# Get dataset info.
	try:
		dataset = DataSet(key=dataset_key, db=db, modules=fourcat_modules)
	except DataSetException:
		return error(404, error="Dataset not found.")
	
	# Load some variables
	parameters = dataset.get_parameters()
	datasource = parameters["datasource"]
	post_count = int(dataset.data["num_rows"])
	annotation_fields = dataset.get_annotation_fields()
	warning = ""

	# See if we can actually serve this page
	if dataset.is_private and not (config.get("privileges.can_view_all_datasets") or dataset.is_accessible_by(current_user)):
		return error(403, error="This dataset is private.")

	if len(dataset.get_genealogy()) > 1:
		return error(404, error="Only available for top-level datasets.")

	results_path = dataset.check_dataset_finished()
	if not results_path:
		return error(404, error="This dataset didn't finish executing.")

	# The amount of posts to show on a page
	posts_per_page = config.get("explorer.posts_per_page", 50)

	# The amount of posts that may be included (limit for large datasets)
	max_posts = config.get('explorer.max_posts', 500000)

	# The offset for posts depending on the current page
	offset = ((int(page) - 1) * posts_per_page) if page else 0

	# Check if we have to sort the data.
	sort = request.args.get("sort")

	# Check if we have to reverse the order.
	reverse = True if request.args.get("order") == "reverse" else False

	# Load posts
	post_ids = []
	posts = []
	count = 0

	# We don't need to sort if we're showing the existing dataset order (default).
	# If we're sorting, we need to iterate over the entire dataset first.
	if not sort or (sort == "dataset-order" and not reverse):
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

	if not posts:
		return error(404, error="No posts or posts could not be displayed")

	# Check whether there's already annotations made for these posts.
	# We're not using `get_annotations()` because we don't need *all* annotations.
	# If there's annotations made, pass these to the template and set the post ID
	# as key so we can easily retrieve them later.
	post_annotations = {}
	for post_id in post_ids:
		annotations = dataset.get_annotations_for_item(post_id)
		post_annotations[post_id] = [a for a in annotations if a]

	# We can use either a generic or a pre-made, data source-specific template.
	template = "datasource" if has_datasource_template(datasource) else "generic"
	if template == "generic":
		posts_css = Path(config.get('PATH_ROOT'), "webtool/static/css/explorer/generic.css")
	else:
		posts_css = Path(config.get('PATH_ROOT'), "webtool/static/css/explorer/" + datasource + ".css")

	# Read CSS and pass as a string
	with open(posts_css, "r", encoding="utf-8") as css:
		posts_css = css.read()

	# Generate the HTML page
	return render_template(
		"explorer/explorer.html",
		dataset=dataset,
		datasource=datasource,
		posts=posts,
		annotation_fields=annotation_fields,
		annotations=post_annotations,
		template=template,
		posts_css=posts_css,
		page=page,
		offset=offset,
		posts_per_page=posts_per_page,
		post_count=post_count,
		max_posts=max_posts,
		warning=warning
	)

@app.route("/explorer/save_annotation_fields/<string:dataset_key>", methods=["POST"])
@api_ratelimit
@login_required
@setting_required("privileges.can_run_processors")
@setting_required("privileges.can_use_explorer")
@openapi.endpoint("explorer")
def explorer_save_annotation_fields(dataset_key: str):
	"""
	Save the annotation fields of a dataset to the datasets table.

	:param dataset_key:  		The dataset key.

	:return-error 404:  If the dataset ID does not exist.
	:return int:		The number of annotation fields saved.
	"""

	# Get dataset.
	if not dataset_key:
		return error(404, error="No dataset key provided")
	try:
		dataset = DataSet(key=dataset_key, db=db)
	except DataSetException:
		return error(404, error="Dataset not found.")

	# Save it!
	annotation_fields = request.get_json()

	# Field IDs are not immediately set in the front end.
	# We're going to do this based on the hash of the
	# dataset key and the input label (should be unique)
	field_keys = list(annotation_fields.keys())
	for field_id in field_keys:
		if "tohash" in field_id:
			new_field_id = hash_to_md5(dataset_key + annotation_fields[field_id]["label"])
			annotation_fields[new_field_id] = annotation_fields[field_id]
			del annotation_fields[field_id]

	try:
		fields_saved = dataset.save_annotation_fields(annotation_fields)
	except AnnotationException as e:
		# If anything went wrong with the annotation field saving, return an error.
		return jsonify(error=str(e)), 400

	# Else return the amount of fields saved.
	return str(fields_saved)

@app.route("/explorer/save_annotations/<string:dataset_key>", methods=["POST"])
@api_ratelimit
@login_required
@setting_required("privileges.can_run_processors")
@setting_required("privileges.can_use_explorer")
@openapi.endpoint("explorer")
def explorer_save_annotations(dataset_key: str):
	"""
	Save the annotations of a dataset to the annotations table.

	:param dataset_key:	  	The dataset key. Must be explicitly given to ensure
							annotations are tied to a dataset

	:return-error 404:  	If the dataset key does not exist.

	"""

	# Save it!
	annotations = request.get_json()
	try:
		dataset = DataSet(key=dataset_key, db=db)
	except DataSetException:
		return error(404, error="Dataset not found.")

	try:
		annotations_saved = dataset.save_annotations(annotations, overwrite=True)
	except AnnotationException as e:
		# If anything went wrong with the annotation field saving, return an error.
		return jsonify(error=str(e)), 400

	# Else return the amount of fields saved.
	return str(annotations_saved)

def sort_and_iterate_items(dataset: DataSet, sort="", reverse=False, **kwargs):
	"""
	Loop through both csv and NDJSON files.
	Wrapper function for `dataset.sort_and_iterate_items()`.

	:param dataset:				The dataset object.
	:param sort:				The item key that determines the sort order.
	:param reverse:				Whether to sort by largest values first.

	:returns dict:				Yields iterated post
	"""

	# Resort to regular iteration if the dataset is larger than the maximum
	# allowed posts for the Explorer.
	if dataset.data["num_rows"] > config.get("explorer.max_posts", 500000):
		yield from dataset.iterate_items(**kwargs)
		return

	# Use dataset's sort_and_iterate_items function which can accept chunk_size and
	# creates a sorted temporary file (thus not using so much memory).
	yield from dataset.sort_and_iterate_items(sort=sort, reverse=reverse, **kwargs)


def has_datasource_template(datasource: str) -> bool:
	"""
	Check if the data source has a data source-specific template.
	This requires HTML and CSS files.
	Custom HTML files should be placed in `webtool/templates/explorer/datasource-templates/<datasource name>.html`.
	Custom CSS files should be placed in `webtool/static/css/explorer/<datasource name>.css`.

	:param datasource:	Datasource name.

	:returns: bool, Whether the required files are present.
	"""
	css_exists = Path(config.get('PATH_ROOT'), "webtool/static/css/explorer/" + datasource + ".css").exists()
	html_exists = Path(config.get('PATH_ROOT'), "webtool/templates/explorer/datasource-templates/" + datasource + ".html").exists()

	if css_exists and html_exists:
		return True
	return False
