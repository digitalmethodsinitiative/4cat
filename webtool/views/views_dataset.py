"""
4CAT Web Tool views - pages to be viewed by the user
"""
import json
import csv
import io
import os
import re

import flask
import markdown
from flask import render_template, request, redirect, send_from_directory, flash, get_flashed_messages, \
    url_for, stream_with_context
from flask_login import login_required, current_user

from webtool import app, db, log
from webtool.lib.helpers import Pagination, error
from webtool.views.api_tool import delete_dataset, toggle_favourite, toggle_private, queue_processor, nuke_dataset, \
    erase_credentials

import config
import backend
from common.lib.dataset import DataSet
from common.lib.queue import JobQueue

csv.field_size_limit(1024 * 1024 * 1024)

"""
Results overview
"""


@app.route('/results/', defaults={'page': 1})
@app.route('/results/page/<int:page>/')
@login_required
def show_results(page):
    """
    Show results overview

    For each result, some metadata is displayed. This also implements a number
    of filters that can be used to narrow down the results. Basically, this is
    an elaborate Postgres query builder.

    :return:  Rendered template
    """
    page_size = 20
    offset = (page - 1) * page_size

    # ensure that we're only getting top-level datasets
    where = ["(key_parent = '' OR key_parent IS NULL)"]
    replacements = []

    # sanitize and validate filters and options
    filters = {
        **{key: request.args.get(key, "") for key in ("filter", "user")},
        "hide_empty": bool(request.args.get("hide_empty", False)),
        "sort_by": request.args.get("sort_by", "desc"),
        "datasource": request.args.get("datasource", "all")
    }

    if filters["sort_by"] not in ("timestamp", "num_rows"):
        filters["sort_by"] = "timestamp"

    if not request.args:
        filters["hide_empty"] = True

    # handle 'depth'; all, own datasets, or favourites?
    depth = request.args.get("depth", "own")
    if depth not in ("own", "favourites", "all"):
        depth = "own"

    if depth == "own":
        where.append("owner = %s")
        replacements.append(current_user.get_id())

    if depth == "favourites":
        where.append("key IN ( SELECT key FROM users_favourites WHERE name = %s )")
        replacements.append(current_user.get_id())

    # handle filters
    if filters["filter"]:
        # text filter looks in query and label (does it need to do more?)
        where.append("(query LIKE %s OR parameters::json->>'label' LIKE %s)")
        replacements.append("%" + filters["filter"] + "%")
        replacements.append("%" + filters["filter"] + "%")

    # hide private datasets for non-owners and non-admins
    if not current_user.is_admin:
        where.append("(is_private = FALSE OR owner = %s)")
        replacements.append(current_user.get_id())

    # empty datasets could just have no results, or be failures. we make no
    # distinction here
    if filters["hide_empty"]:
        where.append("num_rows > 0")

    # the user filter is only exposed to admins, and otherwise emulates the
    # 'own' option
    if filters["user"]:
        if (current_user.is_admin or current_user.get_id() == filters["user"]):
            where.append("owner = %s")
            replacements.append(filters["user"])
        else:
            where.append("(owner = %s AND (owner = %s OR is_private = FALSE))")
            replacements.append(filters["user"])
            replacements.append(current_user.get_id())

    # not all datasets have a datsource defined, but that is fine, since if
    # we are looking for all datasources the query just excludes this part
    if filters["datasource"] and filters["datasource"] != "all":
        where.append("parameters::json->>'datasource' = %s")
        replacements.append(filters["datasource"])

    where = " AND ".join(where)

    # first figure out how many datasets this matches
    num_datasets = db.fetchone("SELECT COUNT(*) AS num FROM datasets WHERE " + where, tuple(replacements))["num"]

    # then get the current page of results
    replacements.append(page_size)
    replacements.append(offset)
    datasets = db.fetchall(
        "SELECT key FROM datasets WHERE " + where + " ORDER BY " + filters["sort_by"] + " DESC LIMIT %s OFFSET %s",
        tuple(replacements))

    if not datasets and page != 1:
        return error(404)

    # some housekeeping to prepare data for the template
    pagination = Pagination(page, page_size, num_datasets)
    filtered = []

    for dataset in datasets:
        filtered.append(DataSet(key=dataset["key"], db=db))

    favourites = [row["key"] for row in
                  db.fetchall("SELECT key FROM users_favourites WHERE name = %s", (current_user.get_id(),))]

    datasources = {datasource: metadata for datasource, metadata in backend.all_modules.datasources.items() if
                   metadata["has_worker"] and metadata["has_options"]}

    return render_template("results.html", filter=filters, depth=depth, datasources=datasources,
                           datasets=filtered, pagination=pagination, favourites=favourites)


"""
Downloading results
"""
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
        return error(404, error="Dataset not found.")

    if dataset.is_private and not (current_user.is_admin or dataset.owner == current_user.get_id()):
        return error(403, error="This dataset is private.")

    if dataset.get_extension() == ".csv":
        # if it's already a csv, just return the existing file
        return url_for(get_result, query_file=dataset.get_results_path().name)

    if not hasattr(dataset.get_own_processor(), "map_item"):
        # cannot map without a mapping method
        return error(404, error="File not found.")

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
    return app.response_class(stream_with_context(map_response()), mimetype="text/csv",
                              headers={"Content-Disposition": disposition})


@app.route("/results/<string:key>/log/")
@login_required
def view_log(key):
    try:
        dataset = DataSet(key=key, db=db)
    except TypeError:
        return error(404, error="Dataset not found.")

    if dataset.is_private and not (current_user.is_admin or dataset.owner == current_user.get_id()):
        return error(403, error="This dataset is private.")

    logfile = dataset.get_log_path()
    if not logfile.exists():
        return error(404)

    log = flask.Response(dataset.get_log_path().read_text("utf-8"))
    log.headers["Content-type"] = "text/plain"

    return log


@app.route("/preview-as-table/<string:key>/")
def preview_items(key):
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
        return error(404, error="Dataset not found.")

    if dataset.is_private and not (current_user.is_admin or dataset.owner == current_user.get_id()):
        return error(403, error="This dataset is private.")

    preview_size = 1000

    processor = dataset.get_own_processor()
    if not processor:
        return render_template("components/error_message.html", title="Preview not available",
                               message="No preview is available for this file.")

    rows = []
    try:
        for row in dataset.iterate_items():
            if len(rows) > preview_size:
                break

            if len(rows) == 0:
                rows.append(list(row.keys()))

            rows.append(list(row.values()))

    except NotImplementedError:
        return error(404)

    return render_template("result-csv-preview.html", rows=rows, max_items=preview_size,
                           dataset=dataset)


"""
Individual result pages
"""


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
        return error(404)

    if not current_user.can_access_dataset(dataset):
        return error(403, error="This dataset is private.")

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
    datasources = backend.all_modules.datasources
    expires_datasource = False
    can_unexpire = hasattr(config, "EXPIRE_ALLOW_OPTOUT") and config.EXPIRE_ALLOW_OPTOUT and (
                current_user.is_admin or dataset.owner == current_user.get_id())
    if datasource in datasources and datasources[datasource].get("expire-datasets", None):
        timestamp_expires = dataset.timestamp + int(datasources[datasource].get("expire-datasets"))
        expires_datasource = True
    elif dataset.parameters.get("expires-after"):
        timestamp_expires = dataset.parameters.get("expires-after")
    else:
        timestamp_expires = None

    # if the dataset has parameters with credentials, give user the option to
    # erase them
    has_credentials = [p for p in dataset.parameters if p.startswith("api_") and p not in ("api_type", "api_track")]

    # we can either show this view as a separate page or as a bunch of html
    # to be retrieved via XHR
    standalone = "processors" not in request.url
    template = "result.html" if standalone else "result-details.html"

    return render_template(template, dataset=dataset, parent_key=dataset.key, processors=backend.all_modules.processors,
                           is_processor_running=is_processor_running, messages=get_flashed_messages(),
                           is_favourite=is_favourite, timestamp_expires=timestamp_expires, has_credentials=has_credentials,
                           expires_by_datasource=expires_datasource, can_unexpire=can_unexpire, datasources=datasources)


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


@app.route("/results/<string:key>/toggle-favourite/")
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


@app.route("/results/<string:key>/toggle-private/")
@login_required
def toggle_private_interactive(key):
    """
    Toggle dataset 'private' status

    Uses code from corresponding API endpoint, but redirects to a normal page
    rather than returning JSON as the API does, so this can be used for
    'normal' links.

    :param str key:  Dataset key
    :return:
    """
    success = toggle_private(key)
    if not success.is_json:
        return success

    if success.json["success"]:
        if success.json["is_private"]:
            flash("Dataset has been made private")
        else:
            flash("Dataset has been made public")

        return redirect("/results/" + key + "/")
    else:
        return render_template("error.html", message="Error while toggling private status for dataset %s." % key)


@app.route("/results/<string:key>/restart/")
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

    if dataset.is_private and not (current_user.is_admin or dataset.owner == current_user.get_id()):
        return error(403, error="This dataset is private.")

    if current_user.get_id() != dataset.owner and not current_user.is_admin:
        return error(403, message="Not allowed.")

    if not dataset.is_finished():
        return render_template("error.html", message="This dataset is not finished yet - you cannot re-run it.")

    for child in dataset.children:
        child.delete()

    dataset.unfinish()
    queue = JobQueue(logger=log, database=db)
    queue.add_job(jobtype=dataset.type, remote_id=dataset.key)

    flash("Dataset queued for re-running.")
    return redirect("/results/" + dataset.key + "/")


@app.route("/results/<string:key>/keep/", methods=["GET"])
@login_required
def keep_dataset(key):
    try:
        dataset = DataSet(key=key, db=db)
    except TypeError:
        return error(404, message="Dataset not found.")

    if not dataset.key_parent:
        # top-level dataset
        # check if data source forces expiration - in that case, the user
        # cannot reset this
        datasources = backend.all_modules.datasources
        datasource = dataset.parameters.get("datasource")
        if datasource in datasources and datasources[datasource].get("expire-datasets"):
            return render_template("error.html", title="Dataset cannot be kept",
                                   message="All datasets of this data source (%s) are scheduled for automatic deletion. This cannot be overridden." %
                                           datasource["name"]), 403

    dataset.delete_parameter("expires-after")
    flash("Dataset expiration data removed. The dataset will no longer be deleted automatically.")
    return redirect(url_for("show_result", key=key))


@app.route("/results/<string:key>/nuke/", methods=["GET", "DELETE", "POST"])
@login_required
def nuke_dataset_interactive(key):
    """
    Nuke dataset

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

    if not current_user.can_access_dataset(dataset):
        return error(403, error="This dataset is private.")

    top_key = dataset.top_parent().key
    reason = request.form.get("reason", "")

    success = nuke_dataset(key, reason)

    if not success.is_json:
        return success
    else:
        # If it's a child processor, refresh the page.
        # Else go to the results overview page.
        return redirect(url_for('show_result', key=top_key))


@app.route("/results/<string:key>/delete/", methods=["GET", "DELETE", "POST"])
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

    if not current_user.can_access_dataset(dataset):
        return error(403, error="This dataset is private.")

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


@app.route("/results/<string:key>/erase-credentials/", methods=["GET", "DELETE", "POST"])
@login_required
def erase_credentials_interactive(key):
    """
    Erase sensitive parameters from dataset

    Removes all parameters starting with `api_`. This heuristic could be made
    more expansive if more fine-grained control is required.

    Uses code from corresponding API endpoint, but redirects to a normal page
    rather than returning JSON as the API does, so this can be used for
    'normal' links.

    :param str key:  Dataset key
    :return:
    """
    try:
        dataset = DataSet(key=key, db=db)
    except TypeError:
        return error(404, error="Dataset does not exist.")

    if not current_user.is_admin and not current_user.get_id() == dataset.owner:
        return error(403, message="Not allowed")

    success = erase_credentials(key)

    if not success.is_json:
        return success
    else:
        flash("Dataset credentials erased.")
        return redirect(url_for('show_result', key=key))
