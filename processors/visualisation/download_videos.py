"""
Download videos linked in dataset
"""
import requests
import json
import re
from pathlib import Path

import common.config_manager as config
from common.lib.helpers import UserInput, validate_url
from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class VideoDownloader(BasicProcessor):
	"""
	Video downloader

	Downloads videos and saves as zip archive
	"""
	type = "video-downloader-OLD"  # job type ID
	category = "Visual"  # category
	title = "Download videos (OLD)"  # title displayed in UI
	description = "Download videos from URLs and store in a zip file. May take a while to complete as videos are retrieved externally. Works best on sources with \"video_url\" columns such as Twitter and TikTok or \"media_url\" like Instagram."  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI

	config = {
		"video_downloader.MAX_NUMBER_VIDEOS": {
			"type": UserInput.OPTION_TEXT,
			"coerce_type": int,
			"default": 1000,
			"help": "Max number of videos to download",
			"tooltip": "Only allow downloading up to this many videos per batch. Increasing this can lead to "
					   "long-running processors and large datasets."
		},
		"video_downloader.MAX_VIDEO_SIZE": {
			"type": UserInput.OPTION_TEXT,
			"coerce_type": int,
			"default": 100,
			"help": "Max allowed MB size of a single video for download",
			"tooltip": "Size in MB/Megabytes; default 100. 0 will allow any size."
		},
		"video_downloader.DOWNLOAD_UNKNOWN_SIZE": {
			"type": UserInput.OPTION_TOGGLE,
			"default": True,
			"help": "Allow download of unknown size",
			"tooltip": "Video size is not always available before downloading. If True, users may choose to download unknown sizes."
		},
	}

	options = {
		"amount": {
			"type": UserInput.OPTION_TEXT,
			"help": "No. of videos (max 1000)",
			"default": 100,
			"min": 0,
			"max": 1000
		},
		"columns": {
			"type": UserInput.OPTION_TEXT,
			"help": "Column to get video links from",
			"default": "video_url",
			"inline": True,
			"tooltip": "If column contains a single URL, use that URL; else, try to extract video URLs."
		},
		"max_video_size": {
			"type": UserInput.OPTION_TEXT,
			"help": "Max videos size (in MB/Megabytes)",
			"coerce_type": int,
			"default": 100,
			"min": 1,
			"tooltip": "Max of 100 MB set by 4CAT administrators",
		},
		"split-comma": {
			"type": UserInput.OPTION_TOGGLE,
			"help": "Split column values by comma",
			"default": False,
			"tooltip": "If enabled, columns can contain multiple URLs separated by commas, which will be considered "
					   "separately"
		},
	}

	@classmethod
	def get_options(cls, parent_dataset=None, user=None):
		"""
		Updating columns with actual columns and setting max_number_videos per
		the max number of images allowed.
		"""
		options = cls.options

		# Update the amount max and help from config
		max_number_videos = int(config.get("video_downloader.MAX_NUMBER_VIDEOS", 100))
		options["amount"]["max"] = max_number_videos
		options["amount"]["help"] = "No. of videos (max %s)" % max_number_videos
		# And update the max size and help from config
		max_video_size = int(config.get("video_downloader.MAX_VIDEO_SIZE", 100))
		if max_video_size == 0:
			# Allow video of any size
			options["max_video_size"]["tooltip"] = "Set to 0 if all sizes are to be downloaded."
			options["max_video_size"]["min"] = 0
		else:
			# Limit video size
			options["max_video_size"]["max"] = max_video_size
			options["max_video_size"]["default"] = options["amount"]["default"] if options["amount"]["default"] <= max_video_size else max_video_size
			options["max_video_size"]["tooltip"] = f"Max of {max_video_size} MB set by 4CAT administrators"
			options["max_video_size"]["min"] = 1

		# Get the columns for the select columns option
		if parent_dataset and parent_dataset.get_columns():
			columns = parent_dataset.get_columns()
			options["columns"]["type"] = UserInput.OPTION_MULTI
			options["columns"]["options"] = {v: v for v in columns}

			# Figure out default column
			if "video_url" in columns:
				options["columns"]["default"] = "video_url"
			elif "media_urls" in columns:
				options["columns"]["default"] = "media_urls"
			elif "video" in "".join(columns):
				# Grab first video column
				options["columns"]["default"] = sorted(columns, key=lambda k: "video" in k).pop()
			elif "url" in columns or "urls" in columns:
				# Grab first url column
				options["columns"]["default"] = sorted(columns, key=lambda k: "url" in k).pop()
			else:
				# Give up
				options["columns"]["default"] = "body"

		return options

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow on tiktok-search only for dev
		"""
		return module.type.endswith("search")
		# return module.type == "tiktok-search" or module.type == "twitterv2-search"

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column with image hashes, one with the first file name used
		for the image, and one with the amount of times the image was used
		"""
		# Collect parameters
		amount = self.parameters.get("amount", 100)
		if amount == 0:
			amount = config.get("video_downloader.MAX_NUMBER_VIDEOS", 1000)
		max_video_size = self.parameters.get("max_video_size",
											 100) * 1000000  # Multiply MB * 1000000 as Content-Length is in Bytes
		if max_video_size == 0:
			all_sizes = True
		else:
			all_sizes = False
		allow_unknown_sizes = config.get("video_downloader.DOWNLOAD_UNKNOWN_SIZE", False)
		split_comma = self.parameters.get("split-comma", False)
		columns = self.parameters.get("columns")
		if type(columns) == str:
			columns = [columns]

		# Check processor able to run
		if self.source_dataset.num_rows == 0:
			self.dataset.update_status("No videos to download.", is_final=True)
			self.dataset.finish(0)
			return

		if not columns:
			self.dataset.update_status("No columns selected; no videos extracted.", is_final=True)
			self.dataset.finish(0)
			return

		# Prepare staging area for videos and video tracking
		results_path = self.dataset.get_staging_area()
		self.dataset.log("Staging directory location: %s" % results_path)
		urls = {}

		# first, get URLs to download images from
		self.dataset.update_status("Reading source file")
		for index, post in enumerate(self.source_dataset.iterate_items(self)):
			item_urls = set()
			if index % 50 == 0:
				self.dataset.update_status("Extracting video links from item %i/%i" % (index, self.source_dataset.num_rows))

			# loop through all columns and process values for item
			for column in columns:
				value = post.get(column)
				if not value:
					continue

				# remove all whitespace from beginning and end (needed for single URL check)
				values = [str(value).strip()]
				if split_comma:
					values = values[0].split(",")

				for value in values:
					if re.match(r"https?://(\S+)$", value):
						# single URL
						if validate_url(value):
							item_urls.add(value)
					else:
						# search for video URLs in string
						video_links = self.identify_video_links(value)
						if video_links:
							self.dataset.log(f"Multiple urls: {','.join(video_links)}")
							item_urls |= set(video_links)

			for item_url in item_urls:
				if item_url not in urls:
					urls[item_url] = {"ids": {post.get("id")}}
				else:
					urls[item_url]["ids"].add(post.get("id"))

		# Check if urls were identified
		if not urls:
			self.dataset.update_status("No video urls identified.", is_final=True)
			self.dataset.finish(0)
			return
		else:
			self.dataset.log("Collected %i video urls." % len(urls))

		# Loop through video URLs and download
		downloaded_videos = 0
		failed_downloads = 0
		total_possible_videos = min(len(urls), amount)
		for url in urls:
			# Stop processing if worker has been asked to stop or max downloads reached
			if downloaded_videos >= amount:
				break
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while downloading videos.")

			# Open stream
			try:
				with requests.get(url, stream=True) as response:
					if response.status_code != 200:
						message = "Unable to obtain URL %s with reason: %s; and headers: %s" % (url, str(response.reason), str(response.headers))
						self.dataset.log(message)
						urls[url]["success"] = False
						urls[url]["error"] = message
						failed_downloads += 1
						continue

					# Verify video
					#TODO: test/research other possible ways to verify video links
					if "video" not in response.headers["Content-Type"].lower():
						# Log in metadata file
						message = "Url %s does not appear to be a video; Content-Type: %s" % (url, response.headers["Content-Type"])
						urls[url]["success"] = False
						urls[url]["error"] = message
						failed_downloads += 1
						continue

					# Create filename
					filename = re.sub(r"[^0-9a-z]+", "_", url.lower())[:100]  # [:100] is to avoid folder length shenanigans
					extension = response.headers["Content-Type"].split("/")[-1]

					# DEBUG Content-Type
					if extension not in ["mp4", "mp3"]:
						self.dataset.log("DEBUG: Odd extension type %s; Notify 4CAT maintainers if video. Content-Type for url %s: %s" % (extension, url, response.headers["Content-Type"]))

					# Ensure unique filename
					video_filepath = Path(filename + "." + extension)
					save_location = results_path.joinpath(video_filepath)
					filename_index = 0
					while save_location.exists():
						save_location = results_path.joinpath(filename + "-" + str(filename_index) + save_location.suffix.lower())
						filename_index += 1

					# Check video size
					if not all_sizes:
						if response.headers.get("Content-Length", False):
							if int(response.headers.get("Content-Length")) > max_video_size:
								urls[url]["success"] = False
								urls[url]["error"] = f"Video size {response.headers.get('Content-Length')} larger than maximum allowed per 4CAT"
								continue
							else:
								# Size appropriate
								pass
						# Size unknown
						elif not allow_unknown_sizes:
							urls[url]["success"] = False
							urls[url]["error"] = f"Video size unknown; not allowed to download per 4CAT settings"
							continue

					# Download video
					with open(results_path.joinpath(save_location), "wb") as f:
						for chunk in response.iter_content(chunk_size=1024 * 1024):
							if chunk:
								f.write(chunk)

					# Add metadata
					urls[url]["filename"] = save_location.name
					urls[url]["success"] = True
			
			except requests.exceptions.SSLError:
				message = "Unable to obtain URL %s due to SSL error." % url
				urls[url]["success"] = False
				urls[url]["error"] = message
				failed_downloads += 1
				self.dataset.log(message)
				continue

			# Update status
			downloaded_videos += 1
			self.dataset.update_status(
				"Downloaded %i/%i videos: %s" % (downloaded_videos, total_possible_videos, url))
			self.dataset.update_progress(downloaded_videos / total_possible_videos)

		# Save some metadata to be able to connect the videos to their source
		metadata = {
			url: {
				"filename": data.get("filename"),
				"success": data.get("success"),
				"from_dataset": self.source_dataset.key,
				# sets() are not JSON serializable...
				"post_ids": list(data.get("ids")),
				"errors": data.get("error", ""),
			} for url, data in urls.items()
		}
		with results_path.joinpath(".metadata.json").open("w", encoding="utf-8") as outfile:
			json.dump(metadata, outfile)

		# Finish up
		self.dataset.update_status("Downloaded %i videos. %i URLs did not link directly to videos or failed. Check .metadata.json for individual video results." % (downloaded_videos, failed_downloads), is_final=True)
		self.write_archive_and_finish(results_path)

	def identify_video_links(self, text):
		"""
		Search string of text for URLs that may contain video links.

		:param str text:  string that may contain URLs
		:return list:  	  list containing validated URLs to videos
		"""
		# Currently just extracting all links
		# Could also try: https://stackoverflow.com/questions/161738/what-is-the-best-regular-expression-to-check-if-a-string-is-a-valid-url
		vid_link_regex = re.compile(r"(https?):\/\/[a - z0 - 9\.:].* ?(?=\s)",  re.IGNORECASE)
		possible_links = vid_link_regex.findall(text)

		# Validate URLs
		# validated_links = [url for url in possible_links if validate_url(url)]
		validated_links = []
		for url in possible_links:
			if validate_url(url):
				validated_links.append(url)
			else:
				# DEBUG: this is to check our regex works as intended
				self.dataset.log("Possible URL identified, but did not validate: %s" % url)
		return validated_links
