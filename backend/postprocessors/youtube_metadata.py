"""
Thread data
"""
import datetime
import time
import re
import urllib.parse
import youtube_dl

from apiclient.discovery import build
from collections import OrderedDict, Counter
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
	title = "YouTube metadata"  # title displayed in UI
	description = "Extract information from YouTube links."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI
	datasources = ["4chan", "8chan", "reddit"]

	options = {
		"top": {
			"type": UserInput.OPTION_TEXT,
			"default": 25,
			"help": "Number of most-used links to include. Use 0 for all links"
		},
		"min": {
			"type": UserInput.OPTION_TEXT,
			"default": 5,
			"help": "Minimum amount of times the link must be posted. Use 0 for all links"
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

			csv = DictReader(source)

			self.query.update_status("Extracting YouTube links")
		
			# Reddit posts have a dedicated URL column
			if datasource == "reddit":
				# Group and order the URLs
				top_urls = Counter([post["url"] for post in csv if "youtu.be" in post["domain"] or "youtube.com" in post["domain"]])

			# Extract YT urls from the posts with 4chan or 8chan
			elif datasource == "4chan" or datasource == "8chan":
				link_regex = re.compile(r"https?://[^\s]+")
				www_regex = re.compile(r"^www\.")
				links = []

				# Read source file
				for post in csv:
					post_links = link_regex.findall(post["body"])
					if post_links:
						for link in post_links:

							# Only keep YouTube links. These two should be all options.
							if "youtu.be" in link or "youtube.com" in link:
								links.append(link)

				# Group and order the URLs
				top_urls = Counter(links)

		# Return if there's no YouTube URLs
		if not top_urls:
			return

		# Slice the amount of URLs depending on the user inputs
		cutoff = int(self.parameters.get("top"))
		if cutoff != 0:
			top_urls = top_urls.most_common(cutoff)
		else:
			top_urls = top_urls.most_common()
		min_mentions = int(self.parameters.get("min"))
		if min_mentions != 0:
			top_urls = [entry for entry in top_urls if entry[1] >= min_mentions]

		# List to store links and metadata 
		all_metadata = []

		self.query.update_status("Extracting metadata from " + str(len(top_urls)) + " YouTube URLs")
		
		# Loop through all the URLs
		for counter, entry in enumerate(top_urls):

			url = entry[0]
			count = entry[1]

			# Get metadata. If it fails
			metadata = get_youtube_metadata(url)

			# Add the amount it has been linked to
			metadata["count"] = count
			
			# Store data
			all_metadata.append(metadata)
			
			# Update status once in a while
			if counter % 10 == 0:
				self.query.update_status("Extracted metadata " + str(counter) + "/" + str(len(top_urls)))
				#print("Extracted metadata " + str(counter) + "/" + str(len(top_urls)))

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

		self.query.write_csv_and_finish(all_metadata)

def get_youtube_metadata(url):
	"""
	:param str url, a url referencing a channel or video
	:returns dict, containing metadata on the YouTube URL

	"""

	metadata = None

	# Get the data for channels and videos
	if "/channel/" in url:
		valid_id = get_channel_id(url)
		if valid_id:
			metadata = get_channel_metadata(valid_id)
	else:
		valid_id = get_video_id(url)
		if valid_id:
			metadata = get_video_metadata(valid_id)

	# If data collection failed, create an almost empty dict
	if not valid_id or not metadata:
		metadata = {}
		metadata["type"] = "unknown"

	# Store the reference URL for every entry
	metadata["url"] = url

	return metadata

def get_channel_id(url):
	"""
	:param str, url: list or string of YT URLs
	:returns str id: The id of the channel
	Gets the channel IDs from a string of YT URLs
	Can link to videos, channels, or users.

	"""

	channel_id = False

	if "channel" in url and "watch?" not in url:
		# Get channel ID
		try:
			url = url.split("channel")
			channel_id = url[1].split("/")[1]
		except Exception as error:
			channel_id = False

	return channel_id

def get_video_id(url):
	"""
	:param str url: string of YT URLs

	"""

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
	
	return video_id

def get_channel_metadata(channel_id):
	"""
	Use the YouTube API to fetch metadata from a channel.
	:param str channel_id, a valild YouTube channel ID
	:return dict, YouTube's response metadata

	"""

	metadata = {}

	# Use YouTubeDL and the YouTube API to request channel data
	youtube = build(config.YOUTUBE_API_SERVICE_NAME, config.YOUTUBE_API_VERSION,
					developerKey=config.YOUTUBE_DEVELOPER_KEY)
	while True:
		try:
			response = youtube.channels().list(
			part = "snippet,contentDetails,topicDetails,statistics,brandingSettings",
			id = channel_id
			).execute()
			break
		except HttpError as e:
			time.sleep(10)
			pass

	result = {}

	# Get and return results
	if response["items"]:
		metadata = response["items"][0]
	else:
		return

	result["type"] = "channel"
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

def get_video_metadata(video_id):
	"""
	Use the YouTube API to fetch metadata from a video.
	:param str channel_id, a valild YouTube video ID
	:return dict, YouTube's response metadata

	"""

	metadata = {}
	

	# Use YouTubeDL and the YouTube API to request video data
	youtube = build(config.YOUTUBE_API_SERVICE_NAME, config.YOUTUBE_API_VERSION,
										developerKey=config.YOUTUBE_DEVELOPER_KEY)

	while True:
		try:
			response = youtube.videos().list(
					part = 'snippet,contentDetails,statistics',
					id = video_id
					).execute()
			break
		except HttpError as e:
			time.sleep(10)
			pass

	#print(response)

	# Check if a valid reponse is provided by the API
	if response["items"]:
		metadata = response["items"][0]
	else:
		return
	
	# Get and return results
	result = {}
	result["type"] = "video"
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