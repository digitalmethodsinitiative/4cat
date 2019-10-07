import traceback
import datetime
import requests
import argparse
import json
import sys
import re

from pathlib import Path
from html.parser import HTMLParser

from lxml import etree as xmltree
import lxml.html

def strip_tags(html, convert_newlines=True):
	"""
	Strip HTML from a string

	:param html: HTML to strip
	:param convert_newlines: Convert <br> and </p> tags to \n before stripping
	:return: Stripped HTML
	"""
	if not html:
		return ""

	deduplicate_newlines = re.compile(r"\n+")

	if convert_newlines:
		html = html.replace("<br>", "\n").replace("</p>", "</p>\n")
		html = deduplicate_newlines.sub("\n", html)

	class HTMLStripper(HTMLParser):
		def __init__(self):
			super().__init__()
			self.reset()
			self.strict = False
			self.convert_charrefs = True
			self.fed = []

		def handle_data(self, data):
			self.fed.append(data)

		def get_data(self):
			return "".join(self.fed)

	stripper = HTMLStripper()
	stripper.feed(html)
	return stripper.get_data()

def stringify_children(node):
	"""
	Returns node contents, NOT stripped of tags

	Thanks, https://stackoverflow.com/a/32468202
	:param node:
	:return:
	"""
	if node is None or (len(node) == 0 and not getattr(node, 'text', None)):
		return ""
	node.attrib.clear()
	opening_tag = len(node.tag) + 2
	closing_tag = -(len(node.tag) + 3)
	return lxml.html.tostring(node).strip()[opening_tag:closing_tag].decode("utf-8").strip()

def fsize(size_str):
	if size_str[-3:] == "KiB":
		return int(size_str[:-3]) * 1024

	if size_str[-3:] == "MiB":
		return int(size_str[:-3]) * 1024 * 1024

	return int(re.sub(r"[^0-9]", "", size_str))

def totime(date):
	return int(datetime.datetime.strptime(date, "%Y-%m-%dT%H:%M:%S%z").timestamp())

def tree_to_op(tree):
	all_posts = []
	op = tree.xpath(".//article[contains(@class, 'post_is_op')]")
	if not op:
		return None

	op = op[0]
	op_image = op.xpath(".//div[contains(@class, 'thread_image_box')]")[0]
	op_image_stats = stringify_children(op_image.xpath(".//div[@class='post_file']")[0])

	try:
		op_body = stringify_children(op.xpath(".//div[@class='text']")[0])
	except IndexError:
		op_body = ""

	try:
		op_subject = stringify_children(op.xpath(".//h2")[0]).strip()
	except IndexError:
		op_subject = ""

	filename = op_image.xpath(".//a[@class='post_file_filename']")[0]
	filename = ".".join(filename.attrib.get("filename", stringify_children(filename)).split(".")[:-1])

	if not op_subject:
		semantic_url = re.sub(r"[^a-z0-9 ]", "", " ".join(strip_tags(op_body).split(" ")[:9]).lower()).replace(" ", "-")
	else:
		semantic_url = re.sub(r"[^a-z0-9 ]", "", op_subject.lower()).replace(" ", "-")

	op_post = {
		"no": int(op.attrib.get("data-thread-num")),
		"now": op.xpath(".//time")[0].attrib.get("title").strip().split(" ")[2],
		"name": stringify_children(op.xpath(".//span[@class='post_author']")[0]),
		"sub": op_subject,
		"com": op_body,
		"filename": filename,
		"ext": "." + op_image.xpath(".//a[contains(@class, 'thread_image_link')]")[0].attrib.get("href").split("/")[-1].split(".")[1],
		"w": int(op_image_stats.split(",")[1].strip().split("x")[0]),
		"h": int(op_image_stats.split(",")[1].strip().split("x")[1]),
		"tn_w": -1,
		"tn_h": -1,
		"tim": int(op_image.xpath(".//a[contains(@class, 'thread_image_link')]")[0].attrib.get("href").split("/")[-1].split(".")[0]),
		"time": totime(op.xpath(".//time")[0].attrib.get("datetime").strip()),
		"md5": op_image.xpath(".//div[contains(@class, 'post_file_controls')]")[0].xpath(".//a[contains(@href, 'search/image')]")[0].attrib.get("href").split("/")[-2]+"==",
		"fsize": fsize(op_image_stats.split(",")[0].strip()),
		"resto": 0,
		"semantic_url": semantic_url,
		"replies": len(tree.xpath(".//aside[@class='posts']/article[contains(@class, 'post doc_id')]")),
		"images": len(tree.xpath(".//aside[@class='posts']/article[contains(@class, 'post') and contains(@class, 'has_image')]")),
		"unique_ips": -1
	}

	country = op.xpath(".//span[contains(@class, 'flag')]")
	if country:
		op_post = {**op_post, **{
			"country_code": country[0].attrib["class"].split(" ")[1].split("-")[1].upper(),
			"country_name": country[0].attrib.get("title")
		}}

	return op_post

def tree_to_posts(tree, thread_id):
	posts = tree.xpath(".//article[contains(@class, 'post ') and contains(@class, 'doc_id_')]")

	for post_tree in posts:
		try:
			post_body = stringify_children(post_tree.xpath(".//div[@class='text']")[0])
		except IndexError:
			post_body = ""

		post = {
			"now": post_tree.xpath(".//time")[0].attrib.get("title").strip().split(" ")[2],
			"name": stringify_children(post_tree.xpath(".//span[@class='post_author']")[0]),
			"com": post_body,
			"time": totime(post_tree.xpath(".//time")[0].attrib.get("datetime").strip()),
			"resto": thread_id,
			"no": int(post_tree.attrib.get("id")),
		}

		image = post_tree.xpath(".//img[@class='post_image']")
		if image:
			metadata = post_tree.xpath(".//div[@class='post_file']")[0]
			link = metadata.xpath(".//a[@class='post_file_filename']")[0]
			dimensions = stringify_children(metadata.xpath(".//span[@class='post_file_metadata']")[0]).strip()

			filename = link.attrib.get("title")
			if not filename:
				filename = stringify_children(link)

			post = {**post, **{
				"filename": ".".join(filename.split(".")[:-1]),
				"md5": image[0].attrib.get("data-md5"),
				"fsize": fsize(dimensions.split(",")[0]),
				"w": int(dimensions.split(",")[1].split("x")[0]),
				"h": int(dimensions.split(",")[1].split("x")[1]),
				"tim": int(post_tree.xpath(".//a[contains(@class, 'thread_image_link')]")[0].attrib.get("href").split("/")[-1].split(".")[0]),
				"ext": "." + filename.split(".")[-1],
				"tn_w": -1,
				"tn_h": -1,
			}}

		country = post_tree.xpath(".//span[contains(@class, 'flag')]")
		if country:
			post = {**post, **{
				"country_code": country[0].attrib["class"].split(" ")[1].split("-")[1].upper(),
				"country_name": country[0].attrib.get("title")
			}}

		yield post

def thread_html_to_dict(html):
	tree = xmltree.fromstring(html, parser=xmltree.HTMLParser())

	posts = []
	op = tree_to_op(tree)
	posts.append(op)

	for post in tree_to_posts(tree, op["no"]):
		posts.append(post)

	return {"posts": posts}


cli = argparse.ArgumentParser()
cli.add_argument("-b", "--board", required=True, help="Board to scrape, e.g. v")
cli.add_argument("-o", "--output", required=True, help="Path to folder with output JSON")
cli.add_argument("-p", "--page", default=1, help="Page to start scraping (starts at 1)")
args = cli.parse_args()

folder = Path(args.output)
if not folder.exists() or not folder.is_dir():
	print("Folder %s does not exist or is not a folder." % args.output)
	sys.exit(1)

page = args.page
thread_link = re.compile(r'<a href="https://archived.moe/[^/]+/thread/([0-9]+)/#reply" class="btnr parent">Reply</a>')

while True:
	url = "https://archived.moe/%s/page/%s/" % (args.board, page)
	print("Requesting page %s" % url)
	data = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:61.0) Gecko/20100101 Firefox/61.0"})
	if data.status_code != 200:
		print("HTTP Error %s for page %s. Stopping." % (data.status_code, url))
		break

	threads = thread_link.findall(data.content.decode("utf-8"))
	if not threads:
		print("No thread links found on page %s. Stopping." % url)
		break

	for thread in threads:
		thread_url = "https://archived.moe/%s/thread/%s/" % (args.board, thread)
		print("Thread ID: %s/%s" % (thread, thread_url))
		thread_file = Path(folder, "%s.json" % thread)

		if thread_file.exists():
			print("Already scraped, skipping.")
			continue

		try:
			thread_html = requests.get(thread_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:61.0) Gecko/20100101 Firefox/61.0"})
		except requests.RequestException as e:
			print("Error %s, stopping." % e)
			sys.exit(1)

		if thread_html.status_code != 200:
			print("Error %i, stopping." % thread_html.status_code)
			sys.exit(1)

		try:
			imported_thread = thread_html_to_dict(thread_html.content)
		except Exception as e:
			print("Error while importing, html dumped as error.html: %s" % traceback.format_exc())
			with open("error.html", "w") as output:
				output.write(thread_html.content.decode("utf-8"))
			sys.exit(1)

		with thread_file.open("w") as output:
			output.write(json.dumps(imported_thread, indent=2))


	page += 1


print("Done.")
