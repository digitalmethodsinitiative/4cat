"""
4CAT Web Tool views - pages to be viewed by the user
"""
import re
import csv
import json
import markdown

from pathlib import Path
from datetime import datetime

import backend

from flask import request, render_template, jsonify, Response
from flask_login import login_required, current_user

from webtool import app, db, config
from webtool.lib.helpers import pad_interval, error, setting_required
from webtool.views.views_dataset import create_dataset, show_results

from common.config_manager import ConfigWrapper
config = ConfigWrapper(config, user=current_user, request=request)

csv.field_size_limit(1024 * 1024 * 1024)


@app.route('/')
@login_required
def show_frontpage():
    """
    Index page: news and introduction

    :return:
    """
    page = config.get("ui.homepage")
    if page == "create-dataset":
        return create_dataset()
    elif page == "datasets":
        return show_results(page=1)
    else:
        return show_about()

@app.route("/about/")
@login_required
def show_about():
    # load corpus stats that are generated daily, if available
    stats_path = Path(config.get('PATH_ROOT'), "stats.json")
    if stats_path.exists():
        with stats_path.open() as stats_file:
            stats = stats_file.read()
        try:
            stats = json.loads(stats)
        except json.JSONDecodeError:
            stats = None
    else:
        stats = None

    news_path = Path(config.get('PATH_ROOT'), "news.json")
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

    datasources = {k: v for k, v in backend.all_modules.datasources.items() if
                   k in config.get("datasources.enabled") and not v["importable"]}
    importables = {k: v for k, v in backend.all_modules.datasources.items() if v["importable"]}

    return render_template("frontpage.html", stats=stats, news=news, datasources=datasources, importables=importables)


@app.route("/robots.txt")
def robots():
    """
    Display robots.txt

    Default to blocking everything, because the tool will (should) usually be
    run as an internal resource.
    """
    robots = Path(config.get("PATH_ROOT"), "webtool/static/robots.txt")
    if not robots.exists():
        return Response("User-agent: *\nDisallow: /", mimetype='text/plain')

    with robots.open() as infile:
        return Response(response=infile.read(), status=200, mimetype="text/plain")


@app.route("/access-tokens/")
@login_required
def show_access_tokens():
    user = current_user.get_id()

    if user == "autologin":
        return error(403, message="You cannot view or generate access tokens without a personal acount.")

    tokens = db.fetchall("SELECT * FROM access_tokens WHERE name = %s", (user,))

    return render_template("access-tokens.html", tokens=tokens)


@app.route('/data-overview/')
@app.route('/data-overview/<string:datasource>')
@login_required
def data_overview(datasource=None):
    """
    Main tool frontend
    """
    datasources = {datasource: metadata for datasource, metadata in backend.all_modules.datasources.items() if
                   metadata["has_worker"] and datasource in config.get("datasources.enabled")}

    if datasource not in datasources:
        datasource = None

    github_url = config.get("4cat.github_url")

    # Get information for a specific data source
    datasource_id = None
    description = None
    total_counts = None
    daily_counts = None
    references = None
    labels = None

    if datasource:

        datasource_id = datasource
        worker_class = backend.all_modules.workers.get(datasource_id + "-search")
        # Database IDs may be different from the Datasource ID (e.g. the datasource "4chan" became "fourchan" but the database ID remained "4chan")
        database_db_id = worker_class.prefix if hasattr(worker_class, "prefix") else datasource_id

        # Get description
        description_path = Path(datasources[datasource_id].get("path"), "DESCRIPTION.md")
        if description_path.exists():
            with description_path.open(encoding="utf-8") as description_file:
                description = description_file.read()

        # Status labels to display in query form
        labels = []
        datasource_options = worker_class.get_options()
        is_local = "local" if hasattr(worker_class, "is_local") and worker_class.is_local else "external"
        is_static = True if hasattr(worker_class, "is_static") and worker_class.is_static else False
        labels.append(is_local)

        if is_static:
            labels.append("static")

        if hasattr(worker_class, "is_from_extension"):
            labels.append("extension")

        # Get daily post counts for local datasource to display in a graph
        if is_local == "local":

            total_counts = db.fetchall("SELECT board, SUM(count) AS post_count FROM metrics WHERE metric = 'posts_per_day' AND datasource = %s GROUP BY board", (database_db_id,))

            if total_counts:
                
                total_counts = {d["board"]: d["post_count"] for d in total_counts}
                
                boards = set(total_counts.keys())
                
                # Fetch date counts per board from the database
                db_counts = db.fetchall("SELECT board, date, count FROM metrics WHERE metric = 'posts_per_day' AND datasource = %s", (database_db_id,))

                # Get the first and last days for padding
                all_dates = [datetime.strptime(row["date"], "%Y-%m-%d").timestamp() for row in db_counts]
                first_date = datetime.fromtimestamp(min(all_dates))
                last_date = datetime.fromtimestamp(max(all_dates))
                
                # Format the dates in a regular dictionary to be used by Highcharts
                daily_counts = {"first_date": (first_date.year, first_date.month, first_date.day)}
                for board in boards:
                    daily_counts[board] = {row["date"]: row["count"] for row in db_counts if row["board"] == board}
                    # Then make sure the empty dates are filled with 0
                    # and each board has the same amount of values.
                    daily_counts[board] = [v for k, v in pad_interval(daily_counts[board], first_interval=first_date)[1].items()]

        references = worker_class.references if hasattr(worker_class, "references") else None        

    return render_template('data-overview.html', datasources=datasources, datasource_id=datasource_id, description=description, labels=labels, total_counts=total_counts, daily_counts=daily_counts, github_url=github_url, references=references)

@app.route('/get-boards/<string:datasource>/')
@login_required
def getboards(datasource):
    if datasource not in config.get("datasources.enabled"):
        result = False
    else:
        result = config.get(datasource + "-search.boards", False)

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
    page_folder = Path(config.get('PATH_ROOT'), "webtool", "pages")
    page_path = page_folder.joinpath(page + ".md")

    if not page_path.exists():
        return error(404, error="Page not found")

    with page_path.open(encoding="utf-8") as file:
        page_raw = file.read()
        page_parsed = markdown.markdown(page_raw)
        page_parsed = re.sub(r"<h2>(.*)</h2>", r"<h2><span>\1</span></h2>", page_parsed)

        if config.get("mail.admin_email"):
            # replace this one explicitly instead of doing a generic config
            # filter, to avoid accidentally exposing config values
            admin_email = config.get("mail.admin_email", "4cat-admin@example.com")
            page_parsed = page_parsed.replace("%%ADMIN_EMAIL%%", admin_email)

    return render_template("page.html", body_content=page_parsed, body_class=page_class, page_name=page)