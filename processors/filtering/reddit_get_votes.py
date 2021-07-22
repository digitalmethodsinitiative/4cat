"""
Update vote data for Reddit datasets
"""
import shutil
import praw, praw.exceptions
import csv

from prawcore.exceptions import Forbidden

from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException

import config

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)

class RedditVoteChecker(BasicProcessor):
	"""
	Update voting information for Reddit data
	"""
	type = "get-reddit-votes"  # job type ID
	category = "Filtering" # category
	title = "Update Reddit post scores"  # title displayed in UI
	description = "Updates the scores for each post to more accurately reflect the real score. Can only be used on datasets with < 5,000 posts due to the heavy usage of the API this requires."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor if dataset is a Reddit dataset

		:param module: Dataset or processor to determine compatibility with
		"""
		if module.is_dataset():
			return module.is_top_dataset() and module.type == "reddit-search" and module.num_rows <= 5000
		return False

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

		# get thread IDs
		# We're assuming here that there are multiple posts per thread. Hence,
		# querying full threads and then retaining relevant posts is cheaper
		# than querying individual posts, so we first gather all thread IDs to
		# query.
		thread_ids = set()
		for post in self.iterate_items(self.source_file):
			thread_ids.add(post["thread_id"])

		post_scores = {}
		thread_scores = {}

		processed = 0
		self.dataset.update_status("Retrieving scores via Reddit API")
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
			except Forbidden:
				self.dataset.update_status("Got error 403 while getting data from Reddit. Reddit may have blocked 4CAT.", is_final=True)
				self.dataset.finish(0)
				return

			processed += 1
			if processed % 100 == 0:
				self.dataset.update_status("Retrieved scores for %i threads" % processed)

		# now write a new CSV with the updated scores
		# get field names
		fieldnames = [*self.get_item_keys(self.source_file)]
		if "score" not in fieldnames:
			fieldnames.append("score")

		self.dataset.update_status("Writing results to file")
		with self.dataset.get_results_path().open("w") as output:
			writer = csv.DictWriter(output, fieldnames=fieldnames)
			writer.writeheader()
			processed = 0

			for post in self.iterate_items(self.source_file):
				# threads may be included too, so store the right score
				if post["thread_id"] == post["id"]:
					post["score"] = thread_scores[post["thread_id"]]
				else:
					post["score"] = post_scores.get(post["id"], post["score"])

				writer.writerow(post)
				processed += 1

		# now comes the big trick - replace original dataset with updated one
		shutil.move(self.dataset.get_results_path(), self.source_dataset.get_results_path())

		self.dataset.update_status("Parent dataset updated.")
		self.dataset.finish(processed)