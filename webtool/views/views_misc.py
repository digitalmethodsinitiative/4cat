"""
4CAT Web Tool views - pages to be viewed by the user
"""
import os
import csv
import json

import config

from pathlib import Path
from datetime import datetime

import backend

from flask import render_template, jsonify, abort
from flask_login import login_required, current_user

from webtool import app, db
from webtool.lib.helpers import pad_interval

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


@app.route('/create-dataset/')
@login_required
def show_index():
    """
    Main tool frontend
    """
    datasources = {datasource: metadata for datasource, metadata in backend.all_modules.datasources.items() if
                   metadata["has_worker"] and metadata["has_options"]}

    return render_template('create-dataset.html', datasources=datasources)


@app.route('/data-overview/')
@app.route('/data-overview/<string:datasource>')
@login_required
def data_overview(datasource=None):
    """
    Main tool frontend
    """
    datasources = {datasource: metadata for datasource, metadata in backend.all_modules.datasources.items() if
                   metadata["has_worker"] and metadata["has_options"]}

    if datasource not in datasources:
        datasource_name = None

    github_url = config.GITHUB_URL

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

        # Get description
        description_path = Path(datasources[datasource_id].get("path"), "DESCRIPTION.md")
        if description_path.exists():
            with description_path.open() as description_file:
                description = description_file.read()

        # Status labels to display in query form
        labels = []
        datasource_options = worker_class.get_options()
        is_local = "local" if hasattr(worker_class, "is_local") and worker_class.is_local else "external"
        is_static = True if hasattr(worker_class, "is_static") and worker_class.is_static else False
        labels.append(is_local)

        if is_static:
            labels.append("static")

        # Get daily post counts for local datasource to display in a graph
        if is_local == "local":

            total_counts = db.fetchall("SELECT board, SUM(count) AS post_count FROM metrics WHERE metric = 'posts_per_day' AND datasource = %s GROUP BY board", (datasource_id,))
            total_counts = {d["board"]: d["post_count"] for d in total_counts}
            
            boards = set(total_counts.keys())
            
            # Fetch date counts per board from the database
            db_counts = db.fetchall("SELECT board, date, count FROM metrics WHERE metric = 'posts_per_day' AND datasource = %s", (datasource_id,))

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
    if datasource not in config.DATASOURCES or "boards" not in config.DATASOURCES[datasource]:
        result = False
    else:
        result = config.DATASOURCES[datasource]["boards"]

    return jsonify(result)
