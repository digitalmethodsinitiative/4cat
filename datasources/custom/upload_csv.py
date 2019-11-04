"""
Custom data upload to create bespoke datasets
"""
import datetime
import time
import csv
import re
import io

from backend.abstract.worker import BasicWorker
from backend.lib.exceptions import QueryParametersException
from backend.lib.helpers import get_software_version


class SearchCustom(BasicWorker):
	type = "custom-search"  # job ID
	category = "Search"  # category
	title = "Custom Dataset Upload"  # title displayed in UI
	description = "Upload your own CSV file to be used as a dataset"  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	# not available as a processor for existing datasets
	accepts = [None]

	max_workers = 1

	def work(self):
		"""
		Run custom search

		All work is done while uploading the data, so this just has to 'finish'
		the job.
		"""
		self.job.finish()

	def validate_query(query, request):
		"""
		Validate custom data input

		Confirms that the uploaded file is a valid CSV file and, if so, returns
		some metadata.

		:param dict query:  Query parameters, from client-side.
		:param request:  Flask request
		:return dict:  Safe query parameters
		"""
		# do we have an uploaded file?
		if "data_upload" not in request.files:
			raise QueryParametersException("No file was offered for upload.")

		file = request.files["data_upload"]
		if not file:
			raise QueryParametersException("No file was offered for upload.")

		# validate file as CSV
		wrapped_upload = io.TextIOWrapper(file)
		reader = csv.DictReader(wrapped_upload)
		try:
			fields = reader.fieldnames
		except UnicodeDecodeError:
			raise QueryParametersException("Uploaded file is not a well-formed CSV file.")

		# check if all required fields are present
		required = ("id", "thread_id", "subject", "author", "body", "timestamp")
		missing = []
		for field in required:
			if field not in reader.fieldnames:
				missing.append(field)

		if missing:
			raise QueryParametersException(
				"The following required columns are not present in the csv file: %s" % ", ".join(missing))

		try:
			row = reader.__next__()
			try:
				datetime.datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
			except ValueError:
				raise QueryParametersException("Your 'timestamp' column does not have the required format (YYY-MM-DD hh:mm:ss)")
		except StopIteration:
			pass

		wrapped_upload.detach()

		# return metadata - the filename is sanitised and serves no purpose at
		# this point in time, but can be used to uniquely identify a dataset
		disallowed_characters = re.compile(r"[^a-zA-Z0-9._+-]")
		return {"filename": disallowed_characters.sub("", file.filename), "time": time.time(), "datasource": "custom", "board": "upload"}

	def after_create(query, dataset, request):
		"""
		Hook to execute after the dataset for this source has been created

		In this case, it is used to save the uploaded file to the dataset's
		result path, and finalise the dataset metadata.

		:param dict query:  Sanitised query parameters
		:param DataSet dataset:  Dataset created for this query
		:param request:  Flask request submitted for its creation
		"""
		file = request.files["data_upload"]
		file.seek(0)
		file.save(dataset.get_results_path().open("wb"))
		file.close()

		with dataset.get_results_path().open() as input:
			reader = csv.DictReader(input)
			dataset.finish(sum(1 for line in reader))
			dataset.update_status("Result processed")

		dataset.update_version(get_software_version())
