"""
Thread data
"""
import datetime
import time
import re
import urllib
import youtube_dl

from apiclient.discovery import build
from collections import OrderedDict, Counter
from operator import itemgetter
from csv import DictReader

from backend.abstract.postprocessor import BasicPostProcessor
from backend.lib.helpers import UserInput

import config

class YouTubeMetadata(BasicPostProcessor):
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
			"default": 25,
			"help": "Top n most-frequently referenced pages (0 = all)"
		},
		"min": {
			"type": UserInput.OPTION_TEXT,
			"default": 5,
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

		self.query.update_status("Reading source file")
		with open(self.source_file, encoding="utf-8") as source:

			# Read source file
			csv = DictReader(source)

			self.query.update_status("Extracting YouTube links")

			# Use a dict with post IDs as keys
			# and a list of YouTube URLs referenced as value
			urls = {}

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
			self.query.update_status("Finished")
			return

		# Get metadata.
		results = get_youtube_metadata(self, urls)

		if not results:
			self.query.update_status("Finished")
			return

		self.query.update_status("Writing results to csv.")
		self.query.write_csv_and_finish(results)

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
	video_ids = parse_video_ids(urls)
	channel_ids = parse_channel_ids(urls)
	unique_video_ids = set(video_ids.keys())
	unique_channel_ids = set(channel_ids.keys())
	all_ids = dict(video_ids, **channel_ids)

	# Slice the amount of URLs depending on the user inputs
	cutoff = int(self.parameters.get("top"))
	min_mentions = int(self.parameters.get("min"))

	# Determine the lowest number in the top n entries, and use it as a cutoff
	if cutoff != 0:
		cutoff = min(sorted([len(value) for value in all_ids.values()])[:cutoff])
	
	# Create a new dict with the amount of references, filtered on user thresholds
	top_ids = {}
	for youtube_id, urls in all_ids.items():
		count = len(urls)
		if count >= min_mentions and count >= cutoff:
			top_ids[youtube_id] = count

	# Sort by most frequently posted pages
	top_ids = OrderedDict(sorted(top_ids.items(), key=itemgetter(1)))

	# Return if there's nothing left after the cutoff
	if not top_ids:
		return

	# Store all data in here
	all_metadata = []

	counter = 0

	self.query.update_status("Extracting metadata from " + str(len(top_ids)) + " YouTube URLs")

	# Loop through all IDs and get metadata per instance
	for youtube_id, count in top_ids.items():

		metadata = {}
		new_metadata = None

		if youtube_id in unique_video_ids:
			metadata["type"] = "video"
			try:
				new_metadata = get_video_metadata(self, youtube_id)
			except Exception as e:
				metadata["error_code"] = str(e)
		
		elif youtube_id in unique_channel_ids:
			metadata["type"] = "channel"
			try:
				new_metadata = get_channel_metadata(self, youtube_id)
			except Exception as e:
				metadata["error_code"] = str(e)

		if not new_metadata:
			metadata["deleted_or_failed"] = True

		# Store the URL(s) used to reference the channel or video
		# Also store who referenced this channel/video in the original dataset.
		# This will be useful for cross-referencing.
		urls_referenced = list(set(all_ids[youtube_id]))
		referenced_by = []
		for url_referenced in urls_referenced:
			referenced_by += list(set(di_urls[url_referenced]))
		metadata["referenced_urls"] = ','.join(urls_referenced)
		metadata["referenced_by"] = ','.join(referenced_by)

		# Store the amount of times the channel/video is linked
		metadata["count"] = len(referenced_by)

		# Add the new metadata after the metrics (looks nice in csv!)
		if new_metadata:
			metadata = {**metadata, **new_metadata}

		# Store the metadata in a longer list
		all_metadata.append(metadata)

		counter += 1

		# Update status once in a while
		if counter % 10 == 0:
			self.query.update_status("Extracted metadata " + str(counter) + "/" + str(len(top_ids)))

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

def parse_channel_ids(urls):
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
					if channel_id not in ids:
						# Make it a list if there only one string entry yet
						ids[channel_id] = [url]
					else:
						ids[channel_id].append(url)
			except Exception as error:
				channel_id = False

	return ids

def parse_video_ids(urls):
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
				if video_id not in ids:
					ids[video_id] = [url]
				else:
					ids[video_id].append(url)
	return ids

def get_channel_metadata(self, channel_id):
	"""
	Use the YouTube API to fetch metadata from a channel.

	:param str channel_id, a valild YouTube channel ID
	:returns dict, containing YouTube's response metadata

	"""

	# Use YouTubeDL and the YouTube API to request channel data
	youtube = build(config.YOUTUBE_API_SERVICE_NAME, config.YOUTUBE_API_VERSION,
					developerKey=config.YOUTUBE_DEVELOPER_KEY)
	retries = 0
	api_error = ""
	while retries < self.max_retries:
		try:
			response = youtube.channels().list(
			part = "snippet,contentDetails,topicDetails,statistics,brandingSettings",
			id = channel_id
			).execute()
			break

		except urllib.error.HTTPError as error:
			self.query.update_status("Encountered exception " + str(e) + ".\nSleeping for " + str(self.sleep_time))
			retries += 1
			api_error = error
			time.sleep(self.sleep_time) # Wait a bit before trying again

	# Raise error if the requests failed
	if retries >= self.max_retries:
		self.log.error("Error during youtube_dl of query %s" % self.query.key)
		self.query.update_status("Error while getting YouTube data")
		raise api_error

	# Get and return results
	if response["items"]:
		metadata = response["items"][0]
	else:
		return

	result = {}
	result["channel_id"] = metadata["id"]
	result["channel_title"] = metadata["snippet"].get("title")
	result["channel_description"] = metadata["snippet"].get("description")
	result["channel_default_language"] = metadata["snippet"].get("defaultLanguage")
	result["channel_country"] = metadata["snippet"].get("country")
	result["channel_viewcount"] = metadata["statistics"].get("viewCount")
	result["channel_commentcount"] = metadata["statistics"].get("commentCount")
	result["channel_subscribercount"] = metadata["statistics"].get("subscriberCount")
	result["channel_videocount"] = metadata["statistics"].get("videoCount")
	result["channel_topic_ids"] = metadata["topicDetails"].get("topicIds")
	result["channel_topic_categories"] = metadata["topicDetails"].get("topicCategories")
	result["channel_branding_keywords"] = metadata["brandingSettings"]["channel"].get("keywords")

	return result

def get_video_metadata(self, video_id):
	"""
	Use the YouTube API to fetch metadata from a video.
	:param str channel_id, a valild YouTube video ID
	:return dict, containing YouTube's response metadata

	"""
	
	# Use YouTubeDL and the YouTube API to request video data
	youtube = build(config.YOUTUBE_API_SERVICE_NAME, config.YOUTUBE_API_VERSION,
										developerKey=config.YOUTUBE_DEVELOPER_KEY)

	retries = 0
	api_error = ""
	while retries < self.max_retries:
		try:
			response = youtube.videos().list(
				part = 'snippet,contentDetails,statistics',
				id = video_id
				).execute()
			break

		except urllib.error.HTTPError as error:
			self.query.update_status("Encountered exception " + str(e) + ".\nSleeping for " + str(self.sleep_time))
			retries += 1
			api_error = error
			time.sleep(self.sleep_time) # Wait a bit before trying again

	# Raise error if the requests failed
	if retries >= self.max_retries:
		self.log.error("Error during youtube_dl of query %s" % self.query.key)
		self.query.update_status("Error while getting YouTube data")
		raise api_error

	# Check if a valid reponse is provided by the API
	if response["items"]:
		metadata = response["items"][0]
	else:
		return
	
	# Get and return results
	result = {}
	result["video_id"] = metadata["id"]
	result["upload_time"] = metadata["snippet"].get("publishedAt")
	result["channel_id"] = metadata["snippet"].get("channelId")
	result["channel_title"] = metadata["snippet"].get("channelTitle")
	result["video_title"] = metadata["snippet"].get("title")
	result["video_duration"] = metadata.get("contentDetails").get("duration")
	result["video_view_count"] = metadata["statistics"].get("viewCount")
	result["video_comment_count"] = metadata["statistics"].get("commentCount")
	result["video_likes_count"] = metadata["statistics"].get("likeCount")
	result["video_dislikes_count"] = metadata["statistics"].get("dislikeCount")
	result["video_topic_ids"] = metadata.get("topicDetails")
	result["video_category_id"] = metadata["snippet"].get("categoryId")
	result["video_tags"] = metadata["snippet"].get("tags")

	return result