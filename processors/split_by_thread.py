"""
Split results by thread
"""
import zipfile
import shutil

from csv import DictReader, DictWriter

from backend.abstract.processor import BasicProcessor


class ThreadSplitter(BasicProcessor):
	"""
	Create separate result files per thread

	Take a results file, and create separate result files per thread, each
	containing only the posts in that thread.
	"""
	type = "split-threads"  # job type ID
	category = "Conversion" # category
	title = "Split by thread"  # title displayed in UI
	description = "Split the result over separate csv files per thread. The threads can then be downloaded as an archive containing the separate CSV files."  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI
	datasources = ["4chan","8chan","reddit","breitbart"]

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column with unique usernames and in the other one the amount
		of posts for that user name
		"""
		users = {}

		# prepare staging area
		results_path = self.dataset.get_temporary_path()
		results_path.mkdir()

		# read and write
		threadfiles = []
		self.dataset.update_status("Creating thread files")
		with self.source_file.open(encoding="utf-8") as source:
			csv = DictReader(source)
			for post in csv:
				thread = results_path.joinpath(post["thread_id"] + ".csv")
				new = not thread.exists()

				with thread.open("a", encoding="utf-8") as output:
					outputcsv = DictWriter(output, fieldnames=post.keys())

					if new:
						outputcsv.writeheader()
						threadfiles.append(thread)

					outputcsv.writerow(post)

		self.dataset.update_status("Writing results to archive")
		with zipfile.ZipFile(self.dataset.get_results_path(), "w") as zip:
			for threadfile in threadfiles:
				zip.write(threadfile)
				threadfile.unlink()

		# remove temporary folder
		shutil.rmtree(results_path)

		self.dataset.update_status("Finished")
		self.dataset.finish(len(threadfiles))