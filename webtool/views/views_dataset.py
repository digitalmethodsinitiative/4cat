"""
4CAT Web Tool views - pages to be viewed by the user
"""
import json
import csv
import io
import json_stream
import mimetypes
import zipfile
from natsort import natsorted
from pathlib import Path
from flask import (Blueprint, current_app, render_template, request, redirect, send_from_directory, flash,
                   get_flashed_messages, url_for, stream_with_context, g, make_response)
from flask_login import login_required, current_user

from webtool.lib.helpers import (Pagination, annotation_context, error, setting_required,
                                 common_dataset_options, collect_grid_tags, module_request_url,
                                 datasource_variants)
from webtool.views.api_tool import toggle_favourite, toggle_private, queue_processor, datasource_form

from common.lib.dataset import DataSet
from common.lib.exceptions import DataSetException

component = Blueprint("dataset", __name__)

csv.field_size_limit(1024 * 1024 * 1024)


def available_datasources():
    """
    Enabled data sources, whether or not a dataset can be created from them

    :return dict:  Data source metadata, by data source ID
    """
    return {datasource: metadata for datasource, metadata in g.modules.datasources.items() if
            metadata["has_worker"] and datasource in g.config.get("datasources.enabled", {})}


def datasource_collector(datasource_id, metadata, worker):
    """
    What collects the data for a data source, for its card

    Three answers: data captured in the browser comes in via Zeeschuimer, and
    everything else is collected either by 4CAT itself or by a separate service
    an extension talks to. In the latter case the service is what a user needs
    to know about - it is where the data actually lives, it is what has to be
    reachable, and the card's own title is a collection within it rather than
    the source as a whole - so the data source is named instead of 4CAT.

    :param str datasource_id:  Data source ID
    :param dict metadata:  Data source metadata, from the module collector
    :param worker:  The data source's search worker
    :return str:  What to name as the collector
    """
    if metadata["importable"]:
        return "Zeeschuimer"

    if getattr(worker, "is_extension", False):
        return metadata.get("name") or datasource_id

    return "4CAT"


@component.route('/create-dataset/')
@login_required
@setting_required("privileges.can_create_dataset")
def create_dataset():
    """
    Main tool frontend
    """
    return render_template('create-dataset.html', datasources=available_datasources(),
                           request_url=module_request_url("datasource"))


@component.route('/create-dataset/datasources/')
@login_required
@setting_required("privileges.can_create_dataset")
def datasource_grid():
    """
    Get the data sources to create a dataset from, as a module grid

    Counterpart to `processor_grid`: fills the module slideout on the
    create-dataset page. Data sources are split by how the data gets into 4CAT
    - collected by 4CAT itself, or captured with Zeeschuimer and imported -
    since that determines what the user needs to do next. Only the former can
    be selected; the latter are listed at the end for reference.

    A data source that declares variants (see `Search.get_variants`) gets one
    card per variant instead of one card in total. Those cards are still the
    same data source: they only differ in what they carry to the options form,
    so the card ID is not a module ID and the URLs are built here rather than
    from the ID in the template.
    """
    modules = {}
    for datasource_id, metadata in available_datasources().items():
        worker = g.modules.workers[datasource_id + "-search"]
        status = worker.get_status()
        card = {
            "title": metadata["name"],
            "description": worker.description,
            "icon": getattr(worker, "icon", None),
            "tags": list(getattr(worker, "tags", []) or []),
            "status": list(status) if isinstance(status, (list, tuple, set)) else ([status] if status else []),
            "importable": metadata["importable"],
            "selectable": metadata["has_options"],
            "code_url": worker.get_repo_link(g.config),
            # the module catalogue is keyed by worker type, not data source ID
            "worker_type": worker.type,
            "collected_via": datasource_collector(datasource_id, metadata, worker),
        }

        variants = datasource_variants(worker, g.config) if metadata["has_options"] else {}
        if not variants:
            modules[datasource_id] = {
                **card,
                "options_url": url_for("dataset.datasource_options", datasource_id=datasource_id),
                "metadata_url": url_for("dataset.datasource_metadata", datasource_id=datasource_id),
            }
            continue

        for variant_id, variant in variants.items():
            modules["%s:%s" % (datasource_id, variant_id)] = {
                **card,
                "title": variant.get("title", variant_id),
                "description": variant.get("description", card["description"]),
                "tags": list(variant.get("tags", card["tags"]) or []),
                "options_url": url_for("dataset.datasource_options", datasource_id=datasource_id,
                                       variant=variant_id),
                "metadata_url": url_for("dataset.datasource_metadata", datasource_id=datasource_id,
                                        variant=variant_id),
            }

    collected = {k: v for k, v in modules.items() if not v["importable"]}
    imported = {k: v for k, v in modules.items() if v["importable"]}

    if collected and imported:
        grid_sections = [
            {"header": "Collected by 4CAT", "modules": collected},
            {"header": "Captured through Zeeschuimer", "modules": imported,
             "note": "Use Zeeschuimer to collect and upload data from these sources to 4CAT"},
        ]
    elif modules:
        grid_sections = [{"header": None, "modules": modules}]
    else:
        grid_sections = []

    return render_template("components/datasource-grid.html", grid_sections=grid_sections,
                           grid_tags=collect_grid_tags(grid_sections),
                           request_url=module_request_url("datasource"))


@component.route('/create-dataset/datasource/<string:datasource_id>/options/')
@login_required
@setting_required("privileges.can_create_dataset")
def datasource_options(datasource_id):
    """
    Get the query form for a data source as an HTML fragment

    htmx-facing counterpart to the JSON `toolapi.datasource_form` endpoint.
    Returns the rendered dataset parameter options for the data source picked
    in the module slideout, as a form that js/query-form.js submits.

    The picked variant, if the data source has any, is read from the query
    string by `datasource_form` and travels with the form from here on.

    :param str datasource_id:  Data source to show options for
    """
    result = datasource_form(datasource_id)
    if not result.is_json or result.status_code != 200:
        message = result.json.get("message", "This data source is not available.") \
            if result.is_json else "This data source is not available."
        return render_template("components/form-notice.html", message=message)

    return render_template("components/datasource-form.html", options_html=result.json["html"],
                           datasource_id=datasource_id, variant=result.json.get("variant"),
                           common_options=common_dataset_options(g.config, current_user))


@component.route('/create-dataset/datasource/<string:datasource_id>/metadata/')
@login_required
@setting_required("privileges.can_create_dataset")
def datasource_metadata(datasource_id):
    """
    Get the header for a data source's options in the module slideout

    Titled after the variant that was picked, if any, since that is the card the
    user clicked; the links stay those of the data source the variant belongs
    to, which is the module all its variants share.

    :param str datasource_id:  Data source to show metadata for
    """
    datasources = available_datasources()
    if datasource_id not in datasources:
        return error(404, error="This data source is not available.")

    worker = g.modules.workers[datasource_id + "-search"]

    title = datasources[datasource_id]["name"]
    variant = request.args.get("variant")
    if variant:
        variants = datasource_variants(worker, g.config)
        if variant not in variants:
            return error(404, error="This data source is not available.")
        title = variants[variant].get("title", variant)

    return render_template(
        "components/module-metadata.html",
        module={"title": title},
        icon=getattr(worker, "icon", None),
        info_url=url_for("misc.module_catalog", module_type="%s-search" % datasource_id),
        info_label="How is this data collected?",
        code_url=worker.get_repo_link(g.config),
        code_label="View data source code",
    )


@component.route('/results/', defaults={'page': 1})
@component.route('/results/page/<int:page>/')
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
        filters["hide_empty"] = False

    # handle 'depth'; all, own datasets, or favourites?
    # 'all' is limited to admins
    depth = request.args.get("depth", "own")
    available_depths = ["own", "favourites"]
    if g.config.get("privileges.can_view_all_datasets"):
        available_depths.append("all")

    if depth not in available_depths:
        depth = "own"

    owner_match = tuple([current_user.get_id(), *[f"tag:{t}" for t in current_user.tags]])

    # the user filter is only exposed to admins
    if filters["user"]:
        if g.config.get("privileges.can_view_all_datasets"):
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
    if not g.config.get("privileges.can_view_private_datasets"):
        where.append(
            "(is_private = FALSE OR key IN ( SELECT key FROM datasets_owners WHERE name IN %s AND key = datasets.key))")
        replacements.append(owner_match)

    # empty datasets could just have no results, or be failures. we make no
    # distinction here
    if filters["hide_empty"]:
        where.append("num_rows > 0")

    # not all datasets have a datasource defined, but that is fine, since if
    # we are looking for all datasources the query just excludes this part
    if filters["datasource"] and filters["datasource"] != "all":
        where.append("parameters::json->>'datasource' = %s")
        replacements.append(filters["datasource"])

    where = " AND ".join(where)

    # first figure out how many datasets this matches
    num_datasets = g.db.fetchone("SELECT COUNT(*) AS num FROM datasets WHERE " + where, tuple(replacements))["num"]

    # then get the current page of results
    replacements.append(page_size)
    replacements.append(offset)
    query = "SELECT * FROM datasets WHERE " + where + " ORDER BY " + filters["sort_by"] + " DESC LIMIT %s OFFSET %s"

    datasets = g.db.fetchall(query, tuple(replacements))

    if not datasets and page != 1:
        return error(404)

    # some housekeeping to prepare data for the template
    pagination = Pagination(page, page_size, num_datasets)
    filtered = [DataSet(data=dataset, db=g.db, modules=g.modules) for dataset in datasets]

    favourites = [row["key"] for row in
                  g.db.fetchall("SELECT key FROM users_favourites WHERE name = %s", (current_user.get_id(),))]

    datasources = {datasource: metadata for datasource, metadata in g.modules.datasources.items() if
                   metadata["has_worker"]}

    breadcrumbs = [{
        "url": url_for("dataset.show_results"),
        "label": "Datasets"
    }]
    # the dataset card names a dataset after the processor that made it, and
    # calls it deprecated when there is no such processor any more - so a page
    # rendering cards needs the processors, or every one of them looks defunct
    return render_template("results.html", filter=filters, depth=depth, datasources=datasources,
                           datasets=filtered, pagination=pagination, favourites=favourites, breadcrumbs=breadcrumbs,
                           processors=g.modules.processors)


"""
Downloading results
"""
def _serve_zip_member(archive_path: Path, member: str, dataset: DataSet):
    """Serve a member from a zip archive path and return a Flask Response or error()."""
    if not member:
        return error(400, error="No member specified.")

    # Reject absolute paths and traversal in member
    if Path(member).is_absolute() or ".." in Path(member).parts:
        return error(400, error="Invalid member path.")

    if not archive_path.is_file():
        return error(404, error="Archive not found.")

    mime_type, _ = mimetypes.guess_type(member)
    if mime_type is None:
        mime_type = "application/octet-stream"

    try:
        extracted = dataset.extract_file_from_archive(member, archive_path=archive_path)
    except Exception as e:
        return error(500, error=f"Error extracting archive member: {str(e)}")

    if not extracted or not extracted.exists():
        return error(404, error="File not found in archive.")

    response = send_from_directory(
        directory=str(extracted.parent),
        path=extracted.name,
        mimetype=mime_type,
        conditional=True,
        etag=True
    )
    response.headers["Content-Disposition"] = f'inline; filename="{Path(member).name}"'
    response.headers.setdefault("Accept-Ranges", "bytes")
    response.call_on_close(lambda: dataset.remove_disposable_files())
    return response

@component.route('/download/<string:dataset_key>/<path:query_file>')
@component.route('/download/<string:dataset_key>/')
def get_result(dataset_key=None, dataset=None, query_file=None, zip_member=None):
    """
    Get dataset result file

    :param str query_file:  name of the result file
    :param str dataset_key:  dataset key
    :param dataset:  Optional DataSet object, if already available
    :return:  Result file
    """
    # Allows use to use get_result without reinstantiating the DataSet if we already have it
    if dataset and isinstance(dataset, DataSet):
        # check DataSet object and dataset_key match if both provided to avoid confusion
        if dataset_key and dataset.key != dataset_key:
            return error(400, error="Dataset key does not match dataset provided.")
    elif dataset_key:
        # Check if dataset_key is valid key
        try:
            dataset = DataSet(key=dataset_key, db=g.db, modules=g.modules)
        except DataSetException:
            return error(404, error="Dataset not found.")
    else:
        return error(400, error="No valid dataset or dataset_key provided.")
    
    # Ensure dataset available to user
    if dataset.is_private and not (
            g.config.get("privileges.can_view_private_datasets") or 
            dataset.is_accessible_by(current_user)
            ):
        return error(403, error="This dataset is private.")
    
    # Read query_file and zip_member from request args if not supplied by a direct call
    if query_file is None:
        query_file = request.args.get("query_file")
    if zip_member is None:
        zip_member = request.args.get("zip_member")

    # If no specific file is requested, serve the main results file
    if not query_file:
        query_file = dataset.get_results_path().name
    
    # Security: Build and validate the full path
    data_root = g.config.get('PATH_DATA')
    results_folder = dataset.get_results_folder_path()
    requested_file = data_root.joinpath(query_file)

    # If the file doesn't exist relative to data_root, try the dataset's results folder.
    # Static HTML pages reference assets via relative URL paths rather than query params.
    if not requested_file.exists():
        fallback = results_folder / query_file
        if fallback.exists():
            query_file = str(fallback.relative_to(data_root))
            requested_file = data_root / query_file

    try:
        resolved_path = requested_file.resolve(strict=True)
    except (OSError, FileNotFoundError):
        return error(404, error="File not found.")

    try:
        # Must be within data_root and within the dataset's results folder (or the main results file)
        resolved_path.relative_to(data_root.resolve())
        if resolved_path != dataset.get_results_path().resolve():
            resolved_path.relative_to(results_folder.resolve())
    except ValueError:
        return error(403, error="Access denied.")

    if zip_member:
        # resolved_path already validated above to be within dataset scope
        return _serve_zip_member(archive_path=resolved_path, member=zip_member, dataset=dataset)

    # Guess MIME type, default to binary if unknown
    mime_type, _ = mimetypes.guess_type(query_file)
    if mime_type is None:
        mime_type = "application/octet-stream"

    # Send related file (Flask can handle file not found w/ 404 error)
    response = send_from_directory(
        directory=data_root, 
        path=query_file,
        mimetype=mime_type,
        conditional=True,
        etag=True
        )
    response.headers.setdefault("Accept-Ranges", "bytes")
    return response

@component.route('/result/<path:query_file>')
def get_result_legacy(query_file):
    """
    Legacy route for backward compatibility to maintain compatibility with old links that don't include the dataset key.
    
    :param str query_file:  name of the result file
    :return:  Result file or error
    """
    # Handle favicon relative requests that get caught by this broad route
    if query_file.endswith('/favicon.ico') or query_file == 'favicon.ico':
        return redirect(url_for('static', filename='img/favicon/favicon.ico'))

    import re
    # Parse dataset key from query_file if possible
    possible_keys = re.findall(r"[abcdef0-9]{32}", query_file)
    if not possible_keys:
        g.log.warning(f"Query file {query_file} does not seem to contain a dataset key - cannot serve file.")
        return error(404, error="This link format is no longer supported. Please use the updated link from the dataset page.")
    
    # if for whatever reason there are multiple hashes in the filename,
    # the key should be the first one (e.g. folder_dataset_key or dataset_type_dataset_key.csv)
    key = possible_keys.pop(0)
    return get_result(dataset_key=key, query_file=query_file)

@component.route('/mapped-result/<string:key>/')
def get_mapped_result(key):
    """
    Get mapped result

    Some result files are not CSV files. CSV is such a central file format that
    it is worth having a generic 'download as CSV' function for these. If the
    processor of the dataset has a method for mapping its data to CSV, then this
    route uses that to convert the data to CSV on the fly and serve it as such.

    We also use this if there's annotation data saved.

    :param str key:  Dataset key
    """
    try:
        dataset = DataSet(key=key, db=g.db, modules=g.modules)
    except DataSetException:
        return error(404, error="Dataset not found.")

    if dataset.is_private and not (
            g.config.get("privileges.can_view_private_datasets") or dataset.is_accessible_by(current_user)):
        return error(403, error="This dataset is private.")

    def map_response():
        """
        Yield a CSV file line by line

        Pythons built-in csv library, which we use, has no real concept of
        this, so we cheat by using a StringIO buffer that we flush and clear
        after each CSV line is written to it.
        """
        writer = None
        buffer = io.StringIO()
        for item in dataset.iterate_items(warn_unmappable=False):
            if not writer:
                fieldnames = list(item.keys())

                writer = csv.DictWriter(buffer, fieldnames=fieldnames)
                writer.writeheader()
                yield buffer.getvalue()
                buffer.truncate(0)
                buffer.seek(0)

            writer.writerow(item)
            yield buffer.getvalue()
            buffer.truncate(0)
            buffer.seek(0)

    disposition = 'attachment; filename="%s"' % dataset.get_results_path().with_suffix(".csv").name
    return current_app.response_class(stream_with_context(map_response()), mimetype="text/csv",
                              headers={"Content-Disposition": disposition})


@component.route("/results/<string:key>/log/")
@login_required
def view_log(key):
    try:
        dataset = DataSet(key=key, db=g.db, modules=g.modules)
    except DataSetException:
        return error(404, error="Dataset not found.")

    if dataset.is_private and not (
            g.config.get("privileges.can_view_private_datasets") or dataset.is_accessible_by(current_user)):
        return error(403, error="This dataset is private.")

    logfile = dataset.get_log_path()
    if not logfile.exists():
        return error(404)

    log = current_app.response_class(dataset.get_log_path().read_text("utf-8"))
    log.headers["Content-type"] = "text/plain"

    return log


@component.route("/preview/<string:key>/")
def preview_items(key):
    """
    Preview a dataset file

    :param str key:  Dataset key
    :return:  HTML preview
    """
    try:
        dataset = DataSet(key=key, db=g.db, modules=g.modules)
    except DataSetException:
        return error(404, error="Dataset not found.")

    if dataset.is_private and not (
            g.config.get("privileges.can_view_private_datasets") or dataset.is_accessible_by(current_user)):
        return error(403, error="This dataset is private.")

    preview_size = 1000
    preview_bytes = (1024 * 1024 * 1)  # 1MB

    # json and ndjson can use mapped data for the preview or the raw json;
    # this depends on 4CAT settings 
    processor = dataset.get_own_processor()
    has_mapper = processor and hasattr(processor, "map_item")
    use_mapper = has_mapper and g.config.get("ui.prefer_mapped_preview")

    if dataset.get_extension() == "gexf":
        # network files
        # use GEXF preview panel which loads full data file client-side
        hostname = g.config.get("flask.server_name").split(":")[0]
        in_localhost = hostname in ("localhost", "127.0.0.1") or hostname.endswith(".local") or \
                       hostname.endswith(".localhost")
        return render_template("preview/gexf.html", dataset=dataset, with_gephi_lite=(not in_localhost))

    elif dataset.get_extension() == "zip" and dataset.get_media_type() in ("image", "video", "audio"):
        # media archive (image/video/audio zip)
        # show the first few items as a carousel; members are served on demand
        # via the get_result endpoint's zip_member support, so nothing is
        # extracted here beyond reading the archive's file listing
        preview_media = 10
        members = []
        try:
            with zipfile.ZipFile(dataset.get_results_path(), "r") as archive:
                for info in natsorted(archive.infolist(), key=lambda f: f.filename):
                    name = info.filename
                    if info.is_dir() or name.rsplit("/", 1)[-1].startswith("."):
                        # skip folders and dotfiles (e.g. .metadata.json)
                        continue
                    members.append(name)
                    if len(members) >= preview_media:
                        break
        except zipfile.BadZipFile:
            return render_template(
                "components/error_message.html",
                title="Preview not available",
                message="This dataset's preview could not be generated. The archive may be corrupted.",
            )

        return render_template("preview/partials/media.html", dataset=dataset, members=members,
                               max_items=preview_media)

    elif dataset.get_extension() in ("svg", "png", "jpeg", "jpg", "gif", "webp", "mp4"):
        # image or video file
        # returned as a bare fragment for inline embedding
        return render_template("preview/partials/image.html", dataset=dataset)

    elif dataset.get_extension() == "html":
        # just render the file!
        with dataset.get_results_path().open() as infile:
            return render_template("preview/html.html", html=infile.read())

    elif dataset.get_extension() not in ("json", "ndjson") or use_mapper:
        # iterable data, which we use iterate_items() for, which in turn will
        # use map_item if the underlying data is not CSV but JSON
        rows = []
        try:
            for row in dataset.iterate_items(warn_unmappable=False):
                if len(rows) > preview_size:
                    break

                if len(rows) == 0:
                    rows.append({k: k for k in list(row.keys())})

                rows.append(row)

        except NotImplementedError:
            return error(404)

        if not rows and dataset.num_rows > 0:
            # Dataset claims to have items but iteration produced none — the
            # result file is likely malformed or its extension is mismatched
            # with its actual content. Surface to logs and to the user rather
            # than silently rendering an empty preview.
            g.log.warning(
                f"Preview for dataset {dataset.key} (type: {dataset.type}, extension: "
                f"{dataset.get_extension()}) yielded 0 items, but num_rows is "
                f"{dataset.num_rows} — possible file/format corruption."
            )
            return render_template(
                "components/error_message.html",
                title="Preview not available",
                message="This dataset's preview could not be generated. The result file may be corrupted or in an unexpected format. An administrator has been notified.",
            )

        return render_template("preview/partials/csv.html", rows=rows, max_items=preview_size,
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

        return render_template("preview/partials/json.html", dataset=dataset, json=json.dumps(data, indent=2), truncated=truncated)

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

        if not data and dataset.num_rows > 0:
            # Dataset claims to have items but the NDJSON file produced no
            # lines — likely the file is empty or malformed despite num_rows
            # being set. Surface this rather than render an empty preview.
            g.log.warning(
                f"Preview for dataset {dataset.key} (type: {dataset.type}, extension: ndjson) "
                f"read 0 lines, but num_rows is {dataset.num_rows} — possible file corruption."
            )
            return render_template(
                "components/error_message.html",
                title="Preview not available",
                message="This dataset's preview could not be generated. The result file may be corrupted or empty. An administrator has been notified.",
            )

        return render_template("preview/partials/json.html", dataset=dataset, json=json.dumps(data, indent=2), truncated=truncated)

    else:
        return render_template(
            "components/error_message.html",
            title="Preview not available",
            message="No preview is available for this file.",
        )


"""
Individual result pages
"""
@component.route('/results/<string:key>/')
def show_result(key):
    """
    Show result page

    The page contains dataset details and a download link, but also shows a list
    of finished processors.

    :param key:  Result key
    :return:  Rendered template
    """
    try:
        dataset = DataSet(key=key, db=g.db, modules=g.modules)
    except DataSetException:
        return error(404, error="This dataset cannot be found.")

    if not current_user.can_access_dataset(dataset):
        return error(403, error="This dataset is private.")

    # child datasets are not available via a separate page - redirect to parent
    if dataset.key_parent:
        genealogy = dataset.get_genealogy()
        nav = ",".join([family.key for family in genealogy])
        url = "/results/%s/#nav=%s" % (genealogy[0].key, nav)
        return redirect(url)

    is_processor_running = False
    is_favourite = (g.db.fetchone("SELECT COUNT(*) AS num FROM users_favourites WHERE name = %s AND key = %s",
                                (current_user.get_id(), dataset.key))["num"] > 0)

    # if the datasource is configured for it, this dataset may be deleted at some point
    datasource = dataset.parameters.get("datasource", "")
    datasources = g.modules.datasources
    datasource_expiration = g.config.get("datasources.expiration", {}).get(datasource, {})
    expires_datasource = False
    can_unexpire = ((g.config.get("expire.allow_optout") and \
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

    # special case: merged datasets
    # it is useful to know the labels of the datasets these were merged from!
    # so fetch these
    merge_sources = None
    if dataset.parameters.get("source"):
        source_keys = [k.strip() for k in dataset.parameters.get("source").split(",")]
        merge_sources = []
        for source in source_keys:
            try:
                merge_sources.append(DataSet(key=source, db=g.db, modules=g.modules))
            except DataSetException:
                merge_sources.append(source)

    # special case: filtered datasets
    # similar situation
    copy_source = None
    if dataset.parameters.get("copied_from"):
        copy_source = dataset.parameters.get("copied_from")
        try:
            copy_source = DataSet(key=copy_source, db=g.db, modules=g.modules)
        except DataSetException:
            copy_source = dataset.parameters.get("copied_from")

    # we can either show this view as a separate page or as a bunch of html
    # to be retrieved via XHR
    standalone = "processors" not in request.url
    template = "dataset-page/view-dataset.html" if standalone else "components/result-details.html"

    breadcrumbs = [{
            "url": url_for("dataset.show_results"),
            "label": "Datasets"
        },
        {
            "url": url_for("dataset.show_result", key=dataset.key),
            "label": dataset.get_label()
        }]

    # the dataset page opens on the Explorer when asked to - the Explorer's old
    # address redirects here, and its page links push URLs of this shape
    explore = request.args.get("view") == "explore"

    return render_template(template, dataset=dataset, parent_key=dataset.key, processors=g.modules.processors,
                           is_processor_running=is_processor_running, messages=get_flashed_messages(),
                           is_favourite=is_favourite, timestamp_expires=timestamp_expires, has_credentials=has_credentials,
                           expires_by_datasource=expires_datasource, can_unexpire=can_unexpire, breadcrumbs=breadcrumbs,
                           datasources=datasources, merge_sources=merge_sources, copy_source=copy_source,
                           explore=explore, **annotation_context(dataset))

@component.route('/results/<string:key>/dataset-card/')
@login_required
def dataset_card_component(key):
    """
    Render the top-level dataset card as a partial

    Polled by the card itself while the dataset is still being created.

    :param str key:  Key of the dataset to re-render
    """
    try:
        dataset = DataSet(key=key, db=g.db, modules=g.modules)
    except DataSetException:
        return error(404, error="This dataset cannot be found.")

    if not current_user.can_access_dataset(dataset):
        return error(403, error="This dataset is private.")

    return render_template(
        "dataset-page/dataset-progress-update.html",
        dataset=dataset,
        processors=g.modules.processors,
        # as in show_result: all data sources, so a dataset from a since-disabled
        # one still links to its overview
        datasources=g.modules.datasources,
        # the last poll of a finishing dataset renders the card with the
        # annotation fields box in it, so it needs the same context
        **annotation_context(dataset),
    )


@component.route('/results/<string:key>/processor-grid/')
@login_required
def processor_grid(key):

    try:
        dataset = DataSet(key=key, db=g.db, modules=g.modules)
    except DataSetException:
        return error(404, error="This dataset cannot be found.")

    if not current_user.can_access_dataset(dataset):
        return error(403, error="This dataset is private.")

    processors_available = dataset.get_available_processors(config=g.config)

    own_processor = dataset.get_own_processor()
    preferred_ids = list(own_processor.compatibility.preferred_followups) \
        if own_processor and own_processor.compatibility else []

    preferred_processors = {
        processor_type: processors_available[processor_type]
        for processor_type in preferred_ids
        if processor_type in processors_available
    }
    other_processors = {
        processor_type: processor
        for processor_type, processor in processors_available.items()
        if processor_type not in preferred_processors
    }

    if preferred_processors:
        grid_sections = [
            {"header": "Custom follow-ups", "modules": preferred_processors},
            {"header": "All available processors", "modules": other_processors},
        ]
    else:
        grid_sections = [{"header": None, "modules": other_processors}]

    return render_template(
        "components/processor-grid.html",
        dataset=dataset,
        grid_sections=grid_sections,
        grid_tags=collect_grid_tags(grid_sections),
        genealogy=dataset.get_genealogy(),
        request_url=module_request_url("processor"),
    )

@component.route('/results/<string:key>/processor-options/<string:processor>/')
@login_required
def processor_options(key, processor):
    """
    Get the options form for a processor, rendered as a partial

    :param str key:  Dataset key to show processor options for
    :param str processor:  ID of the processor to show options for
    """
    try:
        dataset = DataSet(key=key, db=g.db, modules=g.modules)
    except DataSetException:
        return error(404, error="This dataset cannot be found.")

    if not current_user.can_access_dataset(dataset):
        return error(403, error="This dataset is private.")

    available_processors = dataset.get_available_processors(config=g.config)
    if processor not in available_processors:
        return error(404, error="This processor is not available for this dataset.")

    return render_template(
        "components/processor-options.html",
        dataset=dataset,
        processor=available_processors[processor],
    )

@component.route('/results/<string:key>/processor-metadata/<string:processor>/')
@login_required
def processor_metadata(key, processor):
    """
    Get the metadata header for a processor.

    :param str key:  Dataset key to show processor metadata for
    :param str processor:  ID of the processor to show metadata for
    """
    try:
        dataset = DataSet(key=key, db=g.db, modules=g.modules)
    except DataSetException:
        return error(404, error="This dataset cannot be found.")

    if not current_user.can_access_dataset(dataset):
        return error(403, error="This dataset is private.")

    available_processors = dataset.get_available_processors(config=g.config)
    if processor not in available_processors:
        return error(404, error="This processor is not available for this dataset.")

    module = available_processors[processor]

    return render_template(
        "components/module-metadata.html",
        module=module,
        module_id=processor,
        icon=module.icon,
        tags=module.category,
        info_url=url_for("misc.module_catalog", module_type=processor),
        info_label="More information about this processor",
        code_url=module.get_repo_link(g.config),
        code_label="View processor code",
    )

@component.route('/results/<string:key>/child-dataset/')
@login_required
def child_dataset_component(key):
    """
    Render a single child dataset as a partial

    Used by htmx to refresh an in-progress analysis in the dataset tree until
    it is finished; the component polls this endpoint and replaces itself with
    the re-rendered state (see child-dataset.html).

    :param str key:  Dataset key to render
    """
    try:
        dataset = DataSet(key=key, db=g.db, modules=g.modules)
    except DataSetException:
        return error(404, error="This dataset cannot be found.")

    if not current_user.can_access_dataset(dataset):
        return error(403, error="This dataset is private.")

    return render_template(
        "dataset-page/child-dataset.html",
        dataset=dataset,
        top_parent=dataset.get_genealogy()[0],
        processors=g.modules.processors,
    )

@component.route('/results/<string:key>/queue-processor/', methods=["POST"])
@login_required
def queue_processor_component(key):
    """
    Queue a processor and return the updated dataset tree fragment

    htmx-facing counterpart to `queue_processor_interactive`. On success the
    response is a rendered child-dataset component: the new analysis itself
    when the processor ran on the top-level dataset, or the re-rendered parent
    (whose subtree now includes the new analysis) when it ran on a child. The
    options form sets a matching hx-target/hx-swap for either case.

    Failures are retargeted into the options form's notice area via response
    headers, so the slideout stays open and shows what went wrong; only a
    successful queue emits the `processor-queued` event that collapses it.

    :param str key:  Key of dataset to queue the processor for
    """
    try:
        dataset = DataSet(key=key, db=g.db, modules=g.modules)
    except DataSetException:
        return error(404, error="This dataset cannot be found.")

    result = queue_processor(key)

    if not result.is_json:
        # permission/validation error() response from the API function
        return result

    status = result.json.get("status")
    if status == "success":
        if dataset.key_parent:
            # processor ran on a child: re-render that child so its subtree
            # includes the new analysis
            subject = dataset
        else:
            # processor ran on the top-level dataset: render the new analysis
            # to be appended to the tree
            subject = DataSet(key=result.json["key"], db=g.db, modules=g.modules)

        response = make_response(render_template(
            "dataset-page/child-dataset.html",
            dataset=subject,
            top_parent=dataset.get_genealogy()[0],
            processors=g.modules.processors,
        ))
        # note: the vendored htmx build only implements the plain HX-Trigger
        # header, not HX-Trigger-After-Settle/-After-Swap, and dispatches it
        # before the swap happens. The client-side listener closes the
        # processor panel immediately (which doesn't depend on the new
        # content existing yet) and defers scrolling the new analysis into
        # view until htmx's own htmx:after:settle event fires.
        response.headers["HX-Trigger"] = json.dumps(
            {"processor-queued": {"key": result.json["key"]}}
        )
        return response

    # not queued: show the message (and any extra form fields for the
    # "extra-form" status) inside the options form instead
    notice = render_template(
        "components/form-notice.html",
        message=result.json.get("message", "The processor could not be queued."),
        needs_confirmation=(status == "confirm"),
    )
    if status == "extra-form":
        notice += result.json.get("html", "")

    response = make_response(notice)
    response.headers["HX-Retarget"] = "#module-options-notice"
    response.headers["HX-Reswap"] = "innerHTML"
    return response

@component.route('/results/<string:key>/processors/queue/<string:processor>/', methods=["GET", "POST"])
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

    return render_template("error.html", message=result.json.get("message", "Error :("))


@component.route("/results/<string:key>/toggle-favourite/")
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


@component.route("/results/<string:key>/toggle-private/")
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


@component.route("/results/<string:key>/keep/", methods=["GET"])
@login_required
def keep_dataset(key):
    try:
        dataset = DataSet(key=key, db=g.db, modules=g.modules)
    except DataSetException:
        return error(404, message="Dataset not found.")

    if not g.config.get("expire.allow_optout"):
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
        datasource_expiration = g.config.get("datasources.expiration", {}).get(datasource, {})
        if (datasource_expiration and not datasource_expiration.get("allow_optout")) or not g.config.get(
                "expire.allow_optout"):
            return render_template("error.html", title="Dataset cannot be kept",
                                   message="All datasets of this data source (%s) are scheduled for automatic "
                                           "deletion. This cannot be overridden." % datasource), 403

    if dataset.is_expiring(config=g.config):
        dataset.delete_parameter("expires-after")
        dataset.keep = True

    flash("Dataset expiration data removed. The dataset will no longer be deleted automatically.")
    return redirect(url_for("dataset.show_result", key=key))
