"""
Get YouTube metadata from video links posted
"""
import datetime
import time
import re
import urllib.request
import youtube_dl

from apiclient.discovery import build
from collections import OrderedDict, Counter
from operator import itemgetter
from csv import DictReader

from backend.abstract.processor import BasicProcessor
from backend.lib.helpers import UserInput, get_yt_compatible_ids

import config

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
	datasources = ["4chan", "8chan", "reddit"]

	max_retries = 3
	sleep_time = 20

	options = {
		"top": {
			"type": UserInput.OPTION_TEXT,
			"default": 0,
			"help": "Top n most-frequently referenced pages (0 = all)"
		},
		"min": {
			"type": UserInput.OPTION_TEXT,
			"default": 0,
			"help": "Times a page must be referenced (0 = all)"
		}
	}

	def process(self):
		"""
		Takes a 4CAT input file with a URL column.
		Checks whether these URLs contain YouTube URLs.
		If so, it extracts these, groups and orders them by frequency,
		and extracts metadata per link.
		These links may contain URLs to	videos or channels.

		"""

		datasource = self.parent.parameters.get("datasource")

		# Use a dict with post IDs as keys
		# and a list of YouTube URLs referenced as value
		urls = {}

		self.dataset.update_status("Reading source file")
		with open(self.source_file, encoding="utf-8") as source:

			# Read source file
			csv = DictReader(source)

			self.dataset.update_status("Extracting YouTube links")

			link_regex = re.compile(r"https?://[^\s]+")
			www_regex = re.compile(r"^www\.")

			for post in csv:
				# Reddit posts have a dedicated URL column.
				# Start with these and then append URLs from the OP text and commments.
				post_urls = []

				if datasource == "reddit":
					if "youtu.be" in post.get("domain") or "youtube.com" in post.get("domain"):
						post_urls.append(post["url"])
				
				# Extract more YouTube urls from the post body		
				if "youtu" in post["body"]: # If statement to speed things up
					post_links = link_regex.findall(post["body"])
					if post_links:
						for link in post_links:
							# Only keep YouTube links. These two should be all options.
							if "youtu.be" in link or "youtube.com" in link:
								post_urls.append(link)

				# Store the URLs as values with the post ID as a key
				if post_urls:
					for post_url in post_urls:
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
		self.dataset.write_csv_and_finish(results)

	def get_youtube_metadata(self, urls):
		"""
		Gets metadata from various YouTube URLs.
		Currently only supports channels and videos.

		:param list or dict url, a list to urls referencing a channel or video
				or a dictionary with the urls as keys and post IDs as avlues
		:returns dict, containing metadata on the YouTube URL

		"""

		if isinstance(urls, str):
			urls = [urls]

		if isinstance(urls, dict):
			di_urls = urls
			urls = list(urls.keys())

		# Parse video and channel IDs from URLs and add back together
		video_ids = self.parse_video_ids(urls)
		channel_ids = self.parse_channel_ids(urls)
		unique_video_ids = list(set(video_ids.keys()))
		unique_channel_ids = list(set(channel_ids.keys()))
		all_ids = dict(video_ids, **channel_ids)

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
		video_data = request_youtube_api(self, videos_to_fetch, object_type="video")
		channel_data = request_youtube_api(self, channels_to_fetch, object_type="channel")
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
				query = urllib.parse.urlparse(url)

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

def request_youtube_api(self, ids, object_type="video"):
	"""
	Use the YouTube API to fetch metadata from videos or channels.
	:param video_ids str, a list of valid YouTube IDs
	:param type str, the type of object to query. Currently only `video` or `channel`. 
	:return list, containing dicts with YouTube's response metadata.
	Max 50 results per try.

	"""
	
	ids_list = get_yt_compatible_ids(ids)

	if object_type != "video" and object_type != "channel":
		return "No valid YouTube object type (currently only 'channel' and 'video' are supported)"

	# List of dicts for all video data
	results = {}

	for i, ids_string in enumerate(ids_list):

		retries = 0
		api_error = ""

		# Use YouTubeDL and the YouTube API to request video data
		youtube = build(config.YOUTUBE_API_SERVICE_NAME, config.YOUTUBE_API_VERSION,
											developerKey=config.YOUTUBE_DEVELOPER_KEY)
		
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
				break

			except Exception as error:
				self.dataset.update_status("Encountered exception " + str(error) + ".\nSleeping for " + str(self.sleep_time))
				retries += 1
				api_error = error
				time.sleep(self.sleep_time) # Wait a bit before trying again
				pass

		# Do nothing with the results if the requests failed -
		# be in the final results file
		if retries >= self.max_retries:
			self.log.error("Error during YouTube API request of query %s" % self.dataset.key)
			self.dataset.update_status("Error while getting YouTube data")

		else:
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
		self.dataset.update_status("Got metadata from " + str(i * 50) + "/" + str(len(ids)) + " YouTube URLs")

	return results