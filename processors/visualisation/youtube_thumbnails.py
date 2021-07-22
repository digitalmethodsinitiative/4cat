"""
Get YouTube metadata from video links posted
"""
import time
import urllib.request

import config

from apiclient.discovery import build

from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.helpers import get_yt_compatible_ids

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

class YouTubeThumbnails(BasicProcessor):
	"""
	
	Downloads YouTube thumbnails.

	"""

	type = "youtube-thumbnails"  # job type ID
	category = "Cross-platform" # category
	title = "Download YouTube thumbnails"  # title displayed in UI
	description = "Download YouTube video thumbnails."  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI
	
	max_retries = 3
	sleep_time = 10

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor on YouTube metadata sets

		:param module: Dataset or processor to determine compatibility with
		"""
		return module.type == "youtube-metadata"

	def process(self):
		"""
		Downloads thumbnails from YouTube videos. 

		"""
		self.dataset.update_status("Extracting YouTube links")
		video_ids = set()
		for youtube_video in self.iterate_items(self.source_file):
			video_ids.add(youtube_video["id"])

		self.dataset.update_status("Downloading thumbnails")
		self.download_thumbnails(list(video_ids))

	def download_thumbnails(self, video_ids):
		"""
		Download video thumbnails
		:param video_ids list, list of YouTube video IDs
		"""

		# prepare staging area
		results_path = self.dataset.get_staging_area()

		# Use YouTubeDL and the YouTube API to request video data
		youtube = build(config.YOUTUBE_API_SERVICE_NAME, config.YOUTUBE_API_VERSION,
											developerKey=config.YOUTUBE_DEVELOPER_KEY)
		
		ids_list = get_yt_compatible_ids(video_ids)
		retries = 0

		for i, ids_string in enumerate(ids_list):
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while downloading thumbnails from YouTube")

			while retries < self.max_retries:
				try:
					response = youtube.videos().list(
						part = "snippet",
						id = ids_string,
						maxResults = 50
						).execute()
					break
				except Exception as error:
					self.dataset.update_status("Encountered exception " + str(error) + ".\nSleeping for " + str(self.sleep_time))
					retries += 1
					api_error = error
					time.sleep(self.sleep_time)  # Wait a bit before trying again

			# Do nothing with the results if the requests failed -
			# be in the final results file
			if retries >= self.max_retries:
				self.dataset.update_status("Error during YouTube API request")
			else:
				# Get and return results for each video
				for metadata in response["items"]:

					# Get the URL of the thumbnail
					thumb_url = metadata["snippet"]["thumbnails"]["high"]["url"]
					# Format the path to save the thumbnail to
					save_path = results_path.joinpath(metadata["id"] + "." + str(thumb_url.split('.')[-1]))
					# Download the image
					urllib.request.urlretrieve(thumb_url, save_path)

			self.dataset.update_status("Downloaded thumbnails for " + str(i * 50) + "/" + str(len(video_ids)))

		# create zip of archive and delete temporary files and folder
		self.dataset.update_status("Compressing results into archive")

		# Save the count of images for `finish` function
		image_count = 0

		self.write_archive_and_finish(results_path)