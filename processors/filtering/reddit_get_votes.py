"""
Update vote data for Reddit datasets
"""
import shutil
import praw, praw.exceptions
import csv

from prawcore.exceptions import Forbidden, NotFound

from backend.abstract.processor import BasicProcessor
from common.lib.user_input import UserInput
from common.lib.exceptions import ProcessorInterruptedException

import common.config_manager as config
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
	title = "Update Reddit scores"  # title displayed in UI
	description = "Updates the scores for each post and comment to more accurately reflect the real score. Can only be used on datasets with < 5,000 posts due to the heavy usage of the Reddit API."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	config = {
	# Reddit API keys
		'api.reddit.client_id': {
			'type': UserInput.OPTION_TEXT,
			'default' : "",
			'help': 'Reddit API Client ID',
			'tooltip': "",
			},
		'api.reddit.secret': {
			'type': UserInput.OPTION_TEXT,
			'default' : "",
			'help': 'Reddit API Secret',
			'tooltip': "",
			},
		}

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
			reddit = praw.Reddit(client_id=config.get('api.reddit.client_id'),
							 client_secret=config.get('api.reddit.secret'),
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
		for post in self.source_dataset.iterate_items(self):
			thread_ids.add(post["thread_id"])

		post_scores = {}
		thread_scores = {}

		processed = 0
		failed = 0
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
			except NotFound:
				self.dataset.log("Thread %s no longer exists (404), skipping" % thread_id)
				failed += 1

			processed += 1
			self.dataset.update_status("Retrieved updated scores for %i/%i threads" % (processed, len(thread_ids)))
			self.dataset.update_progress(processed / len(thread_ids))

		# now write a new CSV with the updated scores
		# get field names
		fieldnames = [*self.source_dataset.get_item_keys(self)]
		if "score" not in fieldnames:
			fieldnames.append("score")

		self.dataset.update_status("Writing results to file")
		with self.dataset.get_results_path().open("w") as output:
			writer = csv.DictWriter(output, fieldnames=fieldnames)
			writer.writeheader()
			processed = 0

			for post in self.source_dataset.iterate_items(self):
				# threads may be included too, so store the right score
				if post["thread_id"] == post["id"] and post["thread_id"] in thread_scores:
					post["score"] = thread_scores[post["thread_id"]]
				elif post["id"] in post_scores:
					post["score"] = post_scores[post["id"]]
				else:
					failed += 1
					self.dataset.log("Post %s no longer exists, skipping" % post["id"])

				writer.writerow(post)
				processed += 1

		# now comes the big trick - replace original dataset with updated one
		shutil.move(self.dataset.get_results_path(), self.source_dataset.get_results_path())

		if failed > 0:
			self.dataset.update_status("Scores retrieved and dataset updated, but unable to find new scores for some "
									   "deleted posts. Check the dataset log for details.", is_final=True)
		else:
			self.dataset.update_status("Scores retrieved, parent dataset updated.")

		self.dataset.finish(processed)
