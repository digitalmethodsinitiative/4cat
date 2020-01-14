#!/usr/bin/python3

# Munin plugin for 4CAT - All jobs in queue
# Reports the number of jobs currently queued in the 4CAT backend, sorted by
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
        apidata = json.loads(get_api("jobs"))["response"]
except (json.JSONDecodeError, KeyError) as e:
        nodata = True

if len(sys.argv) > 1 and sys.argv[1] == "config":
	print("graph_title 4CAT Jobs per type")
	print("graph_args -l 0")
	print("graph_vlabel jobs")
	print("graph_category 4cat")
	print("graph_info The amount of jobs currently queued for processing by the 4CAT backend, by type of job")
	print("worker-total.warning 100:15000")
	print("worker-total.critical 50:20000")

	if not nodata:
		for type in apidata:
			print("worker-%s.label %s" % (type, type))
	else:
		print("total.label total")
	sys.exit(0)

if not nodata:
	for type in apidata:
		print("worker-%s.value %i" % (type, apidata[type]))
else:
	print("worker-total.value 0")