"""
Split results by thread
"""
import zipfile
import os
import time
import shutil

from csv import DictReader, DictWriter

import config
from backend.abstract.postprocessor import BasicPostProcessor


class ThreadSplitter(BasicPostProcessor):
	"""
	Create separate result files per thread

	Take a results file, and create separate result files per thread, each
	containing only the posts in that thread.
	"""
	type = "split-threads"  # job type ID
	category = "Splitting" # category
	title = "Split by thread"  # title displayed in UI
	description = "Split the result over separate csv files per thread. The threads can then be downloaded as an archive containing the separate CSV files."  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI
	datasources = ["4chan","8chan","reddit"]

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column with unique usernames and in the other one the amount
		of posts for that user name
		"""
		users = {}

		# prepare staging area
		dirname_base = self.query.get_results_path().replace(".", "") + "-threads"
		dirname = dirname_base
		index = 1
		while os.path.exists(dirname):
			dirname = dirname_base + "-" + str(index)
			index += 1

		# create temporary folder
		os.mkdir(dirname)

		# read and write
		threadfiles = []
		self.query.update_status("Creating thread files")
		with open(self.source_file, encoding="utf-8") as source:
			csv = DictReader(source)
			for post in csv:
				thread = dirname + '/' + post["thread_id"] + ".csv"
				new = not os.path.exists(thread)

				with open(thread, "a", encoding="utf-8") as output:
					outputcsv = DictWriter(output, fieldnames=post.keys())

					if new:
						outputcsv.writeheader()
						threadfiles.append(thread)

					outputcsv.writerow(post)

		self.query.update_status("Writing results to archive")
		with zipfile.ZipFile(self.query.get_results_path(), "w") as zip:
			for threadfile in threadfiles:
				zip.write(threadfile)
				os.unlink(threadfile)

		# remove temporary folder
		shutil.rmtree(dirname)

		self.query.update_status("Finished")
		self.query.finish(len(threadfiles))