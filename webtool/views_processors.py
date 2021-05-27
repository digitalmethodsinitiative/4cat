"""

4CAT processor views - generated for specific processors.

"""

from flask import render_template, request
from flask_login import login_required

from webtool import app


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
