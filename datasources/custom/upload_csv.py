"""
Custom data upload to create bespoke datasets
"""
import time
import csv
import re
import io

from dateutil.parser import parse as parse_datetime
from datetime import datetime

from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import QueryParametersException, QueryNeedsFurtherInputException
from common.lib.helpers import strip_tags, sniff_encoding, UserInput


class SearchCustom(BasicProcessor):
	type = "custom-search"  # job ID
	category = "Search"  # category
	title = "Custom Dataset Upload"  # title displayed in UI
	description = "Upload your own CSV file to be used as a dataset"  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI
	is_local = False  # Whether this datasource is locally scraped
	is_static = False  # Whether this datasource is still updated

	max_workers = 1
	options = {
		"intro": {
			"type": UserInput.OPTION_INFO,
			"help": "You can upload a CSV or TAB file here that, after upload, will be available for further analysis "
					"and processing. Files need to be [UTF-8](https://en.wikipedia.org/wiki/UTF-8)-encoded and must "
					"contain a header row. For each item, columns describing its ID, author, timestamp, and content are "
					"expected. You can select which column holds which value after uploading the file."
		},
		"data_upload": {
			"type": UserInput.OPTION_FILE,
			"help": "File"
		},
		"strip_html": {
			"type": UserInput.OPTION_TOGGLE,
			"help": "Strip HTML?",
			"default": False,
			"tooltip": "Removes HTML tags from the column identified as containing the item content ('body' by default)"
		}
	}

	# these columns need to be present or mapped to when uploading a csv file
	required_columns = {
		"id": "A value that uniquely identifies the item, like a numerical ID.",
		"thread_id": "A value that uniquely identifies the sub-collection an item is a part of, e.g. a forum thread. If this does not apply to your dataset you can use the same value as for 'id' here.",
		"author": "A value that identifies the author of the item. If the option to pseudonymise data is selected below, this field will be pseudonymised.",
		"body": "The 'content' of the item, e.g. a post's text.",
		"timestamp": "The time the item was made or posted. 4CAT will try to interpret this value, but for the best results use YYYY-MM-DD HH:MM:SS notation."
	}

	def process(self):
		"""
		Process uploaded CSV file

		Applies the provided mapping and makes sure the file is in a format
		4CAT will understand.
		"""
		temp_file = self.dataset.get_results_path().with_suffix(".importing")
		with temp_file.open("rb") as infile:
			# detect encoding - UTF-8 with or without BOM
			encoding = sniff_encoding(infile)

		infile = temp_file.open("r", encoding=encoding)
		sample = infile.read(1024 * 1024)
		dialect = csv.Sniffer().sniff(sample, delimiters=(",", ";", "\t"))

		# With validated csvs, save as is but make sure the raw file is sorted
		infile.seek(0)
		reader = csv.DictReader(infile, dialect=dialect)
		items = 0
		skipped = 0

		# figure out what the columns in the imported csv will be
		fieldnames = list(self.required_columns) + [field for field in reader.fieldnames if field not in self.required_columns]
		if "unix_timestamp" not in fieldnames:
			fieldnames.append("unix_timestamp")

		# write to the result file
		with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as output_csv:
			writer = csv.DictWriter(output_csv, fieldnames=fieldnames)
			writer.writeheader()
			for row in reader:
				for field in self.required_columns:
					mapping = self.parameters.get("mapping-" + field)
					if mapping and mapping != field:
						row[field] = row[mapping]

				# ensure that timestamp is YYYY-MM-DD HH:MM:SS and that there
				# is a unix timestamp. this will override the columns if they
				# already exist! but it is necessary for 4CAT to handle the
				# data in processors etc and should be an equivalent value.
				try:
					if row["timestamp"].isdecimal():
						timestamp = datetime.fromtimestamp(float(row["timestamp"]))
					else:
						timestamp = parse_datetime(row["timestamp"])

					row["timestamp"] = timestamp.strftime("%Y-%m-%d %H:%M:%S")
					row["unix_timestamp"] = int(timestamp.timestamp())

				except ValueError:
					# skip rows without a valid timestamp - this may happen
					# despite validation because only a sample is validated
					skipped += 1
					continue

				if self.parameters.get("strip_html"):
					row["body"] = strip_tags(row["body"])

				writer.writerow(row)
				items += 1

		infile.close()
		if skipped:
			self.dataset.update_status(
				"CSV file imported, but %i items were skipped because their date could not be parsed." % skipped,
				is_final=True)

		temp_file.unlink()
		self.dataset.finish(items)

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
		if "option-data_upload" not in request.files:
			raise QueryParametersException("No file was offered for upload.")

		file = request.files["option-data_upload"]
		if not file:
			raise QueryParametersException("No file was offered for upload.")

		encoding = sniff_encoding(file)

		wrapped_file = io.TextIOWrapper(file, encoding=encoding)
		sample = wrapped_file.read(1024 * 1024)
		wrapped_file.seek(0)
		dialect = csv.Sniffer().sniff(sample, delimiters=(",", ";", "\t"))

		# With validated csvs, save as is but make sure the raw file is sorted
		reader = csv.DictReader(wrapped_file, dialect=dialect)

		# we know that the CSV file is a CSV file now, next verify whether
		# we know what each column means
		try:
			fields = reader.fieldnames
		except UnicodeDecodeError:
			raise QueryParametersException("Uploaded file is not a well-formed CSV or TAB file.")

		incomplete_mapping = list(SearchCustom.required_columns.keys())
		for field in SearchCustom.required_columns:
			if request.form.get("option-mapping-%s" % field):
				incomplete_mapping.remove(field)

		# offer the user a number of select boxes where they can indicate the
		# mapping for each column
		if incomplete_mapping:
			raise QueryNeedsFurtherInputException({
				"mapping-info": {
					"type": UserInput.OPTION_INFO,
					"help": "Please confirm which column in the CSV file maps to each required value."
				},
				**{
					"mapping-%s" % mappable_column: {
						"type": UserInput.OPTION_CHOICE,
						"options": {
							"": "",
							**{column: column for column in fields}
						},
						"default": mappable_column if mappable_column in fields else "",
						"help": mappable_column,
						"tooltip": SearchCustom.required_columns[mappable_column]
					} for mappable_column in incomplete_mapping
				}})

		# the mappings do need to point to a column in the csv file
		missing_mapping = []
		column_mapping = {}
		for field in SearchCustom.required_columns:
			mapping_field = "option-mapping-%s" % field
			if request.form.get(mapping_field) not in fields or not request.form.get(mapping_field):
				missing_mapping.append(field)
			else:
				column_mapping["mapping-" + field] = request.form.get(mapping_field)

		if missing_mapping:
			raise QueryParametersException(
				"You need to indicate which column in the CSV file holds the corresponding value for the following columns: %s" % ", ".join(
					missing_mapping))

		# the timestamp column needs to be parseable
		timestamp_column = request.form.get("mapping-timestamp")
		try:
			row = reader.__next__()
			if timestamp_column not in row:
				# incomplete row because we are analysing a sample
				# stop parsing because no complete rows will follow
				raise StopIteration

			try:

				if row["timestamp"].isdecimal():
					datetime.fromtimestamp(float(row[timestamp_column]))
				else:
					parse_datetime(row[timestamp_column])
			except ValueError:
				raise QueryParametersException(
					"Your 'timestamp' column does not use a recognisable format (yyyy-mm-dd hh:mm:ss is recommended)")

		except StopIteration:
			pass

		# ok, we're done with the file
		wrapped_file.detach()

		# Whether to strip the HTML tags
		strip_html = False
		if query.get("strip_html"):
			strip_html = True

		# return metadata - the filename is sanitised and serves no purpose at
		# this point in time, but can be used to uniquely identify a dataset
		disallowed_characters = re.compile(r"[^a-zA-Z0-9._+-]")
		return {
			"filename": disallowed_characters.sub("", file.filename),
			"time": time.time(),
			"datasource": "custom",
			"board": "upload",
			"strip_html": strip_html,
			**column_mapping,
		}

	def after_create(query, dataset, request):
		"""
		Hook to execute after the dataset for this source has been created

		In this case, put the file in a temporary location so it can be
		processed properly by the related Job later.

		:param dict query:  Sanitised query parameters
		:param DataSet dataset:  Dataset created for this query
		:param request:  Flask request submitted for its creation
		"""
		file = request.files["option-data_upload"]
		file.seek(0)
		with dataset.get_results_path().with_suffix(".importing").open("wb") as outfile:
			while True:
				chunk = file.read(1024)
				if len(chunk) == 0:
					break
				outfile.write(chunk)