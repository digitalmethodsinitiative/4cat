"""
Get YouTube metadata from video links posted
"""
import time
import urllib.request

from apiclient.discovery import build

from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.helpers import get_yt_compatible_ids, UserInput

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"


class YouTubeThumbnails(BasicProcessor):
	"""
	
	Downloads YouTube thumbnails.

	"""

	type = "youtube-thumbnails"  # job type ID
	category = "Cross-platform"  # category
	title = "Download YouTube thumbnails"  # title displayed in UI
	description = "Downloads the thumbnails of YouTube videos and stores it in a zip archive."  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI
	media_type = "image"  # media type of the result

	followups = ["youtube-imagewall"]

	max_retries = 3
	sleep_time = 10

	@classmethod
	def is_compatible_with(cls, module=None, config=None):
		"""
		Allow processor on YouTube metadata sets

		:param module: Dataset or processor to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
		"""
		return module.type == "youtube-metadata"

	@classmethod
	def get_options(cls, parent_dataset=None, config=None) -> dict:

		api_key = config.get("api.youtube.key")
		if not api_key:
			return {"key":
				{
					"type": UserInput.OPTION_TEXT,
					"default": "",
					"help": "YouTube API key",
					"tooltip": "Can be created on https://developers.google.com/youtube/v3",
					"sensitive": True
				}
			}

		return {}

	def process(self):
		"""
		Downloads thumbnails from YouTube videos. 

		"""
		self.dataset.update_status("Extracting YouTube links")
		video_ids = set()
		for youtube_video in self.source_dataset.iterate_items(self):
			if "video_id" in youtube_video:
				video_ids.add(youtube_video["video_id"])
			else:
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
		
		api_key = self.parameters.get("key")
		if not api_key:
			api_key = self.config.get("api.youtube.key")
		if not api_key:
			self.dataset.finish_with_error("You need to provide a valid API key")
			return
		self.api_key = api_key
				
		# Use YouTubeDL and the YouTube API to request video data
		youtube = build("youtube", "v3",
						developerKey=api_key)

		ids_list = get_yt_compatible_ids(video_ids)
		retries = 0

		for i, ids_string in enumerate(ids_list):
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while downloading thumbnails from YouTube")

			while retries < self.max_retries:
				try:
					response = youtube.videos().list(
						part="snippet",
						id=ids_string,
						maxResults=50
					).execute()
					break
				except Exception as error:
					self.dataset.update_status(
						"Encountered exception " + str(error) + ".\nSleeping for " + str(self.sleep_time))
					retries += 1
					time.sleep(self.sleep_time)  # Wait a bit before trying again

			# Do nothing with the results if the requests failed
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
			self.dataset.update_progress(i / len(ids_list))

		# create zip of archive and delete temporary files and folder
		self.dataset.update_status("Compressing results into archive")
		self.write_archive_and_finish(results_path)
