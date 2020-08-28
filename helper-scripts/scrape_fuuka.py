"""
Scrape any FoolFuuka archive (e.g. archived.moe) and convert found data to
4chan API-compatible data files that may then be imported into 4CAT with
queue_folder.py
"""
import traceback
import requests
import argparse
import json
import time
import sys
import re

from pathlib import Path

postlink = re.compile(r"^&gt;&gt;([0-9]+)", flags=re.MULTILINE)
quote = re.compile(r"^&gt;([^\n]+)", flags=re.MULTILINE)

def htmlize(post):
	if not post:
		return ""

	post = post.replace(">", "&gt;")
	post = post.replace("<", "&lt;")

	post = postlink.sub('<a href="#p\\1" class="quotelink">&gt;&gt;\\1</a>', post)
	post = quote.sub('<span class="quote">&gt;\\1</span>', post)

	return post.strip().replace("\n", "<br>")

def fuuka_to_4chan(post, thread_id = 0):
	post_4chan = {
		"no": int(post["num"]),
		"now": post["fourchan_date"],
		"name": post["name"],
		"resto": thread_id,
		"time": int(post["timestamp"])
	}

	if post["comment"]:
		post_4chan["com"] = htmlize(post["comment"])

	if thread_id == 0:
		if not post["title"]:
			semantic_url = re.sub(r"[^a-z0-9 ]", "", " ".join(post["comment_sanitized"].split(" ")[:9]).lower()).replace(" ", "-")
		else:
			semantic_url = re.sub(r"[^a-z0-9 ]", "", post["title"].lower()).replace(" ", "-")

		post_4chan["semantic_url"] = semantic_url

	if post["capcode"]:
		try:
			post_4chan["capcode"] = {
				"M": "mod",
				"A": "admin",
				"D": "developer",
				"F": "founder"
			}[post["capcode"]]
		except KeyError:
			pass

	if post["trip"]:
		post_4chan["trip"] = post["trip"]

	if post["sticky"] and post["sticky"] != "0":
		post_4chan["sticky"] = 1

	if post["locked"] and post["locked"] != "0":
		post_4chan["closed"] = 1

	if post["title"]:
		post_4chan["sub"] = post["title"]

	if post["poster_hash"]:
		post_4chan["id"] = post["poster_hash"]

	if post["poster_country_name"]:
		post_4chan["country_name"] = post["poster_country_name"]

	if post["poster_country"]:
		post_4chan["country_code"] = post["poster_country"]

	if post["media"]:
		post_4chan = {**post_4chan, **{
			"filename": ".".join(post["media"]["media_filename"].split(".")[:-1]),
			"ext": "." + post["media"]["media_filename"].split(".")[-1],
			"w": int(post["media"]["media_w"]),
			"h": int(post["media"]["media_h"]),
			"tn_w": int(post["media"]["preview_w"]),
			"tn_h": int(post["media"]["preview_h"]),
			"tim": int(post["media"]["media_orig"].split(".")[0]),
			"md5": post["media"]["media_hash"],
			"fsize": int(post["media"]["media_size"])
		}}

		try:
			exif = json.loads(post["media"]["exif"])
			if "trollCountry" in exif:
				post_4chan["country_name"] = exif["trollCountry"]
			if "uniqueIps" in exif and thread_id == 0:
				post_4chan["uniqueIps"] = int(exif["uniqueIps"])
		except (json.JSONDecodeError, TypeError):
			pass

	return post_4chan

def thread(thread_json):
	posts = []

	thread_json = thread_json[list(thread_json.keys())[0]]

	op = fuuka_to_4chan(thread_json["op"])

	if "posts" in thread_json:
		posts = [fuuka_to_4chan(thread_json["posts"][id], op["no"]) for id in thread_json["posts"] if thread_json["posts"][id]["subnum"] == "0"]
		op["replies"] = len(posts)
		op["images"] = len([post for post in posts if "md5" in post])
	else:
		posts = []
		op["replies"] = 0
		op["images"] = 0

	posts.insert(0, op)

	return {"posts": posts}


cli = argparse.ArgumentParser()
cli.add_argument("-b", "--board", required=True, help="Board to scrape, e.g. v")
cli.add_argument("-o", "--output", required=True, help="Path to folder with output JSON")
cli.add_argument("-p", "--page", default=1, help="Page to start scraping (starts at 1)")
cli.add_argument("-u", "--url", default="https://archived.moe", help="URL Prefix")
args = cli.parse_args()

folder = Path(args.output)
if not folder.exists() or not folder.is_dir():
	print("Folder %s does not exist or is not a folder." % args.output)
	sys.exit(1)

page = int(args.page)

base_url = args.url + "/_/api/chan/index/?board=%s&page=" % args.board

while True:
	print("Page %i" % page)
	page_url = base_url + str(page)

	try:
		page_html = requests.get(page_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:61.0) Gecko/20100101 Firefox/61.0"})
	except requests.RequestException as e:
		print("RequestException while requesting page %i: %s" % (page, traceback.format_exc()))
		break

	if page_html.status_code != 200:
		print("HTTP error %i while scraping page %i, retrying in 10 seconds" % (page_html.status_code, page))
		time.sleep(10)
		continue

	try:
		page_json = json.loads(page_html.content)
	except json.JSONDecodeError:
		print("JSON decode error while trying to decode page %i, dumped as error.json" % page)
		with open("error.json", "wb") as output:
			output.write(page_html.content)
		break

	thread_ids = iter(list(page_json.keys()))
	retry = False
	while True:
		try:
			if not retry:
				thread_id = thread_ids.__next__()
			else:
				retry = False
		except StopIteration:
			break

		print("Thread %s" % thread_id)
		thread_path = Path(folder, "%s.json" % thread_id)
		if thread_path.exists():
			print("...already scraped, skipping.")
			continue

		thread_data = None
		thread_url = args.url + "/_/api/chan/thread/?board=%s&num=%s" % (args.board, thread_id)

		try:
			thread_html = requests.get(thread_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:61.0) Gecko/20100101 Firefox/61.0"})
		except requests.RequestException as e:
			print("RequestException while requesting thread %s: %s" % (thread_id, traceback.format_exc()))
			break

		if thread_html.status_code > 399 and thread_html.status_code < 500:
			print("HTTP error %i while scraping thread %s, skipping" % (thread_html.status_code, thread_id))
			continue
		if thread_html.status_code != 200:
			print("HTTP error %i while scraping thread %s, waiting 10 seconds before retrying" % (thread_html.status_code, thread_id))
			time.sleep(10)
			retry = True
			continue

		try:
			thread_json = json.loads(thread_html.content)
		except json.JSONDecodeError:
			print("JSON decode error while trying to decode thread %s, dumped as error.json" % thread_id)
			with open("error.json", "wb") as output:
				output.write(thread_html.content)
			break

		thread_path = Path(folder, "%s.json" % thread_id)
		with thread_path.open("w") as output:
			output.write(json.dumps(thread(thread_json), indent=2))

	page += 1

print("Done")