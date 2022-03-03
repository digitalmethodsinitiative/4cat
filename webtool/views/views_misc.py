"""
4CAT Web Tool views - pages to be viewed by the user
"""
import re
import os
import csv
import json
import markdown

import config

from pathlib import Path

import backend

from flask import render_template, jsonify
from flask_login import login_required, current_user

from webtool import app, db
from webtool.lib.helpers import error

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
        return error(403, message="You cannot view or generate access tokens without a personal acount.")

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
    page_folder = Path(config.PATH_ROOT, "webtool", "pages")
    page_path = page_folder.joinpath(page + ".md")

    if not page_path.exists():
        return error(404, error="Page not found")

    with page_path.open(encoding="utf-8") as file:
        page_raw = file.read()
        page_parsed = markdown.markdown(page_raw)
        page_parsed = re.sub(r"<h2>(.*)</h2>", r"<h2><span>\1</span></h2>", page_parsed)

        if config.ADMIN_EMAILS:
            # replace this one explicitly instead of doing a generic config
            # filter, to avoid accidentally exposing config values
            admin_email = config.ADMIN_EMAILS[0] if config.ADMIN_EMAILS else "4cat-admin@example.com"
            page_parsed = page_parsed.replace("%%ADMIN_EMAIL%%", admin_email)

    return render_template("page.html", body_content=page_parsed, body_class=page_class, page_name=page)