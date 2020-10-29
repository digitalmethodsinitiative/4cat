"""
Create an image wall of the most-used images
"""
import requests
import hashlib
import random
import shutil
import base64
import math
import time
import csv
import re

from pathlib import Path
from PIL import Image, ImageFile, ImageOps

from lxml import etree
from lxml.cssselect import CSSSelector as css
from io import StringIO

import config
from backend.lib.helpers import UserInput
from backend.abstract.processor import BasicProcessor


__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)

class ImageWallGenerator(BasicProcessor):
	"""
	Image wall generator

	Create an image wall from the top images in the dataset
	"""
	type = "image-wall"  # job type ID
	category = "Visual"  # category
	title = "Image wall"  # title displayed in UI
	description = "Download top images and create an image wall. The amount of images used can be configured; the more images, the longer it takes to create the image wall. May take a while to complete as images need to be downloaded externally."  # description displayed in UI
	extension = "png"  # extension of result file, used internally and in UI
	accepts = ["top-images", "tiktok-search", "instagram-search"]  # query types this post-processor accepts as input
	datasources = ["4chan", "tiktok", "instagram"]

	input = "csv:filename,url_4cat"
	output = "png"

	options = {
		"amount": {
			"type": UserInput.OPTION_TEXT,
			"help": "No. of images (max 200)",
			"default": 112,
			"min": 0,
			"max": 200
		}
	}

	# to help with rate-limiting
	previous_download = 0

	# images will be arranged and resized to fit these image wall dimensions
	# note that image aspect ratio may not allow for a precise fit
	TARGET_WIDTH = 2560
	TARGET_HEIGHT = 1440

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column with image hashes, one with the first file name used
		for the image, and one with the amount of times the image was used
		"""
		images = {}

		self.dataset.update_status("Reading source file")
		parent = self.dataset.get_genealogy()[0]

		urls = []
		# determine where and how to get the image
		# this is different between 4chan and other data sources since for
		# 4chan the file may be stored locally
		if parent.parameters["datasource"] == "4chan":
			column_attempt = []
			column_attempt.append("url_fireden" if parent.parameters["board"] == "v" else "url_4plebs")
			rate_limit = 1 if parent.parameters["board"] == "v" else 16
			image_download_method = self.get_image_4chan
			tile_width = 100
			tile_height = 100

		else:
			column_attempt = ["thumbnail_url", "url"]
			image_download_method = self.get_image_generic
			rate_limit = 1
			tile_width = 200
			tile_height = None

		try:
			amount = max(0, min(200, int(self.parameters.get("amount", 0))))
		except ValueError:
			amount = 100


		# prepare staging area
		tmp_path = self.dataset.get_staging_area()
		if not tmp_path.exists():
			tmp_path.mkdir()

		with open(self.source_file) as source:
			csvfile = csv.DictReader(source)
			for post in csvfile:
				if len(urls) >= amount:
					break

				for field in column_attempt:
					if field in post:
						urls.append(post[field])
						break

		# randomize it
		random.shuffle(urls)

		# prepare
		ImageFile.LOAD_TRUNCATED_IMAGES = True
		counter = 0
		wall = None

		# loop through images and copy them onto the wall
		for path in urls:
			counter += 1
			self.dataset.update_status("Downloading image %i of %i" % (counter, len(urls)))

			# acquire and resize image
			try:
				picture = image_download_method(path, tmp_path, rate_limit=rate_limit)
			except (requests.RequestException, IndexError, FileNotFoundError, OSError) as e:
				# increase the counter here to leave an empty space for the
				# missing image, since that itself can be significant
				continue

			if not wall:
				# we can only initialise the wall here, since before we
				# download an image we don't know what the best dimensions are
				if not tile_width:
					tile_width = int(picture.width)
				if not tile_height:
					tile_height = int((tile_width / picture.width) * picture.height)

				ratio = self.TARGET_WIDTH / self.TARGET_HEIGHT
				tiles_y = math.ceil(math.sqrt((tile_width * len(urls)) / (ratio * tile_height)))
				tiles_x = math.ceil(len(urls) / tiles_y)
				wall = Image.new('RGB', (tiles_x * tile_width, tiles_y * tile_height))

			picture = ImageOps.fit(picture, (tile_width, tile_height), method=Image.BILINEAR)

			# put image on wall
			index = counter - 1
			x = index % tiles_x
			y = math.floor(index / tiles_x)
			wall.paste(picture, (x * tile_width, y * tile_height))


		if not wall:
			self.dataset.update_status("No images could be downloaded", is_final=True)
			shutil.rmtree(tmp_path)
			self.dataset.finish(0)
			return

		if wall.width > self.TARGET_WIDTH:
			self.dataset.update_status("Resizing image wall")
			new_height = math.ceil((self.TARGET_WIDTH / wall.width) * wall.height)
			wall = ImageOps.fit(wall, (self.TARGET_WIDTH, new_height), method=Image.BILINEAR)

		# finish up
		self.dataset.update_status("Saving result")
		wall.save(str(self.dataset.get_results_path()))
		shutil.rmtree(tmp_path)

		self.dataset.update_status("Finished")
		self.dataset.finish(counter)

	def get_image_generic(self, path, staging, rate_limit = 0):
		while self.previous_download > time.time() - rate_limit:
			time.sleep(0.1)

		self.previous_download = time.time()
		image = requests.get(path, stream=True)
		image.raw.decode_content = True

		staging = staging.joinpath("temp-image")

		with staging.open("wb") as output:
			for chunk in image.iter_content(1024):
				output.write(chunk)

		picture = Image.open(str(staging))
		picture.load()
		staging.unlink()

		return picture

	def get_image_4chan(self, path, staging, rate_limit=0):
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
		# do we have the file locally?
		filename = Path(config.PATH_IMAGES, path.split("/")[-1])
		if filename.exists():
			return Image.open(str(filename))


		while self.previous_download > time.time() - rate_limit:
			time.sleep(0.1)

		self.previous_download = time.time()

		rate_regex = re.compile(r"Search limit exceeded. Please wait ([0-9]+) seconds before attempting again.")

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
		if config.PATH_IMAGES and Path(config.PATH_ROOT, config.PATH_IMAGES).exists():
			md5 = hashlib.md5()

			based_hash = path.split("/")[-1].split(".")[0].replace("_", "/")
			extension = image_url.split(".")[-1].lower()
			md5.update(base64.b64decode(based_hash))

			local_path = Path(config.PATH_IMAGES, md5.hexdigest() + "." + extension)
			delete_after = False
		else:
			local_path = staging.joinpath("temp-image")
			delete_after = True

		# save file, somewhere
		with local_path.open('wb') as file:
			for chunk in image.iter_content(1024):
				file.write(chunk)

		# avoid getting rate-limited by image source
		time.sleep(rate_limit)
		picture = Image.open(local_path)

		# if no image folder is configured, delete the temporary file
		if delete_after:
			local_path.unlink()

		return picture
