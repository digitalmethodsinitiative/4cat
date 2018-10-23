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


if len(sys.argv) > 1 and sys.argv[1] == "config":
	print("graph_title Deleted threads and posts per hour")
	print("graph_args -l 0")
	print("graph_vlabel deleted")
	print("graph_category 4cat")
	print("graph_info The amount of posts and threads that were found to be deleted over the past hour")
	print("posts.warning 0:1000")
	print("posts.critical 0:2500")
	print("threads.warning 0:500")
	print("threads.critical 0:1000")
	print("posts.label Posts")
	print("threads.label Threads")
	sys.exit(0)

try:
	posts = get_api("posts")
	threads = get_api("threads")
	posts = json.loads(posts)["response"]
	threads = json.loads(threads)["response"]
	print("posts.value %i" % posts["1h"])
	print("threads.value %i" % threads["1h"])
except (KeyError, json.JSONDecodeError, ConnectionError) as e:
	print(e)
	print("posts.value 0")
	print("threads.value 0")
