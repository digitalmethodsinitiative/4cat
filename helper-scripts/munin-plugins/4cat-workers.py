#!/usr/bin/python3

# Munin plugin for 4CAT - Current active workers
# Reports the number of workers currently active in the 4CAT backend, sorted by
# job type. Can be used to see if the system is keeping up with user demand.

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


nodata = False
try:
	apidata = json.loads(get_api("workers"))["response"]
except (json.JSONDecodeError, KeyError) as e:
	nodata = True

if len(sys.argv) > 1 and sys.argv[1] == "config":
	print("graph_title 4CAT active workers")
	print("graph_args -l 0")
	print("graph_vlabel workers")
	print("graph_category 4cat")
	print("graph_info The amount of workers running in 4CAT, by type")
	print("worker-total.critical 3:50")
	if not nodata:
		for type in apidata:
			print("worker-%s.label %s" % (type, type))
	else:
		print("worker-total.label total")

	sys.exit(0)

if not nodata:
	for type in apidata:
		print("worker-%s.value %i" % (type, apidata[type]))
else:
	print("worker-total.value 0")