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
from backend.lib.helpers import get_software_version, strip_tags


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

		file = request.files["data_upload"]
		if not file:
			raise QueryParametersException("No file was offered for upload.")

		encoding = SearchCustom.sniff_encoding(file)

		wrapped_file = io.TextIOWrapper(file, encoding=encoding)
		sample = wrapped_file.read(2048)
		wrapped_file.seek(0)
		dialect = csv.Sniffer().sniff(sample)

		# With validated csvs, save as is but make sure the raw file is sorted
		reader = csv.DictReader(wrapped_file, dialect=dialect)

		try:
			fields = reader.fieldnames
		except UnicodeDecodeError:
			raise QueryParametersException("Uploaded file is not a well-formed CSV or TAB file.")

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

		wrapped_file.detach()

		# Whether to strip the HTML tags
		strip_html = False
		if query.get("strip_html"):
			strip_html = True

		# return metadata - the filename is sanitised and serves no purpose at
		# this point in time, but can be used to uniquely identify a dataset
		disallowed_characters = re.compile(r"[^a-zA-Z0-9._+-]")
		return {"filename": disallowed_characters.sub("", file.filename), "time": time.time(), "datasource": "custom", "board": "upload", "strip_html": strip_html}

	def after_create(query, dataset, request):
		"""
		Hook to execute after the dataset for this source has been created

		In this case, it is used to save the uploaded file to the dataset's
		result path, and finalise the dataset metadata.

		:param dict query:  Sanitised query parameters
		:param DataSet dataset:  Dataset created for this query
		:param request:  Flask request submitted for its creation
		"""

		strip_html = query.get("strip_html")

		file = request.files["data_upload"]

		file.seek(0)

		# detect encoding - UTF-8 with or without BOM
		encoding = SearchCustom.sniff_encoding(file)

		wrapped_file = io.TextIOWrapper(file, encoding=encoding)
		sample = wrapped_file.read(2048)
		wrapped_file.seek(0)
		dialect = csv.Sniffer().sniff(sample)

		# With validated csvs, save as is but make sure the raw file is sorted
		reader = csv.DictReader(wrapped_file, dialect=dialect)
		with dataset.get_results_path().open("w", encoding="utf-8", newline="") as output_csv:
			# Sort by timestamp
			dataset.update_status("Sorting file by date")
			sorted_reader = sorted(reader, key=lambda row:row["timestamp"] if isinstance(row["timestamp"], str) else "")

			dataset.update_status("Writing to file")
			writer = csv.DictWriter(output_csv, fieldnames=reader.fieldnames)
			writer.writeheader()
			for row in sorted_reader:
				if strip_html:
					row["body"] = strip_tags(row["body"])
				writer.writerow(row)

		file.close()
		wrapped_file.detach()

		with dataset.get_results_path().open(encoding="utf-8") as input:
			if file.filename.endswith(".tab"):
				reader = csv.DictReader(input, delimiter="\t", quoting=csv.QUOTE_NONE)
			else:
				reader = csv.DictReader(input)

			dataset.finish(sum(1 for line in reader))
			dataset.update_status("Result processed")

		dataset.update_version(get_software_version())

	def sniff_encoding(file):
		"""
		Determine encoding from raw file bytes

		Currently only distinguishes UTF-8 and UTF-8 with BOM

		:param FileStorage file:
		:return:
		"""
		buffer = file.getbuffer()
		maybe_bom = buffer[:3].tobytes()
		return "utf-8-sig" if maybe_bom == b"\xef\xbb\xbf" else "utf-8"