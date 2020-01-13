"""
Get YouTube metadata from video links posted
"""
import datetime
import time
import re
import zipfile
import shutil
import urllib.request
import youtube_dl
import pandas as pd
import math
import os

import config

from apiclient.discovery import build
from collections import Counter
from csv import DictReader
from PIL import Image, ImageFile, ImageOps, ImageDraw, ImageFont

from backend.abstract.processor import BasicProcessor
from backend.lib.helpers import UserInput, convert_to_int, get_yt_compatible_ids

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

	input = "csv:id"
	output = "zip"
	
	max_retries = 3
	sleep_time = 10
	accepts = ["youtube-metadata"]

	def process(self):
		"""
		Downloads thumbnails from YouTube videos. 

		"""

		self.dataset.update_status("Reading source file")

		with open(self.source_file, encoding="utf-8") as source:

			# Read source file
			csv = DictReader(source)

			# Add all the video IDs to a list
			self.dataset.update_status("Extracting YouTube links")
			video_ids = [youtube_vid["id"] for youtube_vid in csv]
			
			# Get the thumbnails
			self.dataset.update_status("Downloading thumbnails")
			self.download_thumbnails(video_ids)

	def download_thumbnails(self, video_ids):
		"""
		Download video thumbnails
		:param video_ids list, list of YouTube video IDs
		"""

		# prepare staging area
		results_path = self.dataset.get_temporary_path()
		results_path.mkdir()

		# Use YouTubeDL and the YouTube API to request video data
		youtube = build(config.YOUTUBE_API_SERVICE_NAME, config.YOUTUBE_API_VERSION,
											developerKey=config.YOUTUBE_DEVELOPER_KEY)
		
		ids_list = get_yt_compatible_ids(video_ids)
		retries = 0
		for i, ids_string in enumerate(ids_list):
			while retries < self.max_retries:
				try:
					response = youtube.videos().list(
						part = "snippet",
						id = ids_string,
						maxResults = 50
						).execute()
					break
				except Exception as error:
					self.dataset.update_status("Encountered exception " + str(error) + ".\nSleeping for " + str(sleep_time))
					retries += 1
					api_error = error
					time.sleep(sleep_time) # Wait a bit before trying again
					pass

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

		with zipfile.ZipFile(self.dataset.get_results_path(), "w") as zip:
			for image in os.listdir(results_path):
				zip.write(str(results_path) + "/" + image, image)
				results_path.joinpath(image).unlink()
				image_count += 1

		# delete temporary files and folder
		shutil.rmtree(results_path)

		# done!
		self.dataset.update_status("Finished")
		self.dataset.finish(image_count)
