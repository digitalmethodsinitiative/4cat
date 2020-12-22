#!/usr/bin/python3

# Munin plugin for 4CAT - Datasets per hour
# Reports the number of datasets created over the past hour. Can be used to check
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
	print("graph_title Datasets created per hour")
	print("graph_args -l 0")
	print("graph_vlabel datasets")
	print("graph_category 4cat")
	print("graph_info The number of datasets created over the past hour")
	print("datasetsh.warning 1250")
	print("datasetsh.critical 2500")
	print("datasetsh.label Datasets created")
	sys.exit(0)

try:
	datasets = get_api("datasets")
	datasets = json.loads(datasets)["response"]
	print("datasetsh.value %i" % datasets["1h"])
except (KeyError, json.JSONDecodeError, ConnectionError) as e:
	print(e)
	print("datasetsh.value 0")
