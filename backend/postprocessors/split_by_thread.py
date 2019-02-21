"""
Split results by thread
"""
import zipfile
import os
import time

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

		os.mkdir(dirname)
		os.chdir(dirname)

		# read and write
		threadfiles = []
		self.query.update_status("Creating thread files")
		with open(self.source_file, encoding='utf-8') as source:
			csv = DictReader(source)
			for post in csv:
				thread = post["thread_id"]
				new = not os.path.exists(thread + ".csv")

				with open(thread + ".csv", "a") as output:
					outputcsv = DictWriter(output, fieldnames=post.keys())
					if new:
						outputcsv.writeheader()
						threadfiles.append(output.name)

					outputcsv.writerow(post)

		self.query.update_status("Writing results to archive")
		with zipfile.ZipFile(self.query.get_results_path(), "w") as zip:
			for threadfile in threadfiles:
				zip.write(threadfile)
				os.unlink(threadfile)

		os.rmdir(dirname)

		self.query.update_status("Finished")
		self.query.finish(len(threadfiles))