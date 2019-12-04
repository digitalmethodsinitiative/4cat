"""
Download images linked in dataset
"""
import requests
import binascii
import hashlib
import zipfile
import shutil
import base64
import time
import re

from pathlib import Path
from csv import DictReader
from PIL import Image, ImageFile, ImageOps

from lxml import etree
from lxml.cssselect import CSSSelector as css
from io import StringIO

import config
from backend.lib.helpers import UserInput
from backend.abstract.processor import BasicProcessor


class ImageDownloader(BasicProcessor):
	"""
	Image downloader

	Downloads top images and saves as zip archive
	"""
	type = "image-downloader"  # job type ID
	category = "Visual"  # category
	title = "Download images"  # title displayed in UI
	description = "Download top images and compress as a zip file. May take a while to complete as images are sourced externally."  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI
	accepts = ["top-images"]  # query types this post-processor accepts as input

	input = "csv:filename,url_4cat"
	output = "zip"

	options = {
		"amount": {
			"type": UserInput.OPTION_TEXT,
			"help": "No. of images (max 1000)",
			"default": 100,
			"min": 0,
			"max": 1000
		}
	}

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column with image hashes, one with the first file name used
		for the image, and one with the amount of times the image was used
		"""
		images = {}

		self.dataset.update_status("Reading source file")
		parent = self.dataset.get_genealogy()[0]
		external = "fireden" if parent.parameters["board"] == "v" else "4plebs"
		rate_limit = 1 if external == "fireden" else 16

		urls = []

		try:
			amount = max(0, min(1000, int(self.parameters.get("amount", 0))))
		except ValueError:
			amount = 100

		extensions = {}

		with open(self.source_file) as source:
			csv = DictReader(source)
			for post in csv:
				if len(urls) >= amount:
					break

				extension = post["filename"].split(".")[1].lower()
				if extension not in ("jpg", "jpeg", "png", "gif"):
					continue

				local_file = post["url_4cat"].split("/")[-1]
				local_path = Path(config.PATH_IMAGES, local_file)
				if local_path.exists():
					url = local_path
				else:
					url = post["url_" + external]

				urls.append(url)
				extensions[url] = extension

		# prepare staging area
		results_path = self.dataset.get_temporary_path()
		results_path.mkdir()
		counter = 0

		# loop through images and copy them onto the wall
		for path in urls:
			counter += 1
			self.dataset.update_status("Downloading image %i of %i" % (counter, len(urls)))

			# acquire and resize image
			try:
				picture = self.get_image(path, rate_limit=rate_limit)
			except (requests.RequestException, IndexError, FileNotFoundError):
				continue

			# hash needs to be hexified if it's a 4chan hash
			if not isinstance(path, Path) and path[-2:] == "==":
				md5 = hashlib.md5()
				b64hash = base64.b64decode(path.split("/")[-1].split(".")[0].replace("_", "/"))
				try:
					md5.update(b64hash)
				except binascii.Error:
					self.log.warning("Invalid base64 hash %s, skipping" % b64hash)
					continue

				hash = md5.hexdigest()
			else:
				# if we're using an already-saved image the hash is good as it is
				hash = path.stem

			# determine file name
			imagepath = str(results_path.joinpath(hash)) + "." + extensions[path]
			picture.save(imagepath)

		# finish up
		self.dataset.update_status("Compressing images")

		with zipfile.ZipFile(self.dataset.get_results_path(), "w") as zip:
			for imagefile in results_path.glob("*"):
				zip.write(imagefile, imagefile.name)

		# delete temporary files and folder
		shutil.rmtree(results_path)

		self.dataset.update_status("Finished")
		self.dataset.finish(len(urls))

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

		if isinstance(path, Path):
			# local file
			return Image.open(path)

		# get link to image from external HTML search results
		# detect rate limiting and wait until we're good to go again
		page = requests.get(path, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/12.1.1 Safari/605.1.15"})
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

		# if not available, the thumbnail may be
		if image.status_code != 200:
			thumbnail_url = ".".join(image_url.split(".")[:-1]) + "s." + image_url.split(".")[-1]
			image = requests.get(thumbnail_url, stream=True)

		if image.status_code != 200:
			raise FileNotFoundError

		# cache the image for later, if needed
		if config.PATH_IMAGES:
			md5 = hashlib.md5()

			based_hash = path.split("/")[-1].split(".")[0].replace("_", "/")
			extension = image_url.split(".")[-1].lower()
			md5.update(base64.b64decode(based_hash))

			local_path = Path(config.PATH_IMAGES, md5.hexdigest() + "." + extension)
			delete_after = False
		else:
			query_result = self.dataset.get_results_path()
			local_path = Path(query_result.parent, query_result.name + "-temp")
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
			local_path.unlink()

		return picture