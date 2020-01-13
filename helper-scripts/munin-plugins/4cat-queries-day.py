#!/usr/bin/python3

# Munin plugin for 4CAT - Queries per day
# Reports the number of queries queried over the past day. Can be used to check
# user activity on the web tool.

import socket
import json
import sys


def get_api(type):
	api = socket.socket()
	api.connect(("localhost", 4444))
	api.sendall(json.dumps({"request": type}).encode("ascii"))
	response = api.recv(1024)
	api.close()

	return response


if len(sys.argv) > 1 and sys.argv[1] == "config":
	print("graph_title Search queries queued per day")
	print("graph_args -l 0")
	print("graph_vlabel queries")
	print("graph_category 4cat")
	print("graph_info The number of queries queued over the past day")
	print("queriesd.label Queries queued")
	sys.exit(0)

try:
	queries = get_api("queries")
	queries = json.loads(queries)["response"]
	print("queriesd.value %i" % queries["1d"])
except (KeyError, json.JSONDecodeError, ConnectionError) as e:
	print(e)
	print("queriesd.value 0")