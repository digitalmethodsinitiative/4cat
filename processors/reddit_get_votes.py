"""
Update vote data for Reddit datasets
"""
import shutil
import praw, praw.exceptions
import csv

from backend.abstract.processor import BasicProcessor
from backend.lib.exceptions import ProcessorInterruptedException

import config

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

class RedditVoteChecker(BasicProcessor):
	"""
	Update voting information for Reddit data
	"""
	type = "get-reddit-votes"  # job type ID
	category = "Conversion" # category
	title = "Update Reddit post scores"  # title displayed in UI
	description = "Updates the scores for each post to more accurately reflect the real score. Can only be used on datasets with < 5,000 posts due to the heavy usage of the API this requires."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	datasource = ["reddit"]

	input = "csv:body"
	output = "csv"

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a plain text file
		containing all post bodies as one continuous string, sanitized.
		"""
		try:
			user_agent = "4cat:4cat:v1.0 (by /u/oilab-4cat)"
			reddit = praw.Reddit(client_id=config.REDDIT_API_CLIENTID,
							 client_secret=config.REDDIT_API_SECRET,
							 user_agent=user_agent)
		except praw.exceptions.PRAWException:
			# unclear what kind of expression gets thrown here
			self.dataset.update_status("Could not connect to Reddit. 4CAT may be configured wrong.")
			self.dataset.finish(0)
			return

		# reddit has rate limits and it's easy to pass them, so limit this
		# processor to smaller datasets
		if self.dataset.get_genealogy()[0].num_rows > 5000:
			self.dataset.update_status("Reddit score updating is only available for datasets smaller than 5.000 items.")
			self.dataset.finish(0)
			return

		# get thread IDs
		# We're assuming here that there are multiple posts per thread. Hence,
		# querying full threads and then retaining relevant posts is cheaper
		# than querying individual posts, so we first gather all thread IDs to
		# query.
		thread_ids = set()
		for post in self.iterate_csv_items(self.source_file):
			thread_ids.add(post["thread_id"])

		post_scores = {}
		thread_scores = {}

		processed = 0
		for thread_id in thread_ids:
			if self.interrupted:
				raise ProcessorInterruptedException("Halted while querying thread data from Reddit")

			# get info for all comments in the thread
			try:
				thread = reddit.submission(id=thread_id)
				thread.comments.replace_more(limit=None)
				thread_scores[thread.id] = thread.score

				for comment in thread.comments.list():
					post_scores[comment.id] = comment.score
			except praw.exceptions.PRAWException:
				self.dataset.update_status("Error while communicating with Reddit.")
				self.dataset.finish(0)
				return

			processed += 1
			if processed % 100 == 0:
				self.dataset.update_status("Retrieved scores for %i threads" % processed)

		# now write a new CSV with the updated scores
		# get field names
		with self.source_file.open() as input:
			reader = csv.DictReader(input)
			fieldnames = reader.fieldnames


		self.dataset.update_status("Writing results to file")
		with self.dataset.get_results_path().open("w") as output:
			writer = csv.DictWriter(output, fieldnames=fieldnames)
			writer.writeheader()
			processed = 0

			for post in self.iterate_csv_items(self.source_file):
				# threads may be included too, so store the right score
				if post["thread_id"] == post["id"]:
					post["score"] = thread_scores[post["thread_id"]]
				else:
					post["score"] = post_scores[post["id"]]

				writer.writerow(post)
				processed += 1

		# now comes the big trick - replace original dataset with updated one
		parent = self.dataset.genealogy[0]
		shutil.move(self.dataset.get_results_path(), parent.get_results_path())

		self.dataset.update_status("Parent dataset updated.")
		self.dataset.finish(-1)