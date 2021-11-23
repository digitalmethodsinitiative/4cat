"""
Retrieve YouTube Comments using Youtube APIv3
"""
import requests
import datetime
import time
import json
from apiclient.discovery import build

from backend.abstract.search import Search
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException
from common.lib.helpers import convert_to_int, UserInput

class SearchYouTube(Search):
    """
    Get Comments of a Video with YouTube APIv3
    """

    type = "youtube-search"  # job ID
	category = "Search"  # category
	title = "Get YouTube Comments"  # title displayed in UI
	description = "Retrieve YouTube comments per video."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

    def get_items(self, query):
        """
        Run custom search for video ID
        """
        
    api_key = "xxxxXXXXxxxxXXXXxxxxXXXXxxxxXXXXxxxxXXX" # This is the API-key of the 4CAT user
    youtube = build('youtube', 'v3', developerKey=api_key)

    ID = "xxxxXXXXxxxxXXXXxxxxXXXXxxxxXXXXxxxxXXX" # Replace this YouTube video ID with your own.

    box = [['Name', 'Comment', 'Time', 'Likes', 'Reply Count']]


    def scrape_comments_with_replies():
        data = youtube.commentThreads().list(part='snippet', videoId=ID, maxResults='100', textFormat="plainText").execute()

        for i in data["items"]:

            name = i["snippet"]['topLevelComment']["snippet"]["authorDisplayName"]
            comment = i["snippet"]['topLevelComment']["snippet"]["textDisplay"]
            published_at = i["snippet"]['topLevelComment']["snippet"]['publishedAt']
            likes = i["snippet"]['topLevelComment']["snippet"]['likeCount']
            replies = i["snippet"]['totalReplyCount']

            box.append([name, comment, published_at, likes, replies])

            totalReplyCount = i["snippet"]['totalReplyCount']

            if totalReplyCount > 0:

                parent = i["snippet"]['topLevelComment']["id"]

                data2 = youtube.comments().list(part='snippet', maxResults='100', parentId=parent,
                                                textFormat="plainText").execute()

                for i in data2["items"]:
                    name = i["snippet"]["authorDisplayName"]
                    comment = i["snippet"]["textDisplay"]
                    published_at = i["snippet"]['publishedAt']
                    likes = i["snippet"]['likeCount']
                    replies = ""

                    box.append([name, comment, published_at, likes, replies])

        while ("nextPageToken" in data):

            data = youtube.commentThreads().list(part='snippet', videoId=ID, pageToken=data["nextPageToken"],
                                                maxResults='100', textFormat="plainText").execute()

            for i in data["items"]:
                name = i["snippet"]['topLevelComment']["snippet"]["authorDisplayName"]
                comment = i["snippet"]['topLevelComment']["snippet"]["textDisplay"]
                published_at = i["snippet"]['topLevelComment']["snippet"]['publishedAt']
                likes = i["snippet"]['topLevelComment']["snippet"]['likeCount']
                replies = i["snippet"]['totalReplyCount']

                box.append([name, comment, published_at, likes, replies])

                totalReplyCount = i["snippet"]['totalReplyCount']

                if totalReplyCount > 0:

                    parent = i["snippet"]['topLevelComment']["id"]

                    data2 = youtube.comments().list(part='snippet', maxResults='100', parentId=parent,
                                                textFormat="plainText").execute()

                    for i in data2["items"]:
                        name = i["snippet"]["authorDisplayName"]
                        comment = i["snippet"]["textDisplay"]
                        published_at = i["snippet"]['publishedAt']
                        likes = i["snippet"]['likeCount']
                        replies = ''

                        box.append([name, comment, published_at, likes, replies])

        df = pd.DataFrame({'Name': [i[0] for i in box], 'Comment': [i[1] for i in box], 'Time': [i[2] for i in box],
                        'Likes': [i[3] for i in box], 'Reply Count': [i[4] for i in box]})
