"""
4CAT Web Tool views - pages to be viewed by the user
"""
import os
import csv
import json

import config

from pathlib import Path

import backend

from flask import render_template, jsonify, abort
from flask_login import login_required, current_user

from webtool import app, db

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


@app.route('/get-boards/<string:datasource>/')
@login_required
def getboards(datasource):
    if datasource not in config.DATASOURCES or "boards" not in config.DATASOURCES[datasource]:
        result = False
    else:
        result = config.DATASOURCES[datasource]["boards"]

    return jsonify(result)
