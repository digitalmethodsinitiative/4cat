"""

4CAT processor views - generated for specific processors.

"""

import os
import re
import csv
import json
import glob
import config
import markdown

from pathlib import Path

import backend

from flask import render_template, jsonify, abort, request, redirect, send_from_directory, flash, get_flashed_messages, \
	url_for
from flask_login import login_required, current_user

from webtool import app, db, log
from webtool.lib.helpers import Pagination, get_preview, error

from webtool.api_tool import delete_dataset, toggle_favourite, queue_processor

from backend.lib.dataset import DataSet
from backend.lib.queue import JobQueue

@app.route('/sigma-network/', methods=["POST"])
@login_required
def sigma_network():
	"""
	View a sigma js network.
	Part of the sigma js processor.

	:param str key:  Dataset key
	:return:  HTML preview
	"""

	network_data = request.json

	return render_template("processor-templates/sigma-network.html", network_data=network_data)
