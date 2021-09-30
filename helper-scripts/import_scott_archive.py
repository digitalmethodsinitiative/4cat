"""
Script to import old 2006-2008 4chan/b/ threads from the Jason Scott archive.
This archive is downloadble here: https://archive.org/details/4chan_threads_archive_10_billion

Most of the data seems corrupted, but you can extract a few millions HTML files.
These will be converted into a 4CAT dataset with this script.

NOTE: The HTML files do not contain any time data or post IDs.
The thread IDs can be extracted from the file name. Therefore, this script interpolates the dates by using several known ID/time combinations for /b/. These data points are retrieved from Bibliotheca Anonoma's 4chan/History https://wiki.bibanon.org/4chan/History. See the dictionary below.
It also assigns post IDs by increasing the OP's ID with 1 for subsequent replies.
These are rough interpolations, not exact matches!

This script only works for the /b/ data in the archive; the date interpolation is based on activity on that board. 4CAT needs timestamps, so it will fail or assign wildly incorrect values for other boards.

"""

import argparse
import os
import glob
import time
import sys
import json
from bs4 import BeautifulSoup
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/..")
from common.lib.database import Database
from common.lib.logger import Logger

# parse parameters
cli = argparse.ArgumentParser()
cli.add_argument("-i", "--input", required=True, help="Folder containing the HTML files for /b/ threads.")
cli.add_argument("-s", "--skip_duplicates", type=str, required=True, help="If duplicate posts should be skipped (useful if there's already data in the table)")

args = cli.parse_args()

# Dictinonary of thread_ids that are known to be made at a certain date.
# We will use this to interpolate a missing timestamp.
# The last known thread ID is 100868695, so we need to make sure we have a data point after that.
known_timestamps = {
	"6000000": "2006-03-23", # 6M GET
	"7000000": "2006-04-20", # 7M GET
	"8000000": "2006-05-18", # 8M GET
	"10000000": "2006-07-07", # 10M GET
	"11473653": "2006-08-16", # Early Tom Green raids
	"12080322": "2006-08-23", # \"Bob Ross\" sticky (see https://imgur.com/6NHBE1k)
	"12451439": "2006-09-04", # Steve Irwin dies
	"13630584": "2006-10-01", # /b/’s third birthday
	"14567756": "2006-10-20", # Jake Brahm’s bomb threat
	"15494181": "2006-11-07", # 4chan goes down, admin post containing the words 'FIFTY BILLION YEARS'
	"17150979": "2006-11-30", # Technical announcements involving Adbrite banner ads
	"17262903": "2006-12-20", # Start of Hal Turner raids
	"18229843": "2006-12-31", # Hal Turner ‘surrenders’ with the words 'short of my physical presence on this planet'
	"18720601": "2007-01-09", # 'Interstitial ads' announcement by moot
	"22687013": "2007-03-21", # Bestiality pictures posted on /b/
	"23000000": "2007-03-26", # 23M GET
	"25574687": "2007-04-27", # moot announces Fortunes system, using #fortune as a name provides fortune advice.
	"25379623": "2007-04-28", # Subeta raids
	"27079435": "2007-05-13", # Thread length shortened, css changed so everything in the interface had the same color.
	"29000000": "2007-06-06", # 29M GET
	"30000000": "2007-06-16", # 30M GET
	"26143654": "2007-07-17", # Potterforums.com Raids
	"34178570": "2007-07-26", # Fox News coverage of 4chan, labels anons as “hackers on steroids”
	"39103157": "2007-09-11", # Trey Burba terrorism threat
	"41430052": "2007-10-01", # 4chan’s fourth birthday
	"43306011": "2007-10-19", # Lulznet IRC channel DDoSes /b/, moot responds with ‘whatever, Im gonna go make soup’
	"44454672": "2007-11-05", # EFG (Epic Fail Guy) Day raid
	"51390509": "2008-01-01", # Hal Turner revealed to be an FBI informant
	"54796186": "2008-02-19", # New boards added, including /toy/
	"58755694": "2008-03-18", # 4chan theme “Yotsuba Blue” added
	"68884172": "2008-05-22", # 2008 “Operation Jewtube”
	"73513787": "2008-06-18", # Boston meetup
	"74074166": "2008-06-25", # SOHH raids
	"76725105": "2008-07-10", # Spam posts of “Google &#21328”
	"77197588": "2008-07-13", # “Fuck you Google” and “Scientology is a cult” Google bombs
	"84575449": "2008-09-10", # Word filter inserted by moot, related to the Large Hadron Collider at CERN
	"85880267": "2008-09-16", # /b/-user David “Rubico” Kernel hacks Sarah Palin’s email
	"86000199": "2008-09-20", # Rubico revealed to be the son of State Representative Mike Kernell
	"88616277": "2008-10-01", # 4chan turns five years old
	"93174567": "2008-11-06", # Version of the 4chan.js JavaScript troll appears on /b/
	"99307803": "2008-11-27", # Another 4chan.js version, lol.js, appears on /b/
	"100000000": "2008-11-30", # 10M GET
	"107743745": "2009-01-07" #Boxxy post (see https://encyclopediadramatica.online/index.php?title=Boxxy#/media/File:Boxxy_in_4chan_1.png) 
}

if not os.path.isdir(args.input):
	print("%s is not a valid folder name." % args.input)
	sys.exit(1)

logger = Logger()
db = Database(logger=logger, appname="queue-dump")

# Already add thread IDs to seen ids, so we don't reuse them later.
print("Listing thread IDs from filenames")
seen_ids = set()
for f in os.listdir(args.input):
	seen_id = int(f.split(".")[0])
	seen_ids.add(seen_id)
print(len(seen_ids), "threads to process")

safe = False
if args.skip_duplicates:
	print("Skipping duplicate rows (ON CONFLICT DO NOTHING).")
	safe = True

threads = 0
posts = 0

for html_doc in glob.iglob(os.path.join(args.input, "*.*")):
	
	# Thread ID is absent in the HTML but is in the name of file.
	thread_id = int(os.path.basename(html_doc).split(".")[0])

	# Post IDs are absent, but for OPs, this is the same as the thread ID.
	post_id = thread_id

	# Skip low thread ID posts (buggy data: a file with `1` is included).
	if thread_id < 6000000:
		continue

	# Make the HTML traversable
	soup = BeautifulSoup(open(html_doc, "r", encoding="utf-8"), "html.parser")

	# Interpolate a date when a new thread is encountered
	# Get the upper and lower known IDs and timestamps.
	start_timestamp, start_id = [(int(datetime.strptime(v, "%Y-%m-%d").timestamp()), int(k)) for k, v in known_timestamps.items() if thread_id >= int(k)][-1]
	end_timestamp, end_id = [(int(datetime.strptime(v, "%Y-%m-%d").timestamp()), int(k)) for k, v in known_timestamps.items() if thread_id < int(k)][0]

	# First, interpolate the distance between the nearest two known thread ids/timestamps
	sec_distance = end_timestamp - start_timestamp

	# We get the position of this ID between the window as a percentage
	position = (thread_id - start_id) / (end_id - start_id)

	# Use this percentage to calculate the date between the window
	interpolated_timestamp = int(start_timestamp + (sec_distance * position))

	# Set thread data (or what little that's known of it)
	thread_id = str(thread_id)
	thread = {
		"id": thread_id,
		"board": "b",
		"timestamp": interpolated_timestamp,
		"timestamp_scraped": int(os.path.getmtime(html_doc)), # May 2009
		"timestamp_modified": interpolated_timestamp,
		"num_unique_ips": -1,
		"num_images": 0,
		"num_replies": 0,
		"limit_bump": False,
		"limit_image": False,
		"is_sticky": False,
		"is_closed": False,
		"post_last": interpolated_timestamp
	}

	
	# OP is not formatted as the rest, so process this first
	op_data = {
			"thread_id": thread_id,
			"id": post_id,
			"board": "b",
			"timestamp": interpolated_timestamp, # Same for entire thread
			"subject": "",
			"body": soup.find("blockquote").get_text("\n") if soup.find("blockquote") else "",
			"author": soup.find("span", {"class": "postername"}).get_text() if soup.find("span", {"class": "postername"}) else "",
			"author_type": "",
			"author_type_id": "N",
			"author_trip": "",
			"country_code": "",
			"country_name": "",
			"image_file": "",
			"image_url": "",
			"image_4chan": "",
			"image_md5": "",
			"image_dimensions": "",
			"image_filesize": 0,
			"semantic_url": "",
			"unsorted_data": json.dumps({"has_image": True if soup.find("span", {"class": "filesize"}) else False})
			}

	# Insert OP post into database
	db.insert("posts_4chan", op_data, commit=False, safe=safe)

	posts += 1

	# Loop through replies, if present
	for text in soup.find_all("td", {"class": "reply"}):

		# Post IDs are not present, so once again we have to guess.
		# These we simply interpolate by adding +1 after the thread ID (i.e. the OP's post ID)
		# We do need to make sure that these do not overwrite a known post ID.
		# Thus, we only assign a post ID if it didn't appear as a thread ID or as another post ID we already encountered.
		while True:
			post_id += 1
			if post_id not in seen_ids:
				seen_ids.add(post_id)
				break
		
		# The files only say *whether* an image was included, nothing more
		has_image = True if text.find("span", {"class": "filesize"}) in text else False

		# Edit some thread data
		thread["num_replies"] += 1
		thread["post_last"] = post_id
		if has_image:
			thread["num_images"] += 1
		
		post_data = {
		"thread_id": thread_id,
		"id": post_id,
		"board": "b",
		"timestamp": interpolated_timestamp, # Same for entire thread
		"subject": "",
		"body": text.blockquote.get_text("\n") if text.blockquote else "",
		"author": text.find("span", {"class": "postername"}).get_text() if text.find("span", {"class": "postername"}) else "",
		"author_type": "",
		"author_type_id": "N",
		"author_trip": "",
		"country_code": "",
		"country_name": "",
		"image_file": "",
		"image_url": "",
		"image_4chan": "",
		"image_md5": "",
		"image_dimensions": "",
		"image_filesize": 0,
		"semantic_url": "",
		"unsorted_data": json.dumps({"has_image": has_image})
		}

		# Insert into database
		db.insert("posts_4chan", post_data, commit=False, safe=safe)

		posts += 1

	db.upsert("threads_4chan", data=thread, commit=False, constraints=["id", "board"])

	threads += 1
		
	# Commit per 100 threads
	if threads > 0 and threads % 100 == 0:
		print("Committing threads %i - %i" % (threads - 100, threads))
		db.commit()

db.commit()
print("Done")