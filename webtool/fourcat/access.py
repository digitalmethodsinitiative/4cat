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
from fourcat.api import limiter

@app.before_request
def limit_to_hostname():
	"""
	Checks if host name matches whitelisted hostmask. If not, the request is
	aborted and a 403 Forbidden error is shown.
	"""
	if not config.FlaskConfig.HOSTNAME_WHITELIST:
		return

	socket.setdefaulttimeout(2)
	hostname = socket.gethostbyaddr(request.remote_addr)[0]

	for hostmask in config.FlaskConfig.HOSTNAME_WHITELIST:
		if fnmatch.filter([hostname], hostmask):
			return

	abort(403)

@limiter.request_filter
def exempt_from_limit():
	"""
	Checks if host name matches whitelisted hostmasks for exemption from API
	rate limiting.

	:return bool:  Whether the request's hostname is exempt
	"""
	if not config.FlaskConfig.HOSTNAME_WHITELIST_API:
		return False

	socket.setdefaulttimeout(2)
	hostname = socket.gethostbyaddr(request.remote_addr)[0]

	for hostmask in config.FlaskConfig.HOSTNAME_WHITELIST_API:
		if fnmatch.filter([hostname], hostmask):
			return True

	return False