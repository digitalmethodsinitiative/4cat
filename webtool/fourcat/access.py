"""
Control access to web tool
"""
import fnmatch
import socket
import sys
import os

sys.path.insert(0, os.path.dirname(__file__) +  '/../..')
import config

from flask import request, abort
from fourcat import app

@app.before_request
def limit_to_hostname():
	"""
	Checks if host name matches whitelisted hostmask. If not, the request is
	aborted and a 403 Forbidden error is shown.
	"""
	if not config.FlaskConfig.LIMIT_HOSTNAME:
		return

	socket.setdefaulttimeout(2)
	hostname = socket.gethostbyaddr(request.remote_addr)[0]

	for hostmask in config.FlaskConfig.LIMIT_HOSTNAME:
		if fnmatch.filter([hostname], hostmask):
			return

	abort(403)