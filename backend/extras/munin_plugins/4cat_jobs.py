#!/usr/bin/python3
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


types = {
	"misc": "Unknown",
	"scheduler": "Scheduling",
	"image": "Images",
	"query": "Queries",
	"board": "Boards",
	"thread": "Threads",
	"total": "Total"
}

if len(sys.argv) > 1 and sys.argv[1] == "config":
	print("graph_title 4CAT Jobs per type")
	print("graph_args -l 0")
	print("graph_vlabel jobs")
	print("graph_category 4cat")
	print("graph_info The amount of jobs currently queued for processing by the 4CAT backend, by type of job")
	print("total.warning 1000:6000")
	print("total.critical 100:10000")
	for type in types:
		print("%s.label %s" % (type, types[type]))
	sys.exit(0)

try:
	values = json.loads(get_api("jobs"))["response"]
	for type in types:
		if type in values:
			print("%s.value %i" % (type, values[type]))
		else:
			print("%s.value 0" % type)
except (KeyError, json.JSONDecodeError, ConnectionError) as e:
	for type in types:
		print("%s.value 0" % type)
