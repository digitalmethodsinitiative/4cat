"""
Extract most-used images from corpus
"""
import hashlib
import base64
import re
import config
import csv
import shutil

from collections import Counter
from backend.abstract.processor import BasicProcessor
from backend.lib.helpers import UserInput

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class TopImageCounter(BasicProcessor):
	"""
	Top Image listing

	Collects all images used in a data set, and sorts by most-used.
	"""
	type = "top-images"  # job type ID
	category = "Post metrics"  # category
	title = "Top images"  # title displayed in UI
	description = "Collect all images used in the data set, and sort by most used. Contains URLs through which the images may be downloaded."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	input = "csv"
	output = "csv"

	options = {
		"overwrite": {
			"type": UserInput.OPTION_TOGGLE,
			"default": False,
			"help": "Add extracted image URLs to source csv",
			"tooltip": "This will add a new column, \"img_url\", to the dataset's csv file."
		}
	}

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column with image hashes, one with the first file name used
		for the image, and one with the amount of times the image was used
		"""
		images = {}

		restuls = None

		# 4chan data has specific columns for image information, so treat this a bit differently.
		if self.parent.parameters["datasource"] == "4chan":
			
			self.dataset.update_status("Extracting image links from source file")
			
			for post in self.iterate_csv_items(self.source_file):

				if not post["image_file"]:
					continue

				if post["image_md5"] not in images:
					# md5 is stored encoded; make it normal ascii
					md5 = hashlib.md5()
					md5.update(base64.b64decode(post["image_md5"]))

					images[post["image_md5"]] = {
						"filename": post["image_file"],
						"md5": md5.hexdigest(),
						"hash": post["image_md5"],
						"count": 0
					}

				images[post["image_md5"]]["count"] += 1

			top_images = {id: images[id] for id in sorted(images, key=lambda id: images[id]["count"], reverse=True)}

			results = [{
				"md5_hash": images[id]["md5"],
				"filename": images[id]["filename"],
				"num_posts": images[id]["count"],
				"url_4cat": ("s" if config.FlaskConfig.SERVER_HTTPS else "") + "://" + config.FlaskConfig.SERVER_NAME + "/api/image/" + images[id]["md5"] + "." + images[id]["filename"].split(".")[
					-1],
				"url_4plebs": "https://archive.4plebs.org/_/search/image/" + images[id]["hash"].replace("/", "_"),
				"url_fireden": "https://boards.fireden.net/_/search/image/" + images[id]["hash"].replace("/", "_")
			} for id in top_images]

		else:
			
			# Important: image link regex.
			# Makes sure that it gets "http://site.com/img.jpg", but also
			# more complicated ones like
			# https://preview.redd.it/3thfhsrsykb61.gif?format=mp4&s=afc1e4568789d2a0095bd1c91c5010860ff76834
			img_link_regex = re.compile(r"(?:www\.|https?:\/\/)[^\s\(\)\]\[]*\.(?:png|jpg|jpeg|gif|gifv)[^\s\(\)\]\[]*", re.IGNORECASE)

			# Imgur and gfycat links that do not end in an extention are also accepted.
			# These can later be downloaded by adding an extention.
			img_domain_regex = re.compile(r"(?:https:\/\/gfycat\.com\/|https:\/\/imgur\.com\/)[^\s\(\)\]\[]*", re.IGNORECASE)

			self.dataset.update_status("Extracting image links from source file")
			
			all_links = [] # Used for overwrite
			img_links = []
			
			for post in self.iterate_csv_items(self.source_file):

				post_img_links = []

				if "url" in post and (img_link_regex.match(post["url"]) or img_domain_regex.match(post["url"])):
					# some datasources may provide a specific URL per post
					# as a separate attribute.
					post_img_links.append(post["url"])

				if "urls" in post and (img_link_regex.search(post["urls"]) or img_domain_regex.search(post["url"])):
					
					# some datasources may provide a specific URL per post
					# as a separate attribute.
					urls = post["urls"].split(",")
					urls = list(set(urls)) # to prevent spamming
					for url in urls:
						if url.strip() and (img_link_regex.match(post["urls"]) or img_domain_regex.match(post["url"])):
							post_img_links.append(url)

				# We also take into account urls in the text body itself.
				# URLs need some processing because there may be multiple per post.
				body_links = img_link_regex.findall(post["body"]) + img_domain_regex.findall(post["body"])
				
				if body_links:
					post_img_links += body_links

				# Only keep unique links per post, to prevent spamming.
				post_img_links = list(set(post_img_links))

				# Always add to all_links, so we can easily add to the source file if needed.
				all_links.append(post_img_links)
				
				# Only add valid links to img_links.
				if post_img_links:
					img_links += post_img_links

			img_ranked = Counter(img_links)
			
			results = [{
				"img_url": k,
				"num_posts": v
			} for k, v in img_ranked.items()]

		if not results:
			self.dataset.update_status("Zero image URLs detected.")
			return

		# Also add the data to the original csv file, if indicated.
		if self.parameters.get("overwrite"):
			self.update_parent(all_links)

		self.write_csv_items_and_finish(results)

	def update_parent(self, li_urls):
		"""
		Update the original dataset with a column detailing the image urls.

		"""

		self.dataset.update_status("Adding image urls to the source file")

		# Get the source file data path
		genealogy = self.dataset.get_genealogy()
		parent = genealogy[0]
		parent_path = parent.get_results_path()

		# Get a temporary path where we can store the data
		tmp_path = self.dataset.get_staging_area()
		tmp_file_path = tmp_path.joinpath(parent_path.name)

		count = 0

		# Get field names
		with parent_path.open(encoding="utf-8") as input:
			reader = csv.DictReader(input)
			fieldnames = reader.fieldnames
			fieldnames.append("img_url")

		# Iterate through the original dataset and add values to a new img_link column
		self.dataset.update_status("Writing csv with nouns.")
		with tmp_file_path.open("w", encoding="utf-8", newline="") as output:

			writer = csv.DictWriter(output, fieldnames=fieldnames)
			writer.writeheader()

			count = 0

			for post in self.iterate_csv_items(parent_path):
				post["img_url"] = ", ".join(li_urls[count])
				writer.writerow(post)
				count += 1

		# Replace the source file path with the new file
		shutil.copy(str(tmp_file_path), str(parent_path))

		# delete temporary files and folder
		shutil.rmtree(tmp_path)

		self.dataset.update_status("Parent dataset updated.")
