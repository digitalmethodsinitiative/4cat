"""
4CAT Web Tool views - pages to be viewed by the user
"""
import json
import csv
import io

import flask
import json_stream
from flask import render_template, request, redirect, send_from_directory, flash, get_flashed_messages, \
    url_for, stream_with_context
from flask_login import login_required, current_user

from webtool import app, db, config
from webtool.lib.helpers import Pagination, error, setting_required
from webtool.views.api_tool import toggle_favourite, toggle_private, queue_processor

import backend
from common.lib.dataset import DataSet
from common.lib.exceptions import DataSetException
from common.config_manager import ConfigWrapper

config = ConfigWrapper(config, user=current_user, request=request)

csv.field_size_limit(1024 * 1024 * 1024)


@app.route('/create-dataset/')
@login_required
@setting_required("privileges.can_create_dataset")
def create_dataset():
    """
    Main tool frontend
    """
    datasources = {datasource: metadata for datasource, metadata in backend.all_modules.datasources.items() if
                   metadata["has_worker"] and metadata["has_options"] and datasource in config.get(
                       "datasources.enabled", {})}

    return render_template('create-dataset.html', datasources=datasources)


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
    # 'all' is limited to admins
    depth = request.args.get("depth", "own")
    available_depths = ["own", "favourites"]
    if config.get("privileges.can_view_all_datasets"):
        available_depths.append("all")

    if depth not in available_depths:
        depth = "own"

    owner_match = tuple([current_user.get_id(), *[f"tag:{t}" for t in current_user.tags]])

    # the user filter is only exposed to admins
    if filters["user"]:
        if config.get("privileges.can_view_all_datasets"):
            where.append("key IN ( SELECT key FROM datasets_owners WHERE name LIKE %s AND key = datasets.key)")
            replacements.append(filters["user"].replace("*", "%"))
        else:
            return error(403, error="You cannot use this filter.")
    elif depth == "own":
        where.append("key IN ( SELECT key FROM datasets_owners WHERE name IN %s AND key = datasets.key)")
        replacements.append(owner_match)

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
    if not config.get("privileges.can_view_private_datasets"):
        where.append(
            "(is_private = FALSE OR key IN ( SELECT key FROM datasets_owners WHERE name IN %s AND key = datasets.key))")
        replacements.append(owner_match)

    # empty datasets could just have no results, or be failures. we make no
    # distinction here
    if filters["hide_empty"]:
        where.append("num_rows > 0")

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
    query = "SELECT key FROM datasets WHERE " + where + " ORDER BY " + filters["sort_by"] + " DESC LIMIT %s OFFSET %s"

    datasets = db.fetchall(query, tuple(replacements))

    if not datasets and page != 1:
        return error(404)

    # some housekeeping to prepare data for the template
    pagination = Pagination(page, page_size, num_datasets)
    filtered = [DataSet(key=dataset["key"], db=db) for dataset in datasets]

    favourites = [row["key"] for row in
                  db.fetchall("SELECT key FROM users_favourites WHERE name = %s", (current_user.get_id(),))]

    datasources = {datasource: metadata for datasource, metadata in backend.all_modules.datasources.items() if
                   metadata["has_worker"] and metadata["has_options"]}

    return render_template("results.html", filter=filters, depth=depth, datasources=datasources,
                           datasets=filtered, pagination=pagination, favourites=favourites)


"""
Downloading results
"""


@app.route('/result/<path:query_file>')
def get_result(query_file):
    """
    Get dataset result file

    :param str query_file:  name of the result file
    :return:  Result file
    :rmime: text/csv
    """
    return send_from_directory(directory=config.get('PATH_ROOT').joinpath(config.get('PATH_DATA')), path=query_file)


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
    except DataSetException:
        return error(404, error="Dataset not found.")

    if dataset.is_private and not (
            config.get("privileges.can_view_private_datasets") or dataset.is_accessible_by(current_user)):
        return error(403, error="This dataset is private.")

    if dataset.get_extension() == ".csv":
        # if it's already a csv, just return the existing file
        return url_for(get_result, query_file=dataset.get_results_path().name)

    if not hasattr(dataset.get_own_processor(), "map_item"):
        # cannot map without a mapping method
        return error(404, error="File not found.")

    mapper = dataset.get_own_processor().map_item

    # Also add possibly added annotation items.
    # These cannot be added to the static `map_item` function.
    annotation_labels = None
    annotation_fields = dataset.get_annotation_fields()
    if annotation_fields:
        annotation_labels = ["annotation_" + v["label"] for v in annotation_fields.values()]

    def map_response():
        """
        Yield a CSV file line by line

        Pythons built-in csv library, which we use, has no real concept of
        this, so we cheat by using a StringIO buffer that we flush and clear
        after each CSV line is written to it.
        """
        writer = None
        buffer = io.StringIO()
        for mapped_item in dataset.iterate_items(processor=dataset.get_own_processor(), warn_unmappable=False):
            if not writer:
                fieldnames = mapped_item.keys()
                if annotation_labels:
                    for label in annotation_labels:
                        if label not in fieldnames:
                            fieldnames.append(label)

                writer = csv.DictWriter(buffer, fieldnames=tuple(fieldnames))
                writer.writeheader()
                yield buffer.getvalue()
                buffer.truncate(0)
                buffer.seek(0)

            if annotation_fields:
                for label in annotation_labels:
                    mapped_item[label] = item[label]

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
    except DataSetException:
        return error(404, error="Dataset not found.")

    if dataset.is_private and not (
            config.get("privileges.can_view_private_datasets") or dataset.is_accessible_by(current_user)):
        return error(403, error="This dataset is private.")

    logfile = dataset.get_log_path()
    if not logfile.exists():
        return error(404)

    log = flask.Response(dataset.get_log_path().read_text("utf-8"))
    log.headers["Content-type"] = "text/plain"

    return log


@app.route("/preview/<string:key>/")
def preview_items(key):
    """
    Preview a dataset file

    Simply passes the first 25 rows of a dataset's csv result file to the
    template renderer.

    :param str key:  Dataset key
    :return:  HTML preview
    """
    try:
        dataset = DataSet(key=key, db=db)
    except DataSetException:
        return error(404, error="Dataset not found.")

    if dataset.is_private and not (
            config.get("privileges.can_view_private_datasets") or dataset.is_accessible_by(current_user)):
        return error(403, error="This dataset is private.")

    preview_size = 1000
    preview_bytes = (1024 * 1024 * 1)  # 1MB

    processor = dataset.get_own_processor()
    if not processor:
        return render_template("components/error_message.html", title="Preview not available",
                               message="No preview is available for this file.")

    # json and ndjson can use mapped data for the preview or the raw json;
    # this depends on 4CAT settings
    has_mapper = hasattr(processor, "map_item")
    use_mapper = has_mapper and config.get("ui.prefer_mapped_preview")

    if dataset.get_extension() == "gexf":
        # network files
        # use GEXF preview panel which loads full data file client-side
        hostname = config.get("flask.server_name").split(":")[0]
        in_localhost = hostname in ("localhost", "127.0.0.1") or hostname.endswith(".local") or \
                       hostname.endswith(".localhost")
        return render_template("preview/gexf.html", dataset=dataset, with_gephi_lite=(not in_localhost))

    elif dataset.get_extension() in ("svg", "png", "jpeg", "jpg", "gif", "webp"):
        # image file
        # just show image in an empty page
        return render_template("preview/image.html", dataset=dataset)

    elif dataset.get_extension() not in ("json", "ndjson") or use_mapper:
        # iterable data, which we use iterate_items() for, which in turn will
        # use map_item if the underlying data is not CSV but JSON
        rows = []
        try:
            for row in dataset.iterate_items(warn_unmappable=False):
                if len(rows) > preview_size:
                    break

                if len(rows) == 0:
                    rows.append(list(row.keys()))

                rows.append(list(row.values()))

        except NotImplementedError:
            return error(404)

        return render_template("preview/csv.html", rows=rows, max_items=preview_size,
                               dataset=dataset)

    elif dataset.get_extension() == "json":
        # JSON file
        # show formatted json data, or a subset if possible
        datafile = dataset.get_results_path()
        truncated = False
        if datafile.stat().st_size > preview_bytes:
            # larger than 3MB
            # is this a list?
            with datafile.open() as infile:
                if infile.read(1) == "[":
                    # it's a list! use json_stream to stream the first items
                    infile.seek(0)
                    stream = json_stream.load(infile)
                    data = []
                    while infile.tell() < preview_bytes:
                        # read up to 3 MB
                        for row in stream:
                            data.append(row)

                    if infile.read(1) != "":
                        # not EOF
                        truncated = len(data)

                else:
                    data = "Data file too large; cannot preview"
        else:
            with datafile.open() as infile:
                data = infile.read()

        return render_template("preview/json.html", dataset=dataset, json=json.dumps(data, indent=2), truncated=truncated)

    elif dataset.get_extension() == "ndjson":
        # mostly similar to JSON preview, but we don't have to stream the file
        # as json, we can simply read line by line until we've reached the
        # size limit
        datafile = dataset.get_results_path()
        truncated = False
        data = []

        with datafile.open() as infile:
            while infile.tell() < preview_bytes:
                line = infile.readline()
                if line == "":
                    break

                data.append(json.loads(line.strip()))

            if infile.read(1) != "":
                # not EOF
                truncated = len(data)

        return render_template("preview/json.html", dataset=dataset, json=json.dumps(data, indent=2), truncated=truncated)


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
    except DataSetException:
        return error(404)

    if not current_user.can_access_dataset(dataset):
        return error(403, error="This dataset is private.")

    # child datasets are not available via a separate page - redirect to parent
    if dataset.key_parent:
        genealogy = dataset.get_genealogy()
        nav = ",".join([family.key for family in genealogy])
        url = "/results/%s/#nav=%s" % (genealogy[0].key, nav)
        return redirect(url)

    is_processor_running = False
    is_favourite = (db.fetchone("SELECT COUNT(*) AS num FROM users_favourites WHERE name = %s AND key = %s",
                                (current_user.get_id(), dataset.key))["num"] > 0)

    # if the datasource is configured for it, this dataset may be deleted at some point
    datasource = dataset.parameters.get("datasource", "")
    datasources = backend.all_modules.datasources
    datasource_expiration = config.get("datasources.expiration", {}).get(datasource, {})
    expires_datasource = False
    can_unexpire = ((config.get('expire.allow_optout') and \
                     datasource_expiration.get("allow_optout", True)) or datasource_expiration.get("allow_optout",
                                                                                                   False)) \
                   and (current_user.is_admin or dataset.is_accessible_by(current_user, "owner"))

    timestamp_expires = None
    if not dataset.parameters.get("keep"):
        if datasource_expiration and datasource_expiration.get("timeout"):
            timestamp_expires = dataset.timestamp + int(datasource_expiration.get("timeout"))
            expires_datasource = True

        elif dataset.parameters.get("expires-after"):
            timestamp_expires = dataset.parameters.get("expires-after")

    # if the dataset has parameters with credentials, give user the option to
    # erase them
    has_credentials = [p for p in dataset.parameters if p.startswith("api_") and p not in ("api_type", "api_track")]

    # we can either show this view as a separate page or as a bunch of html
    # to be retrieved via XHR
    standalone = "processors" not in request.url
    template = "result.html" if standalone else "components/result-details.html"

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


@app.route("/results/<string:key>/keep/", methods=["GET"])
@login_required
def keep_dataset(key):
    try:
        dataset = DataSet(key=key, db=db)
    except DataSetException:
        return error(404, message="Dataset not found.")

    if not config.get("expire.allow_optout"):
        return render_template("error.html", title="Dataset cannot be kept",
                               message="All datasets are scheduled for automatic deletion. This cannot be "
                                       "overridden."), 403

    if not current_user.can_access_dataset(dataset, role="owner"):
        return error(403, message="You cannot cancel deletion for this dataset.")

    if not dataset.key_parent:
        # top-level dataset
        # check if data source forces expiration - in that case, the user
        # cannot reset this
        datasource = dataset.parameters.get("datasource")
        datasource_expiration = config.get("datasources.expiration", {}).get(datasource, {})
        if (datasource_expiration and not datasource_expiration.get("allow_optout")) or not config.get(
                "expire.allow_optout"):
            return render_template("error.html", title="Dataset cannot be kept",
                                   message="All datasets of this data source (%s) are scheduled for automatic "
                                           "deletion. This cannot be overridden." % datasource), 403

    if dataset.is_expiring(user=current_user):
        dataset.delete_parameter("expires-after")
        dataset.keep = True

    flash("Dataset expiration data removed. The dataset will no longer be deleted automatically.")
    return redirect(url_for("show_result", key=key))
