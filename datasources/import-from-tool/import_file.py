"""
Custom data upload to create bespoke datasets
"""
import datetime
import time
import json
import csv
import re
import io

from backend.abstract.worker import BasicWorker
from backend.lib.exceptions import QueryParametersException
from backend.lib.helpers import get_software_version, sniff_encoding


class ImportFromExternalTool(BasicWorker):
	type = "customimport-search"  # job ID
	category = "Search"  # category
	title = "Custom Dataset Upload"  # title displayed in UI
	description = "Upload your own CSV file to be used as a dataset"  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	# not available as a processor for existing datasets
	accepts = [None]

	max_workers = 1

	required_columns = {
		"instagram-crowdtangle": (
			"\ufeffAccount", "User Name", "Followers at Posting", "Created", "Type", "Likes", "Comments", "Views",
			"URL", "Link",
			"Photo", "Title", "Description"),
		"instagram-dmi-scraper": (
			"id", "thread_id", "parent_id", "body", "author", "timestamp", "type", "url", "thumbnail_url", "hashtags",
			"usertags", "mentioned", "num_likes", "num_comments", "subject"
		),
		"facebook-crowdtangle": (
			"User Name", "Facebook Id", "Likes at Posting", "Followers at Posting", "Created", "Type",
			"Likes", "Comments", "Shares", "Love", "Wow", "Haha", "Sad", "Angry", "Care", "Video Share Status",
			"Post Views", "Total Views", "Total Views For All Crossposts", "Video Length", "URL", "Message", "Link",
			"Final Link", "Image Text", "Link Text", "Description", "Sponsor Id", "Sponsor Name", "Total Interactions"
		),
		"tiktok": (
			"id", "text", "createTime", "authorMeta.name", "authorMeta.id", "musicMeta.musicId", "musicMeta.musicName",
			"musicMeta.musicAuthor", "imageUrl", "videoUrl", "diggCount", "shareCount", "playCount", "commentCount",
			"mentions", "hashtags"
		),
		"facepager": (
			"path", "id", "parent_id", "level", "object_id", "object_type", "query_status", "query_time", "query_type",
			"from.name", "created_time", "type", "link", "picture", "full_picture", "", "comments.summary.total_count",
			"shares.count", "reactions.summary.total_count", "like.summary.total_count", "love.summary.total_count",
			"haha.summary.total_count", "wow.summary.total_count", "sad.summary.total_count",
			"angry.summary.total_count", "message"
		)
	}

	def work(self):
		"""
		Run custom search

		All work is done while uploading the data, so this just has to 'finish'
		the job.
		"""

		self.job.finish()

	def validate_query(query, request, user):
		"""
		Validate custom data input

		Confirms that the uploaded file is a valid CSV or tab file and, if so, returns
		some metadata.

		:param dict query:  Query parameters, from client-side.
		:param request:  Flask request
		:param User user:  User object of user who has submitted the query
		:return dict:  Safe query parameters
		"""

		# do we have an uploaded file?
		if "data_upload" not in request.files:
			raise QueryParametersException("No file was offered for upload.")

		platform = query.get("platform", "")
		if platform not in ImportFromExternalTool.required_columns:
			raise QueryParametersException("Invalid platform")

		file = request.files["data_upload"]
		if not file:
			raise QueryParametersException("No file was offered for upload.")

		# detect encoding - UTF-8 with or without BOM
		encoding = sniff_encoding(file)
		wrapped_upload = io.TextIOWrapper(file, encoding=encoding)

		# validate file as csv
		reader = csv.DictReader(wrapped_upload, delimiter=",")

		try:
			fields = reader.fieldnames
		except UnicodeDecodeError:
			raise QueryParametersException("Uploaded file is not a well-formed CSV file.")

		# check if all required fields are present
		required = ImportFromExternalTool.required_columns[platform]
		missing = []
		for field in required:
			if field not in reader.fieldnames:
				missing.append(field)

		if missing:
			wrapped_upload.detach()
			print(missing)
			print(reader.fieldnames)
			raise QueryParametersException(
				"The following required columns are not present in the csv file: %s. Provided field names: %s" % (", ".join(missing), ", ".join(reader.fieldnames)))

		wrapped_upload.detach()

		# return metadata - the filename is sanitised and serves no purpose at
		# this point in time, but can be used to uniquely identify a dataset
		disallowed_characters = re.compile(r"[^a-zA-Z0-9._+-]")
		return {"filename": disallowed_characters.sub("", file.filename), "time": time.time(), "datasource": platform,
				"board": "upload", "platform": platform}

	def after_create(query, dataset, request):
		"""
		Hook to execute after the dataset for this source has been created

		In this case, it is used to save the uploaded file to the dataset's
		result path, and finalise the dataset metadata.

		:param dict query:  Sanitised query parameters
		:param DataSet dataset:  Dataset created for this query
		:param request:  Flask request submitted for its creation
		"""
		hashtag = re.compile(r"#([^\s,.+=-]+)")
		usertag = re.compile(r"@([^\s,.+=-]+)")

		file = request.files["data_upload"]
		platform = dataset.parameters.get("platform")

		# this is a bit hacky, but sometimes we have multiple tools that can
		# all serve as input for the same datasource (e.g. CrowdTangle and
		# the DMI Instagram Scraper would both go to the 'instagram'
		# datasource), so just assume the datasource ID has no dashes in it
		# and ignore everything after a dash for the purposes of determining
		# what datasource to assign to the dataset
		datasource = platform.split("-")[0]
		dataset.type = "%s-search" % datasource
		dataset.datasource = datasource

		file.seek(0)
		done = 0

		encoding = sniff_encoding(file)

		# With validated csvs, save as is but make sure the raw file is sorted
		if platform == "instagram-crowdtangle":
			with dataset.get_results_path().open("w", encoding="utf-8", newline="") as output_csv:
				wrapped_upload = io.TextIOWrapper(file, encoding=encoding)
				reader = csv.DictReader(wrapped_upload)
				writer = csv.DictWriter(output_csv, fieldnames=(
					"id", "thread_id", "parent_id", "body", "author", "timestamp", "type", "url", "thumbnail_url",
					"hashtags", "usertags", "mentioned", "num_likes", "num_comments", "subject"))
				writer.writeheader()

				dataset.update_status("Sorting by date...")
				posts = sorted(reader, key=lambda x: x["Created"])

				dataset.update_status("Processing posts...")
				for item in posts:
					done += 1
					url = item["URL"]
					url = re.sub(r"/*$", "", url)

					id = url.split("/")[-1]
					caption = item["Description"]
					hashtags = hashtag.findall(caption)
					usertags = usertag.findall(caption)

					datestamp = " ".join(item["Created"].split(" ")[:-1])
					date = datetime.datetime.strptime(datestamp, "%Y-%m-%d %H:%M:%S")

					writer.writerow({
						"id": id,
						"thread_id": id,
						"parent_id": id,
						"body": caption if caption is not None else "",
						"author": item["User Name"],
						"timestamp": int(date.timestamp()),
						"type": "picture" if item["Type"] == "Photo" else item["Type"].lower(),
						"url": item["URL"],
						"thumbnail_url": item["Photo"],
						"hashtags": ",".join(hashtags),
						"usertags": ",".join(usertags),
						"mentioned": "",
						"num_likes": item["Likes"],
						"num_comments": item["Comments"],
						"subject": item["Title"]}
					)

		elif platform == "facebook-crowdtangle":
			with dataset.get_results_path().open("w", encoding="utf-8", newline="") as output_csv:
				wrapped_upload = io.TextIOWrapper(file, encoding=encoding)
				reader = csv.DictReader(wrapped_upload)

				entity_name = "Page Name" if "Page Name" in reader.fieldnames else "Group Name"

				writer = csv.DictWriter(output_csv, fieldnames=(
					"id", "thread_id", "body", "author", "timestamp", "page_id", "page_name", "page_likes",
					"page_followers", "page_shared_from", "type", "interactions", "likes", "comments", "shares",
					"likes_love", "likes_wow", "likes_haha", "likes_sad", "likes_angry", "likes_care", "views_post",
					"views_total", "views_total_crossposts", "video_length", "video_status", "url", "url_original",
					"body_image", "body_link", "body_description", "hashtags", "sponsor_id", "sponsor_name"))
				writer.writeheader()

				dataset.update_status("Sorting by date...")
				posts = sorted(reader, key=lambda x: x["Created"])

				dataset.update_status("Processing posts...")
				for item in posts:
					done += 1
					hashtags = hashtag.findall(item["Message"])

					date = datetime.datetime.strptime(" ".join(item["Created"].split(" ")[:2]), "%Y-%m-%d %H:%M:%S")

					is_from_elsewhere = item["Link"].find("https://www.facebook.com/" + item["User Name"]) < 0
					shared_page = item["Link"].split("/")[3] if is_from_elsewhere and item["Link"].find("https://www.facebook.com/") == 0 else ""

					writer.writerow({
						"id": item["URL"].split("/")[-1],
						"thread_id": item["URL"].split("/")[-1],
						"body": item["Message"],
						"author": item["User Name"],
						"timestamp": int(date.timestamp()),
						"page_name": item[entity_name],
						"page_likes": item["Likes at Posting"],
						"page_id": item["Facebook Id"],
						"page_followers": item["Followers at Posting"],
						"page_shared_from": shared_page,
						"type": item["Type"],
						"interactions": int(re.sub(r"[^0-9]", "", item["Total Interactions"])) if item["Total Interactions"] else 0,
						"comments": item["Comments"],
						"shares": item["Shares"],
						"likes": item["Likes"],
						"likes_love": item["Love"],
						"likes_wow": item["Wow"],
						"likes_haha": item["Haha"],
						"likes_sad": item["Sad"],
						"likes_angry": item["Angry"],
						"likes_care": item["Care"],
						"views_post": item["Post Views"],
						"views_total": item["Total Views"],
						"views_total_crossposts": item["Total Views For All Crossposts"],
						"video_length": "" if item["Video Length"] == "N/A" else item["Video Length"],
						"video_status": item["Video Share Status"],
						"url": item["URL"],
						"hashtags": ",".join(hashtags),
						"url_original": item["Link"],
						"body_image": item["Image Text"],
						"body_link": item["Link Text"],
						"body_description": item["Description"],
						"sponsor_id": item["Sponsor Id"],
						"sponsor_name": item["Sponsor Name"]
					})

		elif platform == "instagram-dmi-scraper":
			# in principe, this csv file should be good to go
			# however, we still need to know how many rows are in it, so we
			# nevertheless copy it line by line rather than in one go
			# as a bonus this also ensures it uses the right csv dialect
			with dataset.get_results_path().open("w", encoding="utf-8") as output_csv:
				wrapped_upload = io.TextIOWrapper(file, encoding=encoding)
				reader = csv.DictReader(wrapped_upload)
				writer = csv.DictWriter(output_csv, fieldnames=reader.fieldnames)
				writer.writeheader()
				for row in reader:
					done += 1
					writer.writerow(row)

		elif platform == "tiktok":
			with dataset.get_results_path().open("w", encoding="utf-8", newline="") as output_csv:
				wrapped_upload = io.TextIOWrapper(file, encoding=encoding)
				reader = csv.DictReader(wrapped_upload)
				writer = csv.DictWriter(output_csv, fieldnames=("id", "thread_id", "author", "subject", "body",
					"timestamp", "is_harmful", "is_duet", "music_name", "music_id", "music_author", "video_url",
					"tiktok_url", "thumbnail_url", "amount_likes", "amount_comments", "amount_shares", "amount_plays",
					"hashtags"))
				writer.writeheader()


				dataset.update_status("Sorting by date...")
				posts = sorted(reader, key=lambda x: x["createTime"])

				dataset.update_status("Processing posts...")
				for item in posts:
					hashtags = json.loads(item["hashtags"])
					hashtags = [hashtag["name"] for hashtag in hashtags]

					done += 1

					writer.writerow({
						"id": item["id"],
						"thread_id": item["id"],
						"author": item["authorMeta.name"],
						"subject": "",
						"body": item["text"],
						"timestamp": int(item["createTime"]),
						"is_harmful": -1,
						"is_duet": -1,
						"music_name": item["musicMeta.musicName"],
						"music_id": item["musicMeta.musicId"],
						"music_author": item["musicMeta.musicAuthor"],
						"video_url": item["videoUrl"],
						"tiktok_url": "https://tiktok.com/@%s/video/%s" % (item["authorMeta.id"], item["id"]),
						"thumbnail_url": item["covers.default"],
						"amount_likes": item["diggCount"],
						"amount_comments": item["commentCount"],
						"amount_shares": item["shareCount"],
						"amount_plays": item["playCount"],
						"hashtags": ",".join(hashtags),
					})

		elif platform == "facepager":
			with dataset.get_results_path().open("w", encoding="utf-8", newline="") as output_csv:
				wrapped_upload = io.TextIOWrapper(file, encoding=encoding)
				reader = csv.DictReader(wrapped_upload)
				writer = csv.DictWriter(output_csv, fieldnames=("id", "thread_id", "author", "subject", "body",
					"timestamp", "is_harmful", "is_duet", "music_name", "music_id", "music_author", "video_url",
					"tiktok_url", "thumbnail_url", "amount_likes", "amount_comments", "amount_shares", "amount_plays",
					"hashtags"))
				writer.writeheader()


				dataset.update_status("Sorting by date...")
				posts = sorted(reader, key=lambda x: x["createTime"])

				dataset.update_status("Processing posts...")
				for item in posts:
					hashtags = json.loads(item["hashtags"])
					hashtags = [hashtag["name"] for hashtag in hashtags]

					done += 1

					writer.writerow({
						"id": item["id"],
						"thread_id": item["id"],
						"author": item["authorMeta.name"],
						"subject": "",
						"body": item["text"],
						"timestamp": int(item["createTime"]),
						"is_harmful": -1,
						"is_duet": -1,
						"music_name": item["musicMeta.musicName"],
						"music_id": item["musicMeta.musicId"],
						"music_author": item["musicMeta.musicAuthor"],
						"video_url": item["videoUrl"],
						"tiktok_url": "https://tiktok.com/@%s/video/%s" % (item["authorMeta.id"], item["id"]),
						"thumbnail_url": item["covers.default"],
						"amount_likes": item["diggCount"],
						"amount_comments": item["commentCount"],
						"amount_shares": item["shareCount"],
						"amount_plays": item["playCount"],
						"hashtags": ",".join(hashtags),
					})


		file.close()

		dataset.finish(done)
		dataset.update_status("Result processed")
		dataset.update_version(get_software_version())
