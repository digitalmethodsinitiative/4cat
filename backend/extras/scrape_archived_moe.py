import requests
import argparse
import json
import re

from lxml import etree as xmltree
import lxml.html

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
	return lxml.html.tostring(node)[opening_tag:closing_tag].decode("utf-8")

def fsize(size_str):
	if size_str[-3:-1] == "KiB":
		return int(size_str[:-3]) * 1000

	if size_str[-3:-1] == "MiB":
		return int(size_str[:3]) * 1000000

	return int(re.sub(r"^[0-9]", "", size_str))

def tree_to_op(tree):
	all_posts = []
	op = tree.xpath(".//article[contains(@class, 'post_is_op')]")
	if not op:
		return None

	op = op[0]
	stats = op.xpath(".//div[contains(@class, 'pull-right') and contains(@title, 'Post Count')]")[0]
	op_image = op.xpath(".//div[contains(@class, 'thread_image_box')]")[0]
	op_image_stats = stringify_children(op_image.xpath(".//div[@class='post_file']")[0])

	try:
		op_body = stringify_children(op.xpath(".//div[@class='text']")[0])
	except IndexError:
		op_body = ""

	try:
		op_subject = ""
	except IndexError:
		op_subject = ""

	op = {
		"no": int(op.attrib.get("data-thread-num")),
		"now": op.xpath(".//time")[0].attrib.get("data-original-time").split(" ")[2].strip(),
		"name": stringify_children(op.xpath(".//span[@class='post_author']")[0]),
		"sub": op_subject,
		"com": op_body,
		"filename": stringify_children(op_image.xpath(".//a[@class='post_file_filename']")[0]),
		"ext": "." + op_image.xpath(".//a[contains(@class, 'thread_image_link')]")[0].attrib.get("href").split("/")[-1].split(".")[1],
		"w": int(op_image_stats.split(",")[1].strip().split("x")[0]),
		"h": int(op_image_stats.split(",")[1].strip().split("x")[1]),
		"tn_w": "",
		"tn_h": "",
		"tim": op_image.xpath(".//a[contains(@class, 'thread_image_link')]")[0].attrib.get("href").split("/")[-1].split(".")[0],
		"time": "",
		"md5": op_image.xpath(".//div[contains(@class, 'post_file_controls')]")[0].xpath(".//a[contains(@href, 'search/image')]")[0].attrib.get("href").split("/")[-2],
		"fsize": fsize(op_image_stats.split(",")[0].strip()),
		"resto": 0,
		"semantic_url": "",
		"replies": int(stats[1:-1].split("/")[0].strip()),
		"images": int(stats[1:-1].split("/")[1].strip()),
		"unique_ips": -1
	}

	return op

def tree_to_posts(tree, thread_id):
	posts = tree.xpath(".//article[contains(@class, 'post ') and contains(@class, 'doc_id_')]")

	for post_tree in posts:
		try:
			post_body = stringify_children(post_tree.xpath(".//div[@class='text']")[0])
		except IndexError:
			post_body = ""

		post = {
			"now": post_tree.xpath(".//time")[0].attrib.get("data-original-time").split(" ")[2].strip(),
			"name": stringify_children(post_tree.xpath(".//span[@class='post_author']")[0]),
			"com": post_body,
			"filename": stringify_children(op_image.xpath(".//a[@class='post_file_filename']")[0]),
			"ext": "." + op_image.xpath(".//a[contains(@class, 'thread_image_link')]")[0].attrib.get("href").split("/")[-1].split(".")[1],
			"w": int(op_image_stats.split(",")[1].strip().split("x")[0]),
			"h": int(op_image_stats.split(",")[1].strip().split("x")[1]),
			"tn_w": "",
			"tn_h": "",
			"tim": op_image.xpath(".//a[contains(@class, 'thread_image_link')]")[0].attrib.get("href").split("/")[-1].split(".")[0],
			"time": "",
			"md5": op_image.xpath(".//div[contains(@class, 'post_file_controls')]")[0].xpath(".//a[contains(@href, 'search/image')]")[0].attrib.get("href").split("/")[-2],
			"fsize": fsize(op_image_stats.split(",")[0].strip()),
			"resto": thread_id,
			"id": int(op.attrib.get("data-thread-num")),
			"semantic_url": "",
			"replies": int(stats[1:-1].split("/")[0].strip()),
			"images": int(stats[1:-1].split("/")[1].strip()),
			"unique_ips": -1
		}

		image = post_tree.xpath(".//img[@class='post_image']")
		if image:
			post = {**post, **{
				"filename": '',
				"md5": "",
				"fsize": "",
				"w": "",
				"h": "",
				"tim": "",
				"ext": ""
			}}

		yield post

def thread_html_to_dict(html):
	try:
		tree = xmltree.fromstring(html, parser=xmltree.HTMLParser())
	except xmltree.ParseError as e:
		return None

	posts = []
	op = tree_to_op(tree)
	posts.append(op)

	for post in tree_to_posts(tree, op["no"]):
		posts.append(post)

	with open("thread.json", "w") as output:
		output.write(json.dumps(posts))


cli = argparse.ArgumentParser()
cli.add_argument("-b", "--board", required=True, help="Board to scrape, e.g. v")
cli.add_argument("-p", "--page", default=1, help="Page to start scraping (starts at 1)")
args = cli.parse_args()

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
		print("Thread ID: %s" % thread)
		thread =

	page += 1


print("Done.")
