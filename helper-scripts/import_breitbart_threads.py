"""
Utility script to convert threads from breitbart-scraper's format to 4CAT data
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/../..")

from backend.lib.database import Database
from backend.lib.logger import Logger

log = Logger(output=True)
db = Database(logger=log)

articles = db.fetchall("SELECT * FROM breitbart_articles WHERE comments_scraped > 0 AND priority = 1")
exists = {row["id"] for row in db.fetchall("SELECT id FROM threads_breitbart")}

for article in articles:
	print("Article: %s" % article["subject"], end="")
	thread_id = article["id"]
	if thread_id in exists:
		print("... exists")
		continue
	else:
		print("\n")

	db.insert("posts_breitbart", data={
		"id": article["id"],
		"thread_id": article["id"],
		"subject": article["subject"],
		"body": article["body"],
		"timestamp": article["timestamp"],
		"author": article["author"],
		"author_location": "",
		"author_name": article["author"],
		"likes": 0,
		"dislikes": 0,
		"reply_to": 0
	}, commit=False)

	db.insert("threads_breitbart", data={
		"id": article["id"],
		"timestamp": article["timestamp"],
		"timestamp_scraped": article["page_scraped"],
		"post_amount": article["num_comments"],
		"url": article["url"],
		"section": article["section"],
		"tags": article["tags"],
		"disqus_id": article["disqus_id"]
	}, commit=False)

	exists.add(article["id"])

print("Committing...")
db.commit()

print("Done")