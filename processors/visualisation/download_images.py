"""
Download images linked in dataset
"""
import requests
import hashlib
import base64
import json
import time
import re
import csv
import shutil

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
	description = "Download images and compress as a zip file. May take a while to complete as images are sourced " \
				  "externally. Note that not always all images can be retrieved. For imgur galleries, only the first " \
				  "image is saved. For animations, only the first frame is saved if available. A JSON metadata file " \
				  "is included in the output archive."  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI

	if hasattr(config, 'MAX_NUMBER_IMAGES'):
		max_number_images = int(config.MAX_NUMBER_IMAGES)
	else:
		max_number_images = 1000

	options = {
		"amount": {
			"type": UserInput.OPTION_TEXT,
			"help": "No. of images (max %s)" % max_number_images,
			"default": 100,
			"min": 0,
			"max": max_number_images
		},
		"columns": {
			"type": UserInput.OPTION_TEXT,
			"help": "Column to get image links from",
			"default": "image_url",
			"tooltip": "If column contains a single URL, use that URL; else, try to find image URLs in the column's content"
		},
	}

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor on top image rankings

		:param module: Dataset or processor to determine compatibility with
		"""
		return module.type == "top-images" or module.type.endswith("search")

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column with image hashes, one with the first file name used
		for the image, and one with the amount of times the image was used
		"""

		# Get the source file data path
		top_parent = self.dataset.get_genealogy()[0]
		datasource = top_parent.parameters.get("datasource")
		amount = self.parameters.get("amount", 100)
		if amount == 0:
			amount = self.max_number_images
		columns = self.parameters.get("columns")

		# is there anything for us to download?
		if self.source_dataset.num_rows == 0:
			self.dataset.update_status("No images to download.", is_final=True)
			self.dataset.finish(0)
			return

		if not columns:
			self.dataset.update_status("No columns selected; no images extracted.", is_final=True)
			self.dataset.finish(0)
			return

		# prepare
		results_path = self.dataset.get_staging_area()
		self.dataset.log('Staging directory location: %s' % results_path)
		urls = {}
		url_file_map = {}
		file_url_map = {}

		# for image URL extraction, we use the following heuristic:
		# Makes sure that it gets "http://site.com/img.jpg", but also
		# more complicated ones like
		# https://preview.redd.it/3thfhsrsykb61.gif?format=mp4&s=afc1e4568789d2a0095bd1c91c5010860ff76834
		img_link_regex = re.compile(
			r"(?:www\.|https?:\/\/)[^\s\(\)\]\[,']*\.(?:png|jpg|jpeg|gif|gifv)[^\s\(\)\]\[,']*", re.IGNORECASE)

		# Imgur and gfycat links that do not end in an extension are also accepted.
		# These can later be downloaded by adding an extension.
		img_domain_regex = re.compile(r"(?:https:\/\/gfycat\.com\/|https:\/\/imgur\.com\/)[^\s\(\)\]\[,']*",
									  re.IGNORECASE)

		external = None
		if datasource == "4chan" and ("image_md5" in columns or "image_file" in columns):
			external = "boards.fireden.net" if top_parent.parameters.get("board") == "v" else "archive.4plebs.org"

		# first, get URLs to download images from
		self.dataset.update_status("Reading source file")
		item_index = 0
		for item in self.iterate_items(self.source_file):
			item_urls = set()
			if 'ids' in item.keys():
				item_ids = [id for id in item.get('ids').split(',')]
			else:
				item_ids = [item.get("id", item_index)]
			# let's iterate after; otherwise we could do something crazy like start an index at 1
			item_index += 1

			if item_index % 50 == 0:
				self.dataset.update_status("Extracting image links from post %i/%i" % (item_index, self.source_dataset.num_rows))

			# loop through all columns and process values for item
			for column in columns:
				value = item.get(column)
				if not value:
					continue

				# remove all whitespace from beginning and end (needed for single URL check)
				value = ' '.join(str(value).split())
				if re.match(r"https?://(\S+)$", value):
					# single URL
					item_urls.add(value)
				else:
					# # Debug
					# if re.match(r"https?://[^\s]+", value):
					# 	self.dataset.log("Debug: OLD single detect url %s" % value)

					# search for image URLs in string
					item_urls |= set(img_link_regex.findall(value))
					item_urls |= set(img_domain_regex.findall(value))

			if external:
				# 4chan has a module that saves images locally, so if the columns in
				# the dataset that reference those local images are selected, check
				# if the referenced images aren't available locally. If not, try a
				# public 4chan mirror to see if they may be downloaded there.

				md5 = hashlib.md5()
				md5.update(base64.b64decode(item["image_md5"]))
				extension = item["image_file"].split(".")[-1]

				local_path = Path(config.PATH_IMAGES, md5.hexdigest() + "." + extension)
				if local_path.exists():
					local_path = str(local_path.absolute())
					item_urls.add(local_path)

				else:
					remote_path = "https://%s/_/search/image/%s" % (external, item["image_md5"].replace("/", "_"))
					item_urls.add(remote_path)

			for item_url in item_urls:
				if item_url not in urls:
					urls[item_url] = []

				[urls[item_url].append(id) for id in item_ids]

		# next, loop through images and download them - until we have as many images
		# as required. Note that images that cannot be downloaded or parsed do
		# not count towards that limit
		downloaded_images = 0
		processed_urls = 0
		failures = []
		for url in urls:
			if downloaded_images >= amount:
				break

			# stop processing if worker has been asked to stop
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while downloading images.")

			processed_urls += 1
			self.dataset.update_status("Downloaded %i images; checking url for next %i/%i: %s" %
									   (downloaded_images, processed_urls, len(urls), url))

			try:
				# acquire image
				if not url.lower().startswith("http"):
					image, image_filename = Image.open(url)
				else:
					image, image_filename = self.get_image(url)

				try:
					picture = Image.open(image)
				except UnidentifiedImageError:
					picture = Image.open(image.raw)

			except (FileNotFoundError, UnidentifiedImageError):
				failures.append(url)
				continue

			# save the image...? avoid overwriting images by appending
			# -[number] to filenames if they already exist
			index = 0
			image_filename = Path(image_filename).name  # no folder shenanigans
			image_stem = Path(image_filename).stem
			image_suffix = Path(image_filename).suffix
			if not image_suffix or image_suffix not in (".png", ".gif", ".jpeg", ".jpg"):
				# default to PNG
				image_suffix = ".png"

			save_location = results_path.joinpath(image_filename).with_suffix(image_suffix)
			while save_location.exists():
				save_location = results_path.joinpath(image_stem + "-" + str(index) + image_suffix)
				index += 1

			url_file_map[url] = save_location.name
			file_url_map[save_location.name] = url
			try:
				picture.save(str(save_location))
				# Counting is important
				downloaded_images += 1
			except OSError as e:
				# some images may need to be converted to RGB to be saved
				self.dataset.log('Debug: OSError when saving image %s: %s' % (save_location, e))
				picture = picture.convert('RGB')
				picture.save(str(save_location))
			except ValueError as e:
				self.dataset.log(f"Error '{e}' saving image for {url}, skipping")
				failures.append(url)
				continue

		# save some metadata to be able to connect the images to their source
		# posts again later
		metadata = {
			url: {
				"filename": url_file_map.get(url),
				"success": url not in failures,
				"from_dataset": self.source_dataset.key,
				"post_ids": urls[url]
			} for url in urls
		}
		with results_path.joinpath(".metadata.json").open("w", encoding="utf-8") as outfile:
			json.dump(metadata, outfile)

		# finish up
		self.dataset.update_status("Compressing images")
		self.write_archive_and_finish(results_path)

	def get_image(self, url):
		"""
		Get image from a generic URL.

		Images from URLs ending in image extensions are attempted to download.
		For imgur and gfycat image URLs, which often do not end in an extension name,
		we try to extrapolate the image file type and the corresponding URL directly to the image.

		:param path:  Path to image, either a local path or a URL
		:return Image:  Image object, or nothing if loading it failed
		:returm str:  	Filename of the image
		"""
		domain = url.split("/")[2].lower()
		url_ext = url.split(".")[-1].lower()
		exts = ["png", "jpg", "jpeg", "gif", "gifv"]

		# Treat imgur and gfycat links a bit differently.
		image_url = url
		if domain in ("www.imgur.com", "imgur.com"):
			# gifv files on imgur are actually small mp4 files. Since
			# downloading videos complicates this and follow-up processors,
			# just save the first frame that imgur also hosts as a .gif file.
			if url_ext == "gifv":
				image_url = url[:-1]

			# Check for image extensions and directly download
			# Some imgur.com links are directly to images (not just i.imgur.com)
			elif any([ext == url_ext for ext in exts]):
				pass

			# If there's not file extension at the end of the url, and the link
			# is a so-called "gallery", use the image's .json endpoint imgur so
			# graciously provides :)
			# We only save the first image of the gallery.
			elif "gallery" in url:
				url += ".json"
				page = self.request_get_w_error_handling(url)

				try:
					imgur_data = page.json()
				except json.JSONDecodeError:
					self.dataset.log("Error loading gallery for image %s, skipping")
					raise FileNotFoundError()

				try:
					image = imgur_data["data"]["image"]["album_images"]["images"][0]
				except KeyError as e:
					raise FileNotFoundError()

				image_url = "https://imgur.com/" + image["hash"] + image["ext"]

			# Handle image preview page
			# Two formats identified: https://imgur.com/a/randomid, https://imgur.com/randomid
			else:
				page = self.request_get_w_error_handling(url)

				try:
					# This seems unlikely to last; could use BeautifulSoup for more dynamic capturing of url
					image_url = \
						page.content.decode('utf-8').split('<meta property="og:image"')[1].split('content="')[1].split('?fb">')[0]
				except IndexError:
					# Noted that image not found pages (no status code of course) will not have this property
					self.dataset.log("Error: IndexError may be 404 for image %s, skipping" % image_url)
					raise FileNotFoundError()
				except UnicodeDecodeError:
					try:
						self.dataset.log("Debug: UnicodeDecodeError detected for image %s" % image_url)
						# Use requests chardet to detect encoding
						page.encoding = page.apparent_encoding
						image_url = \
							page.text.split('<meta property="og:image"')[1].split('content="')[1].split('?fb">')[0]
					except IndexError:
						# Noted that image not found pages (no status code of course) will not have this property
						self.dataset.log("Error: IndexError may be 404 for image %s, skipping" % image_url)
						raise FileNotFoundError()

		elif domain.endswith("gfycat.com") and url_ext not in ("png", "jpg", "jpeg", "gif", "gifv"):
			# For gfycat.com links, just add .gif and download
			image_url = url + ".gif"

		# Get the image!
		if domain.endswith("4plebs.org") or domain.endswith("fireden.net") and image_url:
			image = self.get_4chan_image(url)
		elif image_url:
			image = self.request_get_w_error_handling(image_url, stream=True, timeout=20, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/12.1.1 Safari/605.1.15"})
		else:
			raise FileNotFoundError()

		# Use this for local saving.
		image_name = image_url.split("/")[-1].split("?")[0]

		# Check if we succeeded; content type should be an image
		if image.status_code != 200 or image.headers.get("content-type", "")[:5] != "image":
			raise FileNotFoundError()

		return BytesIO(image.content), image_name

	def get_4chan_image(self, url):
		"""
		Get image from a 4chan archive and save.

		If the path is local, simply read the local path and return an Image
		representing it. If not, attempt to download the image from elsewhere,
		and cache the downloaded result if possible, else discard the file
		afterwards.

		:param url:  Image URL, pointing to a 4chan mirror
		:return Image:  Image object, or nothing if loading it failed
		"""
		rate_regex = re.compile(r"Search limit exceeded. Please wait ([0-9]+) seconds before attempting again.")
		rate_limit = 1 if "fireden.net" in url else 16  # empirically verified

		if isinstance(url, Path):
			# local file
			return Image.open(url)

		# get link to image from external HTML search results
		# detect rate limiting and wait until we're good to go again
		page = self.request_get_w_error_handling(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/12.1.1 Safari/605.1.15"})
		rate_limited = rate_regex.search(page.content.decode("utf-8"))

		while rate_limited:
			self.log.debug("Rate-limited by external source. Waiting %s seconds." % rate_limited[1])
			time.sleep(int(rate_limited[1]))
			page = self.request_get_w_error_handling(url)
			rate_limited = rate_regex.search(page.content.decode("utf-8"))

		# get link to image file from HTML returned
		parser = etree.HTMLParser()
		tree = etree.parse(StringIO(page.content.decode("utf-8")), parser)
		try:
			image_url = css("a.thread_image_link")(tree)[0].get("href")
		except IndexError as e:
			self.dataset.log("Error: IndexError while trying to download 4chan image %s: %s" % (url, e))
			raise FileNotFoundError()

		# download image itself
		image = self.request_get_w_error_handling(image_url, stream=True)

		# if not available, the thumbnail may be
		if image.status_code != 200:
			thumbnail_url = ".".join(image_url.split(".")[:-1]) + "s." + image_url.split(".")[-1]
			image = self.request_get_w_error_handling(thumbnail_url, stream=True)

		if image.status_code != 200:
			raise FileNotFoundError()

		md5 = hashlib.md5()
		based_hash = url.split("/")[-1].split(".")[0].replace("_", "/")
		extension = image_url.split(".")[-1].lower()
		md5.update(base64.b64decode(based_hash))
		file_name = md5.hexdigest() + "." + extension

		# cache the image for later, if configured so
		if config.PATH_IMAGES:
			local_path = Path(config.PATH_IMAGES, md5.hexdigest() + "." + extension)
			with open(local_path, 'wb') as file:
				for chunk in image.iter_content(1024):
					file.write(chunk)

		# avoid getting rate-limited by image source
		time.sleep(rate_limit)
		return BytesIO(image.content), file_name

	def request_get_w_error_handling(self, url, retries=0, **kwargs):
		"""
		Try requests.get() and raise FileNotFoundError while logging actual
		error in dataset.log().

		Retries ConnectionError three times
		"""
		try:
			response = requests.get(url, **kwargs)
		except requests.exceptions.Timeout as e:
			self.dataset.log("Error: Timeout while trying to download image %s: %s" % (url, e))
			raise FileNotFoundError()
		except requests.exceptions.SSLError as e:
			self.dataset.log("Error: SSLError while trying to download image %s: %s" % (url, e))
			raise FileNotFoundError()
		except requests.exceptions.ConnectionError as e:
			if retries < 3:
				self.request_get_w_error_handling(url, retries + 1, **kwargs)
			else:
				self.dataset.log("Error: ConnectionError while trying to download image %s: %s" % (url, e))
				raise FileNotFoundError()
		return response


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



	@classmethod
	def get_options(cls, parent_dataset=None, user=None):
		"""
		Get processor options

		This method by default returns the class's "options" attribute, or an
		empty dictionary. It can be redefined by processors that need more
		fine-grained options, e.g. in cases where the availability of options
		is partially determined by the parent dataset's parameters.

		:param DataSet parent_dataset:  An object representing the dataset that
		the processor would be run on
		:param User user:  Flask user the options will be displayed for, in
		case they are requested for display in the 4CAT web interface. This can
		be used to show some options only to privileges users.
		"""
		options = cls.options

		if parent_dataset and parent_dataset.get_columns():
			columns = parent_dataset.get_columns()
			options["columns"]["type"] = UserInput.OPTION_MULTI_SELECT
			options["columns"]["options"] = {v: v for v in columns}
			options["columns"]["default"] = "body" if "body" in columns else sorted(columns, key=lambda k: "image" in k).pop()

		return options
