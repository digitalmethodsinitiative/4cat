"""
Create an image wall of the most-used images
"""
import requests
import hashlib
import random
import base64
import math
import time
import os
import re

from csv import DictReader
from PIL import Image, ImageFile, ImageOps

from lxml import etree
from lxml.cssselect import CSSSelector as css
from io import StringIO

import config
from backend.lib.helpers import UserInput, get_absolute_folder
from backend.lib.query import SearchQuery
from backend.abstract.postprocessor import BasicPostProcessor


class ImageWallGenerator(BasicPostProcessor):
	"""
	Image wall generator

	Create an image wall from the top images in the dataset
	"""
	type = "image-wall"  # job type ID
	category = "Visual"  # category
	title = "Image wall"  # title displayed in UI
	description = "Download top images and create an image wall. The amount of images used can be configured; the more images, the longer it takes to create the image wall. May take a while to complete as images are sourced externally."  # description displayed in UI
	extension = "png"  # extension of result file, used internally and in UI
	accepts = ["top-images"]  # query types this post-processor accepts as input

	options = {
		"amount": {
			"type": UserInput.OPTION_TEXT,
			"help": "No. of images (max 200)",
			"default": 100,
			"min": 0,
			"max": 200
		}
	}

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column with image hashes, one with the first file name used
		for the image, and one with the amount of times the image was used
		"""
		images = {}

		self.query.update_status("Reading source file")
		parent = self.query.get_genealogy()[0]
		external = "fireden" if parent.parameters["board"] == "v" else "4plebs"
		rate_limit = 1 if external == "fireden" else 16

		urls = []

		try:
			amount = max(0, min(200, int(self.options.get("amount", 0))))
		except ValueError:
			amount = 100

		with open(self.source_file) as source:
			csv = DictReader(source)
			for post in csv:
				if len(urls) >= amount:
					break

				extension = post["filename"].split(".")[1].lower()
				if extension not in ("jpg", "jpeg", "png", "gif"):
					continue

				local_file = post["url_4cat"].split("/")[-1] + "." + extension
				local_path = get_absolute_folder(config.PATH_IMAGES) + "/" + local_file
				if os.path.exists(local_path):
					urls.append(local_path)
				else:
					urls.append(post["url_" + external])

		# randomize it
		random.shuffle(urls)

		# calculate image wall dimensions
		tiles_x = int(math.sqrt(len(urls))) + int(math.sqrt(len(urls)) / 3) + 1
		tiles_y = int(math.sqrt(len(urls))) - int(math.sqrt(len(urls)) / 3) + 1

		# initialize our canvas
		ImageFile.LOAD_TRUNCATED_IMAGES = True
		tile_size = 100  # size of each tile, in pixels (they'll all be square)
		wall = Image.new('RGB', (tiles_x * tile_size, tiles_y * tile_size))
		counter = 0

		# loop through images and copy them onto the wall
		rate_regex = re.compile(r"Search limit exceeded. Please wait ([0-9]+) seconds before attempting again.")
		for path in urls:
			counter += 1
			self.query.update_status("Downloading image %i of %i" % (counter, len(urls)))

			# acquire and resize image
			try:
				picture = self.get_image(path, rate_limit=rate_limit)
			except (requests.RequestException, IndexError, FileNotFoundError):
				continue

			picture = ImageOps.fit(picture, (tile_size, tile_size), method=Image.BILINEAR)

			# put image on wall
			index = counter - 1
			x = index % tiles_x
			y = math.floor(index / tiles_x)
			wall.paste(picture, (x * tile_size, y * tile_size))

		# finish up
		self.query.update_status("Saving result")
		wall.save(self.query.get_results_path())

		self.query.update_status("Finished")
		self.query.finish(len(urls))

	def get_image(self, path, rate_limit=0):
		"""
		Create image from path

		If the path is local, simply read the local path and return an Image
		representing it. If not, attempt to download the image from elsewhere,
		and cache the downloaded result if possible, else discard the file
		afterwards.

		:param path:  Path to image, either a local path or a URL
		:param rate_limit:  Seconds to wait after downloading, if downloading

		:return Image:  Image object, or nothing if loading it failed
		"""
		rate_regex = re.compile(r"Search limit exceeded. Please wait ([0-9]+) seconds before attempting again.")

		if path[0:4] != "http":
			return Image.open(path)

		# get link to image from external HTML search results
		# detect rate limiting and wait until we're good to go again
		page = requests.get(path)
		rate_limited = rate_regex.search(page.content.decode("utf-8"))

		while rate_limited:
			self.log.debug("Rate-limited by external source. Waiting %s seconds." % rate_limited[1])
			time.sleep(int(rate_limited[1]))
			page = requests.get(path)
			rate_limited = rate_regex.search(page.content.decode("utf-8"))

		# get link to image file from HTML returned
		parser = etree.HTMLParser()
		tree = etree.parse(StringIO(page.content.decode("utf-8")), parser)
		image_url = css("a.thread_image_link")(tree)[0].get("href")

		# download image itself
		image = requests.get(image_url, stream=True)
		if image.status_code != 200:
			raise FileNotFoundError

		# cache the image for later, if needed
		if config.PATH_IMAGES:
			md5 = hashlib.md5()

			based_hash = path.split("/")[-1].split(".")[0].replace("_", "/")
			extension = image_url.split(".")[-1].lower()
			md5.update(base64.b64decode(based_hash))

			local_path = get_absolute_folder(
				config.PATH_IMAGES) + "/" + md5.hexdigest() + "." + extension
			delete_after = False
		else:
			local_path = self.query.get_results_path() + "-temp"
			delete_after = True

		# save file, somewhere
		with open(local_path, 'wb') as file:
			for chunk in image.iter_content(1024):
				file.write(chunk)

		# avoid getting rate-limited by image source
		time.sleep(rate_limit)
		picture = Image.open(local_path)

		# if no image folder is configured, delete the temporary file
		if delete_after:
			os.unlink(local_path)

		return picture
