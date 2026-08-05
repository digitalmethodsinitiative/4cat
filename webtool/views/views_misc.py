"""
4CAT Web Tool views - pages to be viewed by the user
"""
import re
import csv
import json
import logging
import markdown2
import traceback

from pathlib import Path

from flask import Blueprint, request, render_template, jsonify, Response, redirect, url_for, g, current_app
from flask_login import login_required
from werkzeug.exceptions import HTTPException, InternalServerError

from webtool.lib.helpers import collect_grid_tags, error, module_map, module_request_url

from common.lib.module_map import describe_requirements

from common.lib.helpers import get_datasource_example_keys

component = Blueprint("misc", __name__)

csv.field_size_limit(1024 * 1024 * 1024)

@component.app_errorhandler(Exception)
def log_exception(e):
    """
    Log all exceptions
    """
    if isinstance(e, HTTPException):
        status_code = e.code
        # Could handle specific HTTP errors here
    else:
        status_code = None

    # Check if it's an InternalServerError and extract the original exception
    if isinstance(e, InternalServerError) and e.original_exception:
        cause = e.original_exception
    else:
        cause = e

    if not status_code or status_code >= 500:
        # Capture the correct frame and log
        tb = traceback.extract_tb(cause.__traceback__)
        location = "→".join([f"{t.filename.split('/')[-1]}:{t.lineno}" for t in tb])

        # Get the request URL
        request_url = request.url

        msg = f"{type(cause).__name__}{(' ('+request_url+')') if request_url else ''}: {cause}"
        current_app.log.error(msg, frame=tb if tb else None)
        logging.error(msg + f" at {location}")

        return error(status_code if status_code else 500, message="An internal error occurred while processing your request.", status="error")
    else:
        # Should be just 4xx errors; return and allow Flask to handle them
        return e

@component.app_errorhandler(413)
def request_entity_too_large(this_error):
    message = "File too large; try uploading as a ZIP file instead."
    return error(413, message=message, status="error")

@component.route('/')
@login_required
def show_frontpage():
    """
    Index page: news and introduction

    :return:
    """
    page = g.config.get("ui.homepage")
    if page == "create-dataset":
        return redirect(url_for("dataset.create_dataset"))
    elif page == "datasets":
        return redirect(url_for("dataset.show_results"))
    else:
        return show_about()

@component.route("/about/")
@login_required
def show_about():
    # load corpus stats that are generated daily, if available
    stats_path = Path(g.config.get('PATH_ROOT'), "stats.json")
    if stats_path.exists():
        with stats_path.open() as stats_file:
            stats = stats_file.read()
        try:
            stats = json.loads(stats)
        except json.JSONDecodeError:
            stats = None
    else:
        stats = None

    news_path = Path(g.config.get('PATH_ROOT'), "news.json")
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

    datasources = {k: v for k, v in g.modules.datasources.items() if
                   k in g.config.get("datasources.enabled") and not v["importable"]}
    importables = {k: v for k, v in g.modules.datasources.items() if (v["importable"] and k in g.config.get("datasources.enabled"))}

    return render_template("frontpage.html", stats=stats, news=news, datasources=datasources, importables=importables)


@component.route("/robots.txt")
def robots():
    """
    Display robots.txt

    Default to blocking everything, because the tool will (should) usually be
    run as an internal resource.
    """
    robots = Path(g.config.get("PATH_ROOT"), "webtool/static/robots.txt")
    if not robots.exists():
        return Response("User-agent: *\nDisallow: /", mimetype='text/plain')

    with robots.open() as infile:
        return Response(response=infile.read(), status=200, mimetype="text/plain")


@component.route("/favicon.ico")
def favicon():
    """
    Serve favicon from static directory

    Redirect to the favicon in the static assets folder. This route handles
    automatic browser requests for /favicon.ico without requiring login.
    """
    return redirect(url_for('static', filename='img/favicon/favicon.ico'))

def datasource_ids_by_worker():
    """
    Map a data source's search worker type onto its data source ID

    The module map is keyed by module type (`bsky-search`), while data source
    metadata is keyed by data source ID (`bsky`).

    :return dict:  {worker type: data source ID}
    """
    return {"%s-search" % datasource: datasource for datasource in g.modules.datasources}


def datasource_detail(datasource_id):
    """
    The data source-specific part of a module's detail in the catalogue

    This is what used to live on the (now redirected) data-overview page: the
    data source's own DESCRIPTION.md, what kind of source it is, how long its
    datasets are kept, and which fields its items have.

    :param str datasource_id:  Data source to describe
    :return dict:  Detail context for components/module-detail-datasource.html
    """
    metadata = g.modules.datasources[datasource_id]
    worker = g.modules.workers.get("%s-search" % datasource_id)

    description = None
    description_path = Path(metadata.get("path"), "DESCRIPTION.md")
    if description_path.exists():
        with description_path.open(encoding="utf-8") as description_file:
            description = description_file.read()

    # the fields items from this data source have; skipped for uploads, whose
    # fields are whatever the uploaded file happens to contain
    example_keys = None
    if datasource_id not in ("upload",):
        example_keys = get_datasource_example_keys(db=g.db, modules=g.modules,
                                                   dataset_type="%s-search" % datasource_id)

    expiration = metadata.get("expire-datasets") or {}
    github_url = (g.config.get("4cat.github_url") or "").rstrip("/")

    return {
        "id": datasource_id,
        "name": metadata["name"],
        "description": description,
        "enabled": datasource_id in g.config.get("datasources.enabled", {}),
        "importable": bool(metadata["importable"]),
        "configurable": bool(metadata["has_options"]),
        "expiration": expiration.get("timeout") or None,
        "example_keys": example_keys,
        "references": getattr(worker, "references", None),
        "source_url": "%s/tree/master/datasources/%s" % (github_url, metadata["id"]) if github_url else None,
    }


def module_detail_context(module_type):
    """
    Everything the catalogue shows about one module

    :param str module_type:  Module to describe
    :return dict|None:  Render context, or None if there is no such module
    """
    module = module_map().module(module_type)
    if module is None:
        return None

    datasource_id = datasource_ids_by_worker().get(module_type) if module["is_datasource"] else None

    requirement = (module.get("how_to_run") or {}).get("accepts", {}).get("requirement")

    return {
        "module": module,
        "module_type": module_type,
        "requirements": describe_requirements(requirement),
        "datasource": datasource_detail(datasource_id) if datasource_id else None,
    }


def module_catalog_sections():
    """
    Every module in the catalog, grouped for the module grid

    Data sources lead - they are where every analysis starts - followed by the
    processors.

    :return list:  `grid_sections` for components/module-grid.html
    """
    catalogue = module_map().catalogue()
    datasource_ids = datasource_ids_by_worker()

    for entry in catalogue:
        entry["datasource_id"] = datasource_ids.get(entry["type"]) if entry["is_datasource"] else None

    def by_title(entries):
        return {entry["type"]: entry for entry in
                sorted(entries, key=lambda entry: (entry["title"] or entry["type"]).lower())}

    sections = []
    datasources = [entry for entry in catalogue if entry["is_datasource"]]
    if datasources:
        sections.append({"header": "Data sources", "modules": by_title(datasources)})

    processors = [entry for entry in catalogue if not entry["is_datasource"]]

    if processors:
        sections.append({"header": "Processors", "modules": by_title(processors)})

    return sections


@component.route("/module-catalog/")
@component.route("/module-catalog/<module_type>")
@login_required
def module_catalog(module_type=None):
    """
    Render the module catalog

    Lists every module 4CAT knows - data sources and processors alike - as
    module cards. With a module type in the path the page opens with that
    module's detail already loaded, so a direct link lands on it instead of the
    visitor having to find and click it.

    :param str module_type:  Module to open the catalogue on
    """
    grid_sections = module_catalog_sections()

    return render_template("module-catalog.html", grid_sections=grid_sections,
                           grid_tags=collect_grid_tags(grid_sections),
                           detail=module_detail_context(module_type) if module_type else None,
                           # the catalogue holds both kinds, so let the requester pick a form
                           request_url=module_request_url(None))


@component.route("/module-catalog/<module_type>/detail/")
@login_required
def module_detail(module_type):
    """
    Render one module's full detail as a partial

    Swapped into the top of the module catalogue when a module is selected.

    :param str module_type:  Module to describe
    """
    detail = module_detail_context(module_type)
    if detail is None:
        return error(404, error="This module cannot be found.")

    return render_template("components/module-detail.html", **detail)


@component.route('/data-overview/')
@component.route('/data-overview/<string:datasource>')
@login_required
def data_overview(datasource=None):
    """
    Redirect to the module catalogue

    The data source overview has been folded into the module catalogue, which
    shows the same information as part of a data source's module detail. Kept as
    a redirect so existing links and bookmarks keep working.

    :param str datasource:  Data source that was being looked at
    """
    if datasource and datasource in g.modules.datasources:
        return redirect(url_for("misc.module_catalog", module_type="%s-search" % datasource))

    return redirect(url_for("misc.module_catalog"))

@component.route('/get-boards/<string:datasource>/')
@login_required
def getboards(datasource):
    if datasource not in g.config.get("datasources.enabled"):
        result = False
    else:
        result = g.config.get(datasource + "-search.boards", False)

    return jsonify(result)

@component.route('/page/<string:page>/')
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
    page_folder = Path(g.config.get('PATH_ROOT'), "webtool", "pages")
    page_path = page_folder.joinpath(page + ".md")

    if not page_path.exists():
        return error(404, error="Page not found")

    with page_path.open(encoding="utf-8") as file:
        page_raw = file.read()
        page_parsed = markdown2.markdown(page_raw)
        page_parsed = re.sub(r"<h2>(.*)</h2>", r"<h2><span>\1</span></h2>", page_parsed)

        if g.config.get("mail.admin_email"):
            # replace this one explicitly instead of doing a generic config
            # filter, to avoid accidentally exposing config values
            admin_email = g.config.get("mail.admin_email", "4cat-admin@example.com")
            page_parsed = page_parsed.replace("%%ADMIN_EMAIL%%", admin_email)

    return render_template("page.html", body_content=page_parsed, body_class=page_class, page_name=page)