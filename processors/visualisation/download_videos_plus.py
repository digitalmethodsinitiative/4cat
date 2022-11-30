"""
Download videos

First attempt to download via request, but if that fails use yt-dlp
"""
from pathlib import Path
import requests
import yt_dlp
import json
import re
from yt_dlp import DownloadError

import common.config_manager as config
from common.lib.helpers import UserInput, validate_url, sets_to_lists
from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException, ProcessorException

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


def url_to_filename(url, extension, directory):
	# Create filename
	filename = re.sub(r"[^0-9a-z]+", "_", url.lower())[:100]  # [:100] is to avoid folder length shenanigans
	save_location = directory.joinpath( Path(filename + "." + extension))
	filename_index = 0
	while save_location.exists():
		save_location = directory.joinpath(
			filename + "-" + str(filename_index) + save_location.suffix.lower())
		filename_index += 1

	return save_location


class VideoDownloaderPlus(BasicProcessor):
	"""
	Downloads videos and saves as zip archive

	Attempts to download videos directly, but if that fails, uses YT_DLP. (https://github.com/yt-dlp/yt-dlp/#readme)
	which attempts to keep up with a plethora of sites: https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md
	"""
	type = "video-downloader-plus"  # job type ID
	category = "Visual"  # category
	title = "Download videos plus"  # title displayed in UI
	description = "Download videos from URLs and store in a zip file. May take a while to complete as videos are retrieved externally."  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI

	references = [
		"[YT-DLP python package](https://github.com/yt-dlp/yt-dlp/#readme)",
		"[Supported sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md)",
	]

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
			"help": "Column to get image links from",
			"default": "video_url",
			"inline": True,
			"tooltip": "If column contains a single URL, use that URL; else, try to find image URLs in the column's content"
		},
		"max_video_size": {
			"type": UserInput.OPTION_TEXT,
			"help": "Max videos size (in MB/Megabytes)",
			"default": 100,
			"min": 1,
			"tooltip": "Max of 100 MB set by 4CAT administrators",
		},
		"split-comma": {
			"type": UserInput.OPTION_TOGGLE,
			"help": "Split column values by comma?",
			"default": True,
			"tooltip": "If enabled, columns can contain multiple URLs separated by commas, which will be considered "
					   "separately"
		}
	}

	def __init__(self, logger, job, queue=None, manager=None, modules=None):
		super().__init__(logger, job, queue, manager, modules)
		self.max_videos_per_url = 5
		self.videos_downloaded_from_url = 0
		self.url_files = None
		self.last_dl_status = None
		self.last_post_process_status = None

	@classmethod
	def get_options(cls, parent_dataset=None, user=None):
		"""
		Updating columns with actual columns and setting max_number_videos per
		the max number of images allowed.
		"""
		options = cls.options

		# Update the amount max and help from config
		max_number_videos = int(config.get('video_downloader.MAX_NUMBER_VIDEOS', 100))
		options['amount']['max'] = max_number_videos
		options['amount']['help'] = "No. of videos (max %s)" % max_number_videos
		# And update the max size and help from config
		max_video_size = int(config.get('video_downloader.MAX_VIDEO_SIZE', 100))
		if max_video_size == 0:
			# Allow video of any size
			options["max_video_size"]["tooltip"] = "Set to 0 if all sizes are to be downloaded."
			options['max_video_size']['min'] = 0
		else:
			# Limit video size
			options["max_video_size"]["max"] = max_video_size
			options['max_video_size']['default'] = options['amount']['default'] if options['amount']['default'] <= max_video_size else max_video_size
			options["max_video_size"]["tooltip"] = f"Max of {max_video_size} MB set by 4CAT administrators"
			options['max_video_size']['min'] = 1

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

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column with image hashes, one with the first file name used
		for the image, and one with the amount of times the image was used
		"""
		# Check processor able to run
		if self.source_dataset.num_rows == 0:
			self.dataset.update_status("No data from which to extract video URLs.", is_final=True)
			self.dataset.finish(0)
			return

		# Collect URLs
		try:
			urls = self.collect_video_urls()
		except ProcessorException as e:
			self.dataset.update_status(str(e), is_final=True)
			self.dataset.finish(0)
			return
		self.dataset.log('Collected %i urls.' % len(urls))

		# Prepare staging area for videos and video tracking
		results_path = self.dataset.get_staging_area()
		self.dataset.log('Staging directory location: %s' % results_path)

		# Set up yt_dlp options
		ydl_opts = {
			# "logger": self.log,  # This will dump any errors to our logger if desired
			"socket_timeout": 30,
			"postprocessor_hooks": [self.yt_dlp_post_monitor],# This function ensures no more than self.max_videos_per_url downloaded and can be used to monitor progress
			"progress_hooks": [self.yt_dlp_monitor],
		}

		# Collect parameters
		amount = self.parameters.get("amount", 100)
		if amount == 0:
			amount = config.get('video_downloader.MAX_NUMBER_VIDEOS', 100)

		# YT-DLP by default attempts to download the best quality videos
		allow_unknown_sizes = config.get('video_downloader.DOWNLOAD_UNKNOWN_SIZE', False)
		max_video_size = self.parameters.get("max_video_size", 100)
		max_size = str(max_video_size) + "M"
		if not max_video_size == 0:
			if allow_unknown_sizes:
				ydl_opts["format"] = f"[filesize<?{max_size}]/[filesize_approx<?{max_size}]"
			else:
				ydl_opts["format"] = f"[filesize<{max_size}]/[filesize_approx<{max_size}]"

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

			# REJECT CERTAIN URLS
			if any([sub_url in url for sub_url in ['youtube.com/c/', 'youtube.com/channel/']]):
				# HAHAHA.... NO. Do not download channels. Might be a better way to ensure we catch this...
				message = 'Skipping... will not download all vids from YouTube CHANNEL: %s' % url
				urls[url]['success'] = False
				urls[url]['error'] = message
				failed_downloads += 1
				self.dataset.update_status(message)
				continue

			# First we'll try to see if we can directly download the URL
			try:
				filename = self.download_video_with_requests(url, results_path, max_video_size)
				urls[url]["files"] = [{
									"filename": filename,
									"metadata": {},
									"success": True
									}]
				success = True
				num_vids_downloaded = 1
			except requests.exceptions.SSLError:
				message = "Unable to obtain URL %s due to SSL error." % url
				self.dataset.log(message)
				urls[url]["success"] = False
				urls[url]["error"] = message
				failed_downloads += 1
				continue
			except (FilesizeException, FailedDownload, NotAVideo) as e:
				# FilesizeException raised when file size is too large or unknown filesize (and that is disabled in 4CAT settings)
				# FailedDownload raised when response other than 200 received
				# NotAVideo raised due to specific Content-Type known to not be a video (or a webpage/html that could lead to a video via YT-DLP)
				self.dataset.log(str(e))
				urls[url]["success"] = False
				urls[url]["error"] = str(e)
				failed_downloads += 1
				continue
			except VideoStreamUnavailable as e:
				# Take it away yt-dlp
				# Update filename
				ydl_opts["outtmpl"] = str(results_path) + '/' + re.sub(r"[^0-9a-z]+", "_", url.lower())[:100] + '_%(autonumber)s.%(ext)s'
				with yt_dlp.YoutubeDL(ydl_opts) as ydl:
					try:
						# Count and use self.yt_dlp_monitor() to ensure sure we don't download videos forever...
						self.videos_downloaded_from_url = 0
						self.url_files = []
						self.last_dl_status = {}
						self.last_post_process_status = {}
						self.dataset.update_status("Downloading via yt-dlp: %s" % url)
						info = ydl.extract_info(url)
						num_vids_downloaded = self.videos_downloaded_from_url
					except MaxVideosDownloaded:
						# Raised when already downloaded max number of videos per URL as defined in self.max_videos_per_url
						pass
					except DownloadError as e:
						if "Requested format is not available" in str(e):
							message = f"No format available for video (filesize less than {max_size}" + " and unknown sizes not allowed)" if not allow_unknown_sizes else ")"
						else:
							message = 'DownloadError: %s' % str(e)
						urls[url]['success'] = False
						urls[url]['error'] = message
						failed_downloads += 1
						self.dataset.update_status(message)
						continue

				# Add file data collected by YT-DLP
				urls[url]['files'] = self.url_files

				# Check that download and processing finished
				success = all([self.last_dl_status.get('status') == 'finished', self.last_post_process_status.get('status') == 'finished'])

			urls[url]["success"] = success

			# Update status
			downloaded_videos += num_vids_downloaded
			self.dataset.update_status(
				"Downloaded %i/%i videos: %s" % (downloaded_videos, total_possible_videos, url))
			self.dataset.update_progress(downloaded_videos / total_possible_videos)

		# Save some metadata to be able to connect the videos to their source
		metadata = {
			url: {
				"from_dataset": self.source_dataset.key,
				"post_ids": list(data.get('ids')),
				**sets_to_lists(data)  # TODO: This some shenanigans until I can figure out what to do with the info returned
			} for url, data in urls.items()
		}
		with results_path.joinpath(".metadata.json").open("w", encoding="utf-8") as outfile:
			json.dump(metadata, outfile)

		# Finish up
		self.dataset.update_status('Downloaded %i videos.' % downloaded_videos + ' %i URLs failed.' % failed_downloads if failed_downloads > 0 else '' + ' Check .metadata.json for individual results.', is_final=True)
		self.write_archive_and_finish(results_path)

	def yt_dlp_monitor(self, d):
		"""
		Can be used to gather information from yt-dlp while downloading
		"""
		self.last_dl_status = d

		# Make sure we can stop downloads
		if self.interrupted:
			raise ProcessorInterruptedException("Interrupted while downloading videos.")

	def yt_dlp_post_monitor(self, d):
		"""
		Can be used to gather information from yt-dlp while post processing the downloads
		"""
		self.last_post_process_status = d
		if d['status'] == 'finished':  # "downloading", "error", or "finished"
			self.videos_downloaded_from_url += 1
			self.url_files.append({
								"filename": Path(d.get('info_dict').get('_filename')).name,
								"metadata": d.get('info_dict'),
								"success": True
								})
		if self.videos_downloaded_from_url >= self.max_videos_per_url:
			raise MaxVideosDownloaded('Max videos for URL reached.')

		# Make sure we can stop downloads
		if self.interrupted:
			raise ProcessorInterruptedException("Interrupted while downloading videos.")

	def download_video_with_requests(self, url, results_path, max_video_size):
		# Open stream
		with requests.get(url, stream=True) as response:
			if response.status_code != 200:
				raise FailedDownload("Unable to obtain URL %s with reason: %s; and headers: %s" % (url, str(response.reason), str(response.headers)))

			# Verify video
			# YT-DLP will download images; so we raise them differently
			# TODO: test/research other possible ways to verify video links; watch for additional YT-DLP oddities
			if "image" in response.headers["Content-Type"].lower():
				raise NotAVideo("Not a Video: %s; Content-Type: %s" % (url, response.headers["Content-Type"]))
			elif "video" not in response.headers["Content-Type"].lower():
				raise VideoStreamUnavailable("Possibly video, but unable to download via requests: %s; Content-Type: %s" % (url, response.headers["Content-Type"]))

			extension = response.headers["Content-Type"].split("/")[-1]
			# DEBUG Content-Type
			if extension not in ["mp4", "mp3"]:
				self.dataset.log(
					"DEBUG: Odd extension type %s; Notify 4CAT maintainers if video. Content-Type for url %s: %s" % (
					extension, url, response.headers["Content-Type"]))

			# Ensure unique filename
			save_location = url_to_filename(url, extension, results_path)

			# Check video size (after ensuring it is actually a video above)
			if not max_video_size == 0:
				if response.headers.get("Content-Length", False):
					if int(response.headers.get("Content-Length")) > (max_video_size * 1000000):  # Use Bytes!
						raise FilesizeException(f"Video size {response.headers.get('Content-Length')} larger than maximum allowed per 4CAT")
				# Size unknown
				elif not config.get("video_downloader.DOWNLOAD_UNKNOWN_SIZE", False):
					FilesizeException("Video size unknown; not allowed to download per 4CAT settings")

			# Download video
			self.dataset.update_status("Downloading via requests: %s" % url)
			with open(results_path.joinpath(save_location), "wb") as f:
				for chunk in response.iter_content(chunk_size=1024 * 1024):
					if chunk:
						f.write(chunk)

			# Return filename to add to metadata
			return save_location.name

	def collect_video_urls(self):
		urls = {}
		split_comma = self.parameters.get("split-comma", False)
		columns = self.parameters.get("columns")
		if type(columns) == str:
			columns = [columns]

		if not columns:
			raise ProcessorException("No columns selected; cannot collect video urls.")

		self.dataset.update_status("Reading source file")
		for index, post in enumerate(self.source_dataset.iterate_items(self)):
			item_urls = set()
			if index + 1 % 250 == 0:
				self.dataset.update_status(
					"Extracting video links from item %i/%i" % (index + 1, self.source_dataset.num_rows))

			# loop through all columns and process values for item
			for column in columns:
				value = post.get(column)
				if not value:
					continue

				# remove all whitespace from beginning and end (needed for single URL check)
				values = [str(value).strip()]
				if split_comma:
					values = values[0].split(',')

				for value in values:
					if re.match(r"https?://(\S+)$", value):
						# single URL
						if validate_url(value):
							item_urls.add(value)
					else:
						# search for video URLs in string
						video_links = self.identify_video_urls_in_string(value)
						if video_links:
							item_urls |= set(video_links)

			for item_url in item_urls:
				if item_url not in urls:
					urls[item_url] = {'ids': {post.get('id')}}
				else:
					urls[item_url]['ids'].add(post.get('id'))

		if not urls:
			raise ProcessorException("No video urls identified in provided data.")
		else:
			return urls

	def identify_video_urls_in_string(self, text):
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
				self.dataset.log('Possible URL identified, but did not validate: %s' % url)
		return validated_links


class MaxVideosDownloaded(ProcessorException):
	"""
	Raise if processor throws an exception
	"""
	pass


class FailedDownload(ProcessorException):
	"""
	Raise if processor throws an exception
	"""
	pass


class VideoStreamUnavailable(ProcessorException):
	"""
	Raise if processor throws an exception
	"""
	pass


class NotAVideo(ProcessorException):
	"""
	Raise if processor throws an exception
	"""
	pass


class FilesizeException(ProcessorException):
	"""
	Raise if processor throws an exception
	"""
	pass
