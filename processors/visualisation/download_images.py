"""
Download images linked in dataset
"""
import requests
import binascii
import hashlib
import base64
import json
import time
import re
import csv
import shutil
import uuid

from pathlib import Path
from PIL import Image, UnidentifiedImageError

from lxml import etree
from lxml.cssselect import CSSSelector as css
from io import StringIO, BytesIO

import config
from common.lib.helpers import UserInput
from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException

__author__ = "Stijn Peeters, Sal Hagen"
__credits__ = ["Stijn Peeters, Sal Hagen"]
__maintainer__ = "Stijn Peeters, Sal Hagen"
__email__ = "4cat@oilab.eu"

class ImageDownloader(BasicProcessor):
	"""
	Image downloader

	Downloads top images and saves as zip archive
	"""
	type = "image-downloader"  # job type ID
	category = "Visual"  # category
	title = "Download images"  # title displayed in UI
	description = "Download top images and compress as a zip file. May take a while to complete as images are sourced externally. Note that not always all images can be retrieved. For imgur galleries, only the first image is saved. For imgur gifv files, only the first frame is saved. Use the \"Add download status\" option to see what downloads succeeded"  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI

	options = {
		"amount": {
			"type": UserInput.OPTION_TEXT,
			"help": "No. of images (max 1000)",
			"default": 100,
			"min": 0,
			"max": 5000
		},
		"overwrite": {
			"type": UserInput.OPTION_TOGGLE,
			"default": True,
			"help": "Add download status to Top images",
			"tooltip": "This will add two columns, \"download_status\" and \"img_name\", to above csv file so you can check whether downloading succeeded and what the image's filename is."
		}
	}

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor on top image rankings

		:param module: Dataset or processor to determine compatibility with
		"""
		return module.type == "top-images"

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column with image hashes, one with the first file name used
		for the image, and one with the amount of times the image was used
		"""
		images = {}

		urls = []

		# is there anything for us to download?
		if self.source_dataset.num_rows == 0:
			self.dataset.update_status("No images to download.", is_final=True)
			self.dataset.finish(0)
			return

		# Get the source file data path
		top_parent = self.dataset.get_genealogy()[0]
		datasource = top_parent.parameters["datasource"]

		try:
			amount = max(0, min(1000, int(self.parameters.get("amount", 0))))
		except ValueError:
			amount = 100

		extensions = {}

		# 4chan is the odd one out (images are traced to and scraped from
		# external archives rather than 4chan itself) so here we collect the
		# relevant archive URLs for any 4chan images we encounter
		if datasource == "4chan":
			self.dataset.update_status("Reading source file")
			external = "fireden" if top_parent.parameters.get("board") == "v" else "4plebs"
			rate_limit = 1 if external == "fireden" else 16

			for post in self.iterate_items(self.source_file):
				# stop processing if worker has been asked to stop
				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while extracting image URLs")

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

		# With other sources, simply take the URLs as they are provided by the
		# parent dataset
		else:
			for row in self.iterate_items(self.source_file):

				img_url = row["item"]
				extension = img_url.split(".")[-1].lower()
				extensions[img_url] = extension
				urls.append(img_url)

		# prepare staging area
		results_path = self.dataset.get_staging_area()
		counter = 0
		downloaded_images = 0

		# Used to overwrite top-images csv file with download status
		success = []

		# loop through images and download them - until we have as many images
		# as required. Note that images that cannot be downloaded or parsed do
		# not count towards that limit
		for path in urls:
			if downloaded_images >= amount:
				break

			# stop processing if worker has been asked to stop
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while downloading images.")

			counter += 1
			success.append({"download_status": "failed", "img_name": ""})
			self.dataset.update_status("Downloading image %i of %i" % (counter, len(urls)))

			# acquire and resize image
			try:
				if datasource == "4chan":
					picture = self.get_4chan_image(path, rate_limit=rate_limit)
				else:
					picture, image_name = self.get_image(path)

			except (requests.RequestException, IndexError, FileNotFoundError) as e:
				continue

			# Again, some different processing for 4chan
			if datasource == "4chan":

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

				# if we're using an already-saved image the image filename is good as it is
				else:
					hash = path.stem

				# determine file name and where to save
				image_name = hash + "." + extensions[path]
				imagepath = str(results_path.joinpath(image_name))

			# For other data sources, we take the imagename it already had.
			else:
				if results_path.joinpath(image_name).exists():
					# File exists; rename
					image_name = uuid.uuid4().hex + "_" + image_name

				imagepath = str(results_path.joinpath(image_name))

			# save file
			try:
				picture.save(imagepath, format="png")
				downloaded_images += 1
			except (OSError, ValueError):
				self.log.warning("Could not save image %s to disk - invalid format" % path)
				continue

			# If this all succeeded, we update the download status and the filename.
			success[counter - 1]["download_status"] = "succeeded"
			success[counter - 1]["img_name"] = image_name

		# Also add the data to the original csv file, if indicated.
		if self.parameters.get("overwrite"):
			self.update_parent(success)

		# finish up
		self.dataset.update_status("Compressing images")
		self.write_archive_and_finish(results_path)

	def get_image(self, path):
		"""
		Get image from a generic URL.

		Images from URLs ending in image extensions are attempted to download.
		For imgur and gfycat image URLs, which often do not end in an extension name,
		we try to extrapolate the image file type and the corresponding URL directly to the image.

		:param path:  Path to image, either a local path or a URL
		:return Image:  Image object, or nothing if loading it failed
		:returm str:  	Filename of the image
		"""

		image_url = None

		# gfycat and imgur images have to handled a bit differently, so check for these first.
		img_domain_regex = re.compile(r"(?:https:\/\/gfycat\.com\/|imgur\.com\/)[^\s\(\)\]\[]*", re.IGNORECASE)

		# Determine whether the URL ends with a valid image extension.
		exts = ["png", "jpg", "jpeg", "gif", "gifv"]
		url_ext = path.split("/")[-1].lower().split(".")[-1]
		if url_ext not in exts:
			url_ext = None

		# Treat imgur and gfycat links a bit differently.
		if (img_domain_regex.search(path)):

			# Imgur images can appear in different formats, so we have to process this a bit.
			if "imgur.com/" in path:

				# gifv files on imgur are actually small mp4 files.
				# Since downloading videos complicates this and follow-up processors,
				# just safe the first frame that imgur also hosts as a .gif file.
				if url_ext == "gifv":
					image_url = path[:-1]

				# Other urls ending in file extensions we just attempt to download straight away.
				elif any([ext == url_ext for ext in exts]):
					image_url = path

				# If there's not file extention at the end of the url,
				# and the link is a so-called "gallery",
				# use the image's .json endpoint imgur so graciously provides :)
				# We only save the first image of the gallery.
				elif "gallery" in path:
					path += ".json"
					page = requests.get(path)
					imgur_images = []
					try:
						imgur_data = page.json()
					except json.JSONDecodeError:
						self.dataset.log("Error loading gallery for image %s, skipping")
						raise FileNotFoundError

					try:
						image = imgur_data["data"]["image"]["album_images"]["images"][0]
					except KeyError as e:
						raise FileNotFoundError

					image_url = "https://imgur.com/" + image["hash"] + image["ext"]

				# Handle image preview page
				# Two formats identified: https://imgur.com/a/randomid, https://imgur.com/randomid
				else:
					page = requests.get(path)
					# This seems unlikely to last; could use BeautifulSoup for more dynamic capturing of url
					image_url = page.content.decode('utf-8').split('<meta property="og:image"')[1].split('content="')[1].split(
						'?fb">')[0]



		elif "gfycat.com/" in path:

				if not url_ext:
					# For gfycat.com links, just add .gif and download
					image_url = path + ".gif"
				else:
					image_url = path

		# If the URL ends with an image file extension and it's not from imgur or gfycat, just attempt to download it.
		else:
			image_url = path

		# Get the image!
		if image_url:
			image = requests.get(image_url, stream=True, timeout=20, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/12.1.1 Safari/605.1.15"})
		else:
			raise FileNotFoundError

		# Use this for local saving.
		image_name = image_url.split("/")[-1]
		# Some URLs have parameters after extention. Remove if this is the case.
		if "?" in image_name:
			image_name = image_name.split("?")[0]

		# Check if we succeeded; content type should be an image
		if image.status_code != 200 or image.headers.get("content-type", "")[:5] != "image":
			raise FileNotFoundError

		# Try opening the image in multiple ways
		try:
			picture = Image.open(BytesIO(image.content))
		except UnidentifiedImageError:
			try:
				picture = Image.open(image.raw)
			except UnidentifiedImageError:
				raise FileNotFoundError

		return picture, image_name

	def get_4chan_image(self, path, rate_limit=0):
		"""
		Get image from a 4chan archive and save.

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
			local_path = Path(query_result.source_dataset, query_result.name + "-temp")
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

	def update_parent(self, success):
		"""
		Update the original dataset with a nouns column

		"""

		self.dataset.update_status("Adding image urls to the source file")

		# Get the source file data path
		parent_path = self.source_dataset.get_results_path()

		# Get a temporary path where we can store the data
		tmp_path = self.dataset.get_staging_area()
		tmp_file_path = tmp_path.joinpath(parent_path.name)

		count = 0

		# Get field names
		fieldnames = self.get_item_keys(parent_path)
		for fieldname in ["download_status", "img_name"]:
			if fieldname not in fieldnames:
				fieldnames += [fieldname]

		# Iterate through the original dataset and add values to a new img_link column
		self.dataset.update_status("Writing download status to Top images csv.")
		with tmp_file_path.open("w", encoding="utf-8", newline="") as output:

			writer = csv.DictWriter(output, fieldnames=fieldnames)
			writer.writeheader()

			for post in self.iterate_items(parent_path):

				if count < len(success):
					post["download_status"] = success[count]["download_status"]
					post["img_name"] = success[count]["img_name"]

				writer.writerow(post)
				count += 1

		# Replace the source file path with the new file
		shutil.copy(str(tmp_file_path), str(parent_path))

		# delete temporary files and folder
		shutil.rmtree(tmp_path)

		self.dataset.update_status("Parent dataset updated.")
