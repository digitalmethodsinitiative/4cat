import config
import youtube_dl
from apiclient.discovery import build

youtube = build(config.YOUTUBE_API_SERVICE_NAME, config.YOUTUBE_API_VERSION,
					developerKey=config.YOUTUBE_DEVELOPER_KEY)
	
video_ids = '3UYfQARN2f8,IDaiOx4E53I,d0o_ZmdOiqc'

response = youtube.videos().list(
				part = 'snippet,contentDetails,statistics',
				id = video_ids,
				maxResults = 50
				).execute()

print(response)