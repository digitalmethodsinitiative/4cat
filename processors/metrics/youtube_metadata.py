"""
Get YouTube metadata from video links posted
"""
import time
import re
import csv
import urllib.request

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from backend.lib.processor import BasicProcessor
from common.lib.helpers import UserInput

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)


class YouTubeMetadata(BasicProcessor):
	"""
	
	Extracts data from YouTube URLs
	Every row is one link, with the metadata and `amount`
	of times shared.

	"""

	type = "youtube-metadata"  # job type ID
	category = "Metrics"  # category
	title = "Fetch metadata from YouTube URLs"  # title displayed in UI
	description = "Collect metadata from YouTube videos, channels, and playlists with the YouTube API"  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	followups = ["youtube-thumbnails"]

	max_retries = 3
	sleep_time = 20

	api_key = None
	api_limit_reached = False
	invalid_api_key = False

	client = None

	references = [
		"[YouTube v3 API documentation](https://developers.google.com/youtube/v3)",
		"[4chan’s YouTube: A Fringe Perspective on YouTube’s Great Purge of 2019 - OILab.eu](https://oilab.eu/4chans-youtube-a-fringe-perspective-on-youtubes-great-purge-of-2019/)"
	]

	config = {
		"api.youtube.key": {
			"type": UserInput.OPTION_TEXT,
			"default": "",
			"help": "YouTube API key",
			"tooltip": "Can be created on https://developers.google.com/youtube/v3"
		}
	}

	@classmethod
	def get_options(cls, parent_dataset=None, config=None) -> dict:

		options = {
			"columns": {
				"type": UserInput.OPTION_TEXT,
				"help": "Columns with YouTube URLs",
				"default": "url",
				"inline": True,
				"tooltip": "These should be valid YouTube URLs. Separate by comma. "
						   "Use the Extract URLs processor if you need to extract URLs from text columns."
			},
			"save_annotations": {
				"type": UserInput.OPTION_ANNOTATIONS,
				"options": {
					"url": "YouTube URL",
					"type": "Type (video, channel, playlist)",
					"video_id": "Video ID",
					"video_title": "Video title",
					"video_description": "Video description",
					"upload_time": "Video creation date",
					"video_view_count": "Video views",
					"video_likes_count": "Video like count",
					"video_comment_count": "Video comment count",
					"video_duration": "Video duration",
					"video_tags": "Video tags",
					"video_category_id": "Video category ID",
					"video_topic_ids": "Video topic IDs",
					"channel_id": "Channel ID",
					"channel_title": "Channel title",
					"channel_handle": "Channel handle",
					"channel_description": "Channel description",
					"channel_start": "Channel creation date",
					"channel_subscribercount": "Channel subscriber count",
					"channel_videocount": "Channel video count",
					"channel_commentcount": "Channel comment count",
					"channel_viewcount": "Channel view count",
					"channel_topic_ids": "Channel topic IDs",
					"channel_topic_categories": "Channel topic categories",
					"channel_branding_keywords": "Channel branding keywords",
					"channel_country": "Channel country",
					"channel_default_language": "Channel language",
					"playlist_id": "Playlist ID",
					"playlist_title": "Playlist title",
					"playlist_description": "Playlist description",
					"playlist_thumbnail": "Playlist thumbnail URL",
					"playlist_video_count": "Playlist video count",
					"playlist_status": "Playlist status"
				},
				"default": "",
				"tooltip": "Every type of YouTube data will get its own annotation"
			}
		}

		# Get the columns for the select columns option
		if parent_dataset and parent_dataset.get_columns():
			columns = parent_dataset.get_columns()
			options["columns"]["type"] = UserInput.OPTION_MULTI
			options["columns"]["options"] = {v: v for v in columns}
			options["columns"]["default"] = "extracted_urls" if "extracted_urls" in columns else sorted(columns,
																										key=lambda
																											k: "text" in k).pop()
		api_key = config.get("api.youtube.key")
		if not api_key:
			options["key"] = {
				"type": UserInput.OPTION_TEXT,
				"default": "",
				"help": "YouTube API key",
				"tooltip": "Can be created on https://developers.google.com/youtube/v3",
				"sensitive": True
			}

		return options

	@classmethod
	def is_compatible_with(cls, module=None, config=None):
		"""
		Allow processor on datasets probably containing youtube links

		:param module: Module to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
		"""
		# Compatible with every top-level dataset.
		return ((module.is_top_dataset() and module.get_extension() in ("csv", "ndjson"))
				or module.type == "extract-urls-filter")

	def process(self):
		"""
		Writes a csv file with metadata of extracted YouTube objects.
		Will include the ID of the original row for reference.
		"""

		api_key = self.parameters.get("key")
		if not api_key:
			api_key = self.config.get("api.youtube.key")
		if not api_key:
			self.dataset.finish_with_error("You need to provide a valid API key")
			return
		self.api_key = api_key

		# Get column parameters
		columns = self.parameters.get("columns", [])
		if isinstance(columns, str):
			columns = [columns]

		# Are we writing annotations?
		annotations_to_save = self.parameters.get("save_annotations")

		# First thing to do is to extract IDs from YouTube links.
		# These can be video IDs (including shorts), channel IDs, channel names, or playlists
		self.dataset.update_status(f"Extracting YouTube links and IDs from {','.join(columns)}")
		youtube_urls = set()
		youtube_ids = []
		items_to_retrieve = []
		failed_ids = 0

		# Loop through initial datasets to extract IDs
		for row in self.source_dataset.iterate_items(self):
			# Go through all columns
			for column in columns:

				data = row[column]

				# Skip empty rows and non-string rows
				if not data or not isinstance(data, str):
					continue

				# Split by URL by default
				urls = data.split(",")

				for url in urls:

					# Get rid of unwanted (often trailing) characters
					url = re.sub(r"[(),|]", "", url.strip())

					# Skip if not a YouTube URL
					if "youtu.be" not in url and "youtube" not in url:
						continue

					# Skip if the URL is seen already (ID already extracted)
					if url in youtube_urls:
						continue
					youtube_urls.add(url)

					# Get the ID
					try:
						yt_id = self.get_yt_id(url, original_id=row.get("id", ""))
					except ValueError:
						self.dataset.update_status("Could not extract YouTube ID from " + url)
						continue

					if not yt_id:
						self.dataset.update_status(f"Could not parse ID from URL {url}")
						failed_ids += 1
						continue

					# Already seen
					if yt_id[0] in youtube_ids:
						continue
					youtube_ids.append(yt_id[0])

					items_to_retrieve.append(yt_id)

		# Finish if there's no YouTube IDs
		if not youtube_ids:
			self.dataset.finish_as_empty("No YouTube IDs found")
			return

		# Start client
		self.start_youtube_client()

		# Get YouTube API data for all videos, playlists, and channels.
		youtube_items = self.get_youtube_metadata(items_to_retrieve)

		if not youtube_items:
			self.dataset.finish_with_error("No items retrieved from the YouTube API")
			return

		# Possibly add values as annotations to top-level dataset
		if annotations_to_save:
			annotations = []
			for youtube_item in youtube_items:
				if "retrieved_from_id" in youtube_item:
					for retrieved_from_id in youtube_item["retrieved_from_id"].split(","):
						for annotation_to_save in annotations_to_save:
							if youtube_item.get(annotation_to_save):
								annotations.append({
									"item_id": retrieved_from_id,
									"label": annotation_to_save,
									"value": youtube_item[annotation_to_save]
								})

			self.save_annotations(annotations)

		warning = None
		if failed_ids:
			warning = f"Could not parse IDs from {failed_ids} URLs."
		self.dataset.update_status("Writing results to csv.")
		self.write_csv_items_and_finish(youtube_items, warning=warning)

	def get_youtube_metadata(self, yt_ids: list[tuple]) -> list:
		"""
		Use the YouTube API to fetch metadata from videos or channels.

		:param yt_ids:	A list of tuples, where the first value is a YouTube ID (video, channel, playlist)
						or a username handle.
						The second value should be one of:
							`video`, `channel`, `channel_handle`, `playlist`
						so we know what API  endpoint to call.
						A third value can indicate what original item IDs references this YouTube ID, so we
						can re-add this value for traceability and annotation writing.

		:returns list with dicts with YouTube's response metadata.

		"""

		results = []
		keys = set()
		original_items = {yi[0]: [] for yi in yt_ids}  # Use this to re-add the original IDs

		ids_per_type = {}
		for youtube_id in yt_ids:
			if youtube_id[1] not in ids_per_type:
				ids_per_type[youtube_id[1]] = [youtube_id[0]]
			else:
				ids_per_type[youtube_id[1]].append(youtube_id[0])

			# Keep track of the item IDs where this YouTube link was mentioned
			if youtube_id[2]:
				original_items[youtube_id[0]].append(youtube_id[2])

		# Loop in batches of 50
		for yt_type, ids in ids_per_type.items():
			for i, ids_string in enumerate(self.batch_strings(ids)):
				retries = 0
				response = None

				while retries < self.max_retries:
					try:
						if yt_type == "video":
							response = self.client.videos().list(
								part='snippet,contentDetails,statistics',
								id=ids_string,
								maxResults=50
							).execute()
						elif yt_type == "channel":
							response = self.client.channels().list(
								part="snippet,topicDetails,statistics,brandingSettings",
								id=ids_string,
								maxResults=50
							).execute()
						elif yt_type == "channel_handle":
							response = {"items": []}
							# Handles have to be done per handle...
							for handle in ids_string.split(","):
								single_response = self.client.channels().list(
									part="snippet,topicDetails,statistics,brandingSettings",
									forHandle=handle,
									maxResults=50
								).execute()
								if single_response.get("items"):
									response["items"] += single_response["items"]

						elif yt_type == "playlist":
							response = self.client.playlists().list(
								part="snippet,contentDetails,id,player,status",
								id=ids_string,
								maxResults=50
							).execute()

						self.api_limit_reached = False
						break

					# Check rate limits
					except HttpError as e:

						status_code = e.resp.status

						if status_code == 403:  # "Forbidden", what Google returns with rate limits
							retries += 1
							self.api_limit_reached = True
							self.dataset.update_status(f"API quota limit likely exceeded (http {status_code}, sleeping "
													   f"for {self.sleep_time} seconds")
							time.sleep(self.sleep_time)  # Wait a bit before trying again
							pass

						else:
							retries += 1
							self.dataset.update_status(f"API error encountered (http {status_code}), "
													   f"sleeping for {self.sleep_time}")
							time.sleep(self.sleep_time)  # Wait a bit before trying again
							pass

				# Do nothing with the results if the requests failed after retries
				if retries >= self.max_retries:
					self.dataset.update_status(
						f"Failed to get metadata from {yt_type}s after {retries} attempts (ids {ids_string}).")
					if self.api_limit_reached:
						self.dataset.update_status("Daily YouTube API requests exceeded.")

					return results

				# Sometimes there's no results and "response" won't have an item key.
				elif response is not None:
					result = {}

					if "items" not in response:
						for id_string in ids_string.split(","):
							result["youtube_id"] = id_string
							result["type"] = yt_type
							result["retrieved"] = False

					# Get and return results for each video
					else:
						for metadata in response["items"]:

							result = {"retrieved": True}

							if yt_type == "video":
								video_id = metadata["id"]
								result["retrieved_from_id"] = ",".join(original_items[video_id])
								result["type"] = "video"
								result["url"] = "https://youtube.com/watch?v=" + metadata["id"]
								result["video_id"] = video_id
								result["upload_time"] = metadata["snippet"].get("publishedAt")
								result["channel_id"] = metadata["snippet"].get("channelId")
								result["channel_title"] = metadata["snippet"].get("channelTitle")
								result["video_title"] = metadata["snippet"].get("title")
								result["video_description"] = metadata["snippet"].get("description")
								result["video_duration"] = metadata.get("contentDetails").get("duration")
								result["video_view_count"] = metadata["statistics"].get("viewCount")
								result["video_comment_count"] = metadata["statistics"].get("commentCount")
								result["video_likes_count"] = metadata["statistics"].get("likeCount")
								result["video_dislikes_count"] = metadata["statistics"].get("dislikeCount")
								result["video_topic_ids"] = metadata.get("topicDetails")
								result["video_category_id"] = metadata["snippet"].get("categoryId")
								result["video_tags"] = metadata["snippet"].get("tags")

							elif yt_type.startswith("channel"):
								channel_id = metadata["snippet"].get("channelId", "")
								channel_handle = metadata["snippet"].get("customUrl", "")
								result["retrieved_from_id"] = ",".join(
									original_items.get(channel_id, []) + original_items.get(channel_handle, []))
								result["type"] = "channel"
								result["url"] = "https://youtube.com/channel/" + channel_id
								result["channel_id"] = channel_id
								result["channel_handle"] = channel_handle
								result["channel_title"] = metadata["snippet"].get("title", "")
								result["channel_description"] = metadata["snippet"].get("description", "")
								result["channel_start"] = metadata["snippet"].get("publishedAt", "")
								result["channel_default_language"] = metadata["snippet"].get("defaultLanguage", "")
								result["channel_country"] = metadata["snippet"].get("country", "")
								result["channel_viewcount"] = metadata["statistics"].get("viewCount", "")
								result["channel_commentcount"] = metadata["statistics"].get("commentCount", "")
								result["channel_subscribercount"] = metadata["statistics"].get("subscriberCount", "")
								result["channel_videocount"] = metadata["statistics"].get("videoCount", "")
								# This one sometimes fails for some reason
								if "topicDetails" in metadata:
									result["channel_topic_ids"] = metadata["topicDetails"].get("topicIds")
									result["channel_topic_categories"] = metadata["topicDetails"].get("topicCategories")
								result["channel_branding_keywords"] = metadata.get("brandingSettings").get("channel").get(
									"keywords")

							elif yt_type == "playlist":
								result["retrieved_from_id"] = ",".join(original_items[metadata["id"]])
								result["type"] = "playlist"
								result["url"] = "https://youtube.com/playlist?list=" + metadata["id"]
								result["channel_id"] = metadata["snippet"].get("channelId", "")
								result["channel_title"] = metadata["snippet"].get("channelTitle", "")
								result["playlist_id"] = metadata["id"]
								result["playlist_title"] = metadata["snippet"].get("title", "")
								result["playlist_description"] = metadata["snippet"].get("channelTitle", "")
								result["playlist_thumbnail"] = metadata["snippet"].get("thumbnails", {}).get("high",
																											 {}).get("url",
																													 "")
								result["playlist_video_count"] = metadata["contentDetails"].get("itemCount", ""),
								result["playlist_status"] = metadata["status"].get("privacyStatus", "")

							results.append(result)
							keys |= set(result.keys())

				# Update status per response item
				self.dataset.update_status(f"Got metadata for {i * 50}/{len(ids)} {yt_type} objects")

		# Make sure all items have the same keys for csv writing
		for i in range(len(results)):
			for key in keys:
				if key not in results[i].keys():
					results[i][key] = ""

		return results

	@staticmethod
	def get_yt_id(url: str, original_id="") -> tuple[str, str, str]:
		"""
		Extracts IDs from YouTube URLs.
		Supports videos, channel IDs, channel names, and playlist IDs.
		Returns a tuple with the extracted ID, the type of object (`video`, `channel`, `playlist`), and the row id.
		"""

		yt_type = ""
		yt_id = ""

		# Prepend https:// if it doesn't start with it for urllib
		if not url.startswith(("http://", "https://")):
			url = "https://" + url
		# And remove www.
		url = url.replace("www.", "")

		# Extract the YouTube link
		query = urllib.parse.urlparse(url)

		# Channel: @
		if "@" in query.path:
			yt_id = re.findall(r"(?<=@)[a-zA-Z0-9_]+", query.path)
			if yt_id:
				yt_id = "@" + yt_id[0]
				yt_type = "channel_handle"
		# Channel: "channel" in URL
		elif "channel" in query.path:
			yt_id = re.findall(r"(?<=channel/)[a-zA-Z0-9_]+", query.path)
			if yt_id:
				yt_id = yt_id[0]
				yt_type = "channel"
		# youtu.be URLs always reference videos
		elif query.hostname == "youtu.be":
			yt_id = query.path[1:]
		# Playlist
		elif query.path == "/playlist":
			parsed_url = urllib.parse.parse_qs(query.query)
			if "list" in parsed_url:
				yt_id = parsed_url["list"][0]
				yt_type = "playlist"
		# Regular "watch?v=" link
		elif query.path == "/watch":
			parsed_url = urllib.parse.parse_qs(query.query)
			if "v" in parsed_url:
				yt_id = parsed_url["v"][0]
		# Embedded video
		elif query.path[:7] == "/embed/":
			yt_id = query.path.split("/")[2]
		# Shorts
		elif query.path[:8] == "/shorts/":
			yt_id = query.path.split("/")[2]
		# /v/ format
		elif query.path[:3] == "/v/":
			yt_id = query.path.split("/")[2]

		# Remove URL parameters
		yt_id = yt_id.split("&")[0]

		# Assume we're dealing with videos
		if yt_id and not yt_type:
			yt_type = "video"

		# Check if a video ID has the right length
		if not yt_type or (yt_type == "video" and len(yt_id) != 11):
			return None

		return yt_id, yt_type, original_id

	def start_youtube_client(self):
		"""
		Starts the Google API client for the YouTube v3 API.
		An API key needs to be set at the start of this processor.
		"""
		try:
			# Use YouTubeDL and the YouTube API to request video data
			youtube = build("youtube", "v3", developerKey=self.api_key)
		# Catch invalid API keys
		except HttpError as e:
			return e

		self.client = youtube

	@staticmethod
	def batch_strings(strings: list, batch_size=50):
		"""
		A generator function to yield strings in batches of comma-separated values.
		"""
		for i in range(0, len(strings), batch_size):
			yield ','.join(strings[i:i + batch_size])

	def after_process(self):
		"""
		Override of the same function in processor.py
		Used to notify of potential API rate limit errors.

		"""
		super().after_process()
		if self.api_limit_reached:
			self.dataset.update_status("YouTube API quota limit exceeded. Saving the results retreived thus far. "
									   "To get all data, use your own API key, or try to split up the dataset and get "
									   "the YouTube data over the course of a few days.")
		elif self.invalid_api_key:
			self.dataset.update_status("Invalid API key. Extracted YouTube links but did not retreive any video "
									   "information.")
		else:
			self.dataset.update_status("Dataset saved.")
