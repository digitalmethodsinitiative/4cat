"""
Get YouTube metadata from video links posted
"""
import time
import re
import csv
import urllib.request

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput, get_yt_compatible_ids

import config

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
	category = "Post metrics" # category
	title = "YouTube URL metadata"  # title displayed in UI
	description = "Extract information from YouTube links to videos and channels"  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	max_retries = 3
	sleep_time = 20

	api_limit_reached = False
	invalid_api_key = False

	references = [
		"[YouTube API v3 documentation](https://developers.google.com/youtube/v3)",
		"[4chan’s YouTube: A Fringe Perspective on YouTube’s Great Purge of 2019 - OILab.eu](https://oilab.eu/4chans-youtube-a-fringe-perspective-on-youtubes-great-purge-of-2019/)"
	]

	options = {
		"top": {
			"type": UserInput.OPTION_TEXT,
			"default": 100,
			"help": "Top n most-frequently referenced videos/channels (0 = all)"
		},
		"min": {
			"type": UserInput.OPTION_TEXT,
			"default": 0,
			"help": "Times a video/channel must be referenced (0 = all)"
		},
		"custom-key": {
			"type": UserInput.OPTION_TEXT,
			"default": "",
			"help": "Optional: A custom YouTube API key. Leave empty for 4CAT's API key."
		}
	}

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor on datasets probably containing youtube links

		:param module: Dataset or processor to determine compatibility with
		"""
		# Compatible with every top-level dataset.
		return module.is_top_dataset()

	def process(self):
		"""
		Takes a 4CAT input file with a body columns.
		Extracts URLs and checks whether these are YouTube URLs.
		If so, it extracts these, groups and orders them by frequency,
		and extracts metadata per link.
		These links may contain URLs to	videos or channels.

		"""

		# First check if there's a YouTube Developer API key in config
		if not config.YOUTUBE_DEVELOPER_KEY:
			self.dataset.update_status("No API key found")
			self.dataset.finish(0)
			return

		datasource = self.source_dataset.parameters.get("datasource")

		# Use a dict with post IDs as keys
		# and a list of YouTube URLs referenced as value
		urls = {}

		self.dataset.update_status("Extracting YouTube links")

		link_regex = re.compile(r"https?://[^\s]+")
		www_regex = re.compile(r"^www\.")

		for post in self.iterate_items(self.source_file):

			post_urls = []

			# Reddit posts have a dedicated URL column.
			# Start with these and then append URLs from the OP text and commments.
			if datasource == "reddit":
				if "youtu.be" in post.get("domain") or "youtube.com" in post.get("domain"):
					post_urls.append(post["url"])

			# Extract more YouTube urls from the post body
			if "youtu" in post["body"]:  # If statement to speed things up
				post_links = link_regex.findall(post["body"])
				if post_links:
					for link in post_links:
						# Only keep YouTube links. These two should be all options.
						if "youtu.be" in link or "youtube.com" in link:
							post_urls.append(link)

			# Store the URLs as values with the post ID as a key
			if post_urls:
				for post_url in post_urls:

					# Sometimes markdown links appear,
					# like https://streamlink.ou](https://www.youtube.com/watch?v=PHgc8Q6qTjc)
					# Split and keep the last containing a YT link
					if "](" in post_url:
						post_url = post_url.split("](")
						for post_url_single in post_url:
							if "youtu" in post_url_single:
								post_url = post_url_single

					# Get rid of unwanted (often trailing) characters
					post_url = re.sub(r"[(),|]", "", post_url)

					if post_url in urls:
						urls[post_url].append(post["id"])
					else:
						urls[post_url] = [post["id"]]

		# Return if there's no YouTube URLs
		if not urls:
			self.dataset.update_status("Finished")
			self.dataset.finish(0)
			return

		# Get metadata.
		results = self.get_youtube_metadata(urls)

		if not results:
			self.dataset.update_status("Finished")
			self.dataset.finish(0)
			return

		self.dataset.update_status("Writing results to csv.")
		self.write_csv_items_and_finish(results)

	def get_youtube_metadata(self, di_urls):
		"""
		Gets metadata from various YouTube URLs.
		Currently only supports channels and videos.

		:param di_urls, dict: A dictionary with URLs as keys and post ids as values
		:returns dict: containing metadata on the YouTube URL

		"""

		urls = list(di_urls.keys())

		# Parse video and channel IDs from URLs and add back together
		video_ids = self.parse_video_ids(urls)
		channel_ids = self.parse_channel_ids(urls)
		unique_video_ids = list(set(video_ids.keys()))
		unique_channel_ids = list(set(channel_ids.keys()))
		all_ids = dict(video_ids, **channel_ids)

		# Use a custom API key if provided
		custom_key = self.parameters.get("custom-key")

		try:
			min_mentions = int(self.parameters.get("min"))
		except ValueError:
			min_mentions = 0

		# Make a list of dicts with meta info about the YouTube URLs,
		# including the post ids, urls, and times referenced.
		urls_metadata = []
		for youtube_id, urls in all_ids.items():
			# Store the unique URLs used to reference the video/channel.
			# This can for instance include timestamps (e.g. '&t=19s'),
			# which might be interesting at a later point.
			url_metadata = {}
			url_metadata["id"] = youtube_id
			url_metadata["urls_referenced"] = list(urls)

			referenced_by = []
			for url in urls:
				# Make the 'referenced by' a set to prevent
				# spammers posting the same link in one post
				# to overrepresent
				referenced_by += list(set(di_urls[url]))

			url_metadata["referenced_urls"] = urls
			url_metadata["referenced_by"] = referenced_by

			# Store the amount of times the channel/video is linked
			url_metadata["count"] = len(referenced_by)

			# only use the data if it meets the user threshold
			if url_metadata["count"] >= min_mentions:
				urls_metadata.append(url_metadata)

		# Sort the dict by frequency
		urls_metadata = sorted(urls_metadata, key=lambda i: i['count'], reverse=True)

		# Slice the amount of URLs depending on the user inputs
		try:
			top = int(self.parameters.get("top"))
		except ValueError:
			top = 0
		if top != 0:
			if top < len(urls_metadata):
				urls_metadata = urls_metadata[:top]
		
		# These IDs we'll actually fetch
		videos_to_fetch = []
		channels_to_fetch = []
		for url_metadata in urls_metadata:
			if url_metadata["id"] in unique_video_ids:
				videos_to_fetch.append(url_metadata["id"])
			if url_metadata["id"] in unique_channel_ids:
				channels_to_fetch.append(url_metadata["id"])
		
		# Return if there's nothing left after the cutoff
		if not urls_metadata:
			return

		# Store all YouTube API data in here
		all_metadata = []

		counter = 0

		# Get YouTube API data for all videos and channels
		video_data = self.request_youtube_api(videos_to_fetch, custom_key=custom_key, object_type="video")
		channel_data = self.request_youtube_api(channels_to_fetch, custom_key=custom_key, object_type="channel")
		api_results = {**video_data, **channel_data}

		# Loop through retreived videos and channels
		for youtube_item in urls_metadata:

			youtube_id = youtube_item["id"]

			# Dict that will become the csv row.
			# Store some default values so it's placed in the first columns
			metadata = {"id": youtube_id, "deleted_or_failed": False, "count": 0}
			
			# Get the YouTube API dict for the relevant video/channel
			api_data = api_results.get(youtube_id)

			if not api_data:
				metadata["deleted_or_failed"] = True

			# Store data from original post file for cross-referencing
			metadata["referenced_urls"] = ','.join(youtube_item["urls_referenced"])
			metadata["referenced_by"] = ','.join(youtube_item["referenced_by"])
			metadata["count"] = youtube_item["count"]

			# Add api data if the request for the item was succesfull
			if api_data:
				metadata = {**metadata, **api_data}

			# Store the metadata the overall list
			all_metadata.append(metadata)

			counter += 1

			# Update status once in a while
			if counter % 10 == 0:
				self.dataset.update_status("Extracted metadata " + str(counter) + "/" + str(len(urls_metadata)))

		# To write to csv, all dictionary items must have all the possible keys
		# Get all the possible keys
		all_keys = []
		for entry in all_metadata:
			for key in entry.keys():
				if key not in all_keys:
					all_keys.append(key)

		# Make sure all possible items are in every dict entry.
		for entry in all_metadata:
			for contain_key in all_keys:
				if contain_key not in entry.keys():
					entry[contain_key] = None

		return all_metadata

	def parse_channel_ids(self, urls):
		"""
		Parses the channel ID from URLs pointing to a YouTube channel.

		:param str, url: string of a URL pointing to a YouTube channel.
		:returns dict ids: dict with validly parsed IDs as keys and URLs as values.

		"""

		# Parse string to list so the loop works
		if isinstance(urls, str):
			urls = [urls]

		ids = {}

		for url in urls:
			channel_id = False

			if "channel" in url and "watch?" not in url:
				# Get channel ID
				try:
					url_splitted = url.split("channel")
					channel_id = url_splitted[1].split("/")[1]

					# Check if we already encountered the ID.
					# If so, we're appending the URL to that existing
					# key in the dictionary
					if channel_id:
						channel_id = channel_id.strip().replace(",","")
						if channel_id not in ids:
							# Make it a list if there only one string entry yet
							ids[channel_id] = [url]
						else:
							ids[channel_id].append(url)
				except Exception as error:
					channel_id = False

		return ids

	def parse_video_ids(self, urls):
		"""
		Gets the video ID from URLs pointing to a YouTube video.
		
		:param str url: string of a URL pointing to a YouTube video.
		:returns dict ids: dict with validly parsed IDs as keys and URLs as values.

		"""

		# Parse string to list so the loop works
		if isinstance(urls, str):
			urls = [urls]

		ids = {}

		for url in urls:
			video_id = False

			if "youtu" in url:

				# Extract the YouTube link
				try:
					query = urllib.parse.urlparse(url)
				# In large datasets, malformed links occur. Catch these and continue.
				except ValueError as e:
					continue

				# youtu.be URLs always reference videos
				if query.hostname == "youtu.be":
					video_id = query.path[1:]

				elif query.hostname in ("www.youtube.com", "youtube.com", "m.youtube.com"):
					if query.path == "/watch":
						parsed_url = urllib.parse.parse_qs(query.query)
						if "v" in parsed_url:
							video_id = parsed_url["v"][0]
					elif query.path[:7] == "/embed/":
						video_id = query.path.split("/")[2]
					elif query.path[:3] == "/v/":
						video_id = query.path.split("/")[2]
				
				# Check if we already encountered the ID.
				# If so, we're appending the URL to that existing
				# key in the dictionary
				if video_id:
					video_id = video_id.strip().replace(",","")
					if video_id not in ids:
						ids[video_id] = [url]
					else:
						ids[video_id].append(url)

		return ids

	def request_youtube_api(self, ids, custom_key=None, object_type="video"):
		"""
		Use the YouTube API to fetch metadata from videos or channels.

		:param video_ids, str:		A list of valid YouTube IDs
		:param custom_key, str:		A custom API key which can be provided by the user.
		:param object_type, str:	The type of object to query. Currently only `video` or `channel`. 
		
		:return list, containing dicts with YouTube's response metadata.
		Max 50 results per try.

		"""
		
		ids_list = get_yt_compatible_ids(ids)

		if object_type != "video" and object_type != "channel":
			return "No valid YouTube object type (currently only 'channel' and 'video' are supported)"

		# List of dicts for all video data
		results = {}

		# Use standard key or custom key
		if custom_key:
			api_key = custom_key
		else:
			api_key = config.YOUTUBE_DEVELOPER_KEY

		for i, ids_string in enumerate(ids_list):

			retries = 0
			api_error = ""

			try:
				# Use YouTubeDL and the YouTube API to request video data
				youtube = build(config.YOUTUBE_API_SERVICE_NAME, config.YOUTUBE_API_VERSION,
												developerKey=api_key)
			# Catch invalid API keys
			except HttpError as e:
				if e.resp.status == 400: # "Bad Request"
					self.invalid_api_key = True
					return results
			# Google API's also throws other weird errors that might be resolved by retrying, like SSLEOFError
			except Exception as e:
				time.sleep(self.sleep_time) # Wait a bit before trying again
				pass

			while retries < self.max_retries:
				try:
					if object_type == "video":
						response = youtube.videos().list(
							part = 'snippet,contentDetails,statistics',
							id = ids_string,
							maxResults = 50
							).execute()
					elif object_type == "channel":
						response = youtube.channels().list(
							part = "snippet,topicDetails,statistics,brandingSettings",
							id = ids_string,
							maxResults = 50
						).execute()

					self.api_limit_reached = False

					break

				# Check rate limits
				except HttpError as httperror:

					status_code = httperror.resp.status

					if status_code == 403: # "Forbidden", what Google returns with rate limits
						retries += 1
						self.api_limit_reached = True
						self.dataset.update_status("API quota limit might be reached (HTTP" + str(status_code) + "), sleeping for " + str(self.sleep_time))
						time.sleep(self.sleep_time) # Wait a bit before trying again
						pass

					else:
						retries += 1
						self.dataset.update_status("API error encoutered (HTTP" + str(status_code) + "), sleeping for " + str(self.sleep_time))
						time.sleep(self.sleep_time) # Wait a bit before trying again
						pass

				# Google API's also throws other weird errors that might be resolved by retrying, like SSLEOFError
				except Exception as e:
					retries += 1
					self.dataset.update_status("Error encoutered, sleeping for " + str(self.sleep_time))
					time.sleep(self.sleep_time) # Wait a bit before trying again
					pass

			# Do nothing with the results if the requests failed
			if retries > self.max_retries:
				if self.api_limit_reached == True:
					self.dataset.update_status("Daily YouTube API requests exceeded.")

				return results

			else:

				# Sometimes there's no results,
				# and "respoonse" won't have an item key.
				if "items" not in response:
					continue

				# Get and return results for each video
				for metadata in response["items"]:
					result = {}

					# This will become the key
					result_id = metadata["id"]

					if object_type == "video":

						# Results as dict entries
						result["type"] = "video"

						result["upload_time"] = metadata["snippet"].get("publishedAt")
						result["channel_id"] = metadata["snippet"].get("channelId")
						result["channel_title"] = metadata["snippet"].get("channelTitle")
						result["video_id"] = metadata["snippet"].get("videoId")
						result["video_title"] = metadata["snippet"].get("title")
						result["video_duration"] = metadata.get("contentDetails").get("duration")
						result["video_view_count"] = metadata["statistics"].get("viewCount")
						result["video_comment_count"] = metadata["statistics"].get("commentCount")
						result["video_likes_count"] = metadata["statistics"].get("likeCount")
						result["video_dislikes_count"] = metadata["statistics"].get("dislikeCount")
						result["video_topic_ids"] = metadata.get("topicDetails")
						result["video_category_id"] = metadata["snippet"].get("categoryId")
						result["video_tags"] = metadata["snippet"].get("tags")

					elif object_type == "channel":

						# Results as dict entries
						result["type"] = "channel"
						result["channel_id"] = metadata["snippet"].get("channelId")
						result["channel_title"] = metadata["snippet"].get("title")
						result["channel_description"] = metadata["snippet"].get("description")
						result["channel_default_language"] = metadata["snippet"].get("defaultLanguage")
						result["channel_country"] = metadata["snippet"].get("country")
						result["channel_viewcount"] = metadata["statistics"].get("viewCount")
						result["channel_commentcount"] = metadata["statistics"].get("commentCount")
						result["channel_subscribercount"] = metadata["statistics"].get("subscriberCount")
						result["channel_videocount"] = metadata["statistics"].get("videoCount")
						# This one sometimes fails for some reason
						if "topicDetails" in metadata:
							result["channel_topic_ids"] = metadata["topicDetails"].get("topicIds")
							result["channel_topic_categories"] = metadata["topicDetails"].get("topicCategories")
						result["channel_branding_keywords"] = metadata.get("brandingSettings").get("channel").get("keywords")

					results[result_id] = result

			# Update status per response item
			self.dataset.update_status("Got metadata from " + str(i * 50) + "/" + str(len(ids)) + " " + object_type + " YouTube URLs")

		return results

	def after_process(self):
		"""
		Override of the same function in processor.py
		Used to notify of potential API rate limit errors.

		"""
		super().after_process()
		if self.api_limit_reached:
			self.dataset.update_status("YouTube API quota limit exceeded. Saving the results retreived thus far. To get all data, use your own API key, or try to split up the dataset and get the YouTube data over the course of a few days.")
		elif self.invalid_api_key:
			self.dataset.update_status("Invalid API key. Extracted YouTube links but did not retreive any video information.")
		else:
			self.dataset.update_status("Dataset saved.")