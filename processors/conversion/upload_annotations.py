"""
Upload annotations for a dataset
"""
import csv
import io

from flask import g

from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException, QueryParametersException, DataSetException
from common.lib.helpers import UserInput
from common.lib.dataset import DataSet

__author__ = "4CAT"
__credits__ = ["4CAT"]
__maintainer__ = "4CAT"
__email__ = "4cat@oilab.eu"


class UploadAnnotations(BasicProcessor):
	"""
	Upload annotations for a dataset
	"""
	type = "upload-annotations"  # job type ID
	category = "Conversion"  # category
	title = "Upload annotations"  # title displayed in UI
	description = ("Upload annotations for this dataset via a CSV file or by pasting text data. "
				   "The first column should contain item IDs; subsequent columns become annotation fields. "
				   "For CSV file uploads, comma is used as the separator. For text input, a custom separator can be specified.")
	extension = "csv"

	@classmethod
	def get_options(cls, parent_dataset=None, config=None) -> dict:
		"""
		Get processor options

		:param parent_dataset DataSet:  An object representing the dataset that
			the processor would be or was run on.
		:param config ConfigManager|None config:  Configuration reader (context-aware)
		:return dict:   Options for this processor
		"""
		return {
			"intro": {
				"type": UserInput.OPTION_INFO,
				"help": "Add annotations to the parent dataset. The first column should contain item IDs "
						"matching items in the dataset. Each subsequent column becomes a text annotation. "
						"A maximum of 20 new annotation fields per uploaded dataset is allowed."
			},
			"upload_method": {
				"type": UserInput.OPTION_CHOICE,
				"help": "Upload method",
				"options": {
					"file": "Upload CSV file",
					"text": "Paste text"
				},
				"default": "file"
			},
			"data_upload": {
				"type": UserInput.OPTION_FILE,
				"help": "CSV file with annotations",
				"requires": "upload_method=file",
				"tooltip": "Use UTF-8"
			},
			"separator": {
				"type": UserInput.OPTION_CHOICE,
				"help": "Separator",
				"default": "comma",
				"requires": "upload_method=text",
				"options": {
					"comma": "Comma",
					"tab": "Tab"
				}
			},
			"annotation_text": {
				"type": UserInput.OPTION_TEXT_LARGE,
				"help": "Paste annotation data (one item per line, starting with the item ID, then annotation values)",
				"requires": "upload_method=text"
			}
		}

	@classmethod
	def is_compatible_with(cls, module=None, config=None):
		"""
		Allow processor on top-level CSV and NDJSON datasets

		:param module: Module to determine compatibility with
		:param config: Configuration reader (context-aware)
		"""
		return module.is_top_dataset() and module.get_extension() in ("csv", "ndjson")

	@staticmethod
	def validate_query(query, request, config):
		"""
		Validate uploaded annotation data

		Checks that the uploaded data is valid and that annotation field names
		do not conflict with existing ones.

		:param dict query:  Query parameters, from client-side.
		:param request:  Flask request
		:param config:  Configuration reader (context-aware)
		:return dict:  Safe query parameters
		"""
		upload_method = query.get("upload_method", "file")

		if upload_method == "file":
			if "option-data_upload" not in request.files or not request.files["option-data_upload"]:
				raise QueryParametersException("No file was uploaded.")

			file = request.files["option-data_upload"]
			file.seek(0)
			try:
				content = file.read().decode("utf-8")
			except UnicodeDecodeError:
				raise QueryParametersException("The uploaded file must be a UTF-8 encoded CSV.")
			finally:
				file.seek(0)

			separator = ","
		elif upload_method == "text":
			content = query.get("annotation_text", "").strip()
			if not content:
				raise QueryParametersException("No annotation data was provided.")
			separator = query.get("separator", "comma")
			separator = "," if separator == "comma" else "\t" if separator == "tab" else separator
		else:
			raise QueryParametersException("Invalid upload method.")

		# Parse the header row
		try:
			reader = csv.reader(io.StringIO(content), delimiter=separator)
			header = next(reader, None)
		except csv.Error:
			raise QueryParametersException("Could not parse the data. Make sure the correct separator is used between columns.")

		if not header or len(header) < 2:
			raise QueryParametersException(
				"Data must have at least two columns: the first for item IDs, and at least one for annotations. "
				"Make sure the correct separator is used between columns."
			)

		annotation_labels = [h.strip() for h in header[1:]]

		# Check max 20 annotation fields
		if len(annotation_labels) > 20:
			raise QueryParametersException("A maximum of 20 annotation fields per upload is allowed.")

		# Check for empty field names
		if any(not label for label in annotation_labels):
			raise QueryParametersException("Annotation field names cannot be empty.")

		# Check for duplicate field names in the upload
		if len(set(annotation_labels)) != len(annotation_labels):
			raise QueryParametersException("Annotation field names must be unique within the upload.")

		# Check if annotation fields already exist in the dataset
		key = request.form.get("key", "")
		if key:
			try:
				dataset = DataSet(key=key, db=g.db, modules=g.modules)
				existing_labels = dataset.get_annotation_field_labels()
				conflicts = [label for label in annotation_labels if label in existing_labels]
				if conflicts:
					raise QueryParametersException(
						"The following annotation field(s) already exist for this dataset: %s. "
						"Please rename them in your input data." % ", ".join(conflicts)
					)
			except DataSetException:
				pass

		return query

	@staticmethod
	def after_create(query, dataset, request):
		"""
		Save uploaded file to disk after dataset creation

		:param dict query:  Sanitised query parameters
		:param DataSet dataset:  Dataset created for this processor
		:param request:  Flask request submitted for its creation
		"""
		if query.get("upload_method", "file") == "file":
			file = request.files["option-data_upload"]
			file.seek(0)
			with dataset.get_results_path().with_suffix(".importing").open("wb") as outfile:
				while True:
					chunk = file.read(1024)
					if len(chunk) == 0:
						break
					outfile.write(chunk)

	def process(self):
		"""
		Process uploaded annotations and save them to the dataset
		"""
		upload_method = self.parameters.get("upload_method", "file")
		import_file = None
		f_handle = None

		if upload_method == "file":
			import_file = self.dataset.get_results_path().with_suffix(".importing")
			if not import_file.exists():
				self.dataset.finish_with_error("No uploaded file found.")
				return

			f_handle = import_file.open("r", encoding="utf-8")
			separator = ","
		else:
			content = self.parameters.get("annotation_text", "").strip()
			separator = self.parameters.get("separator", "comma")
			separator = "," if separator == "comma" else "\t" if separator == "tab" else separator
			if not content:
				self.dataset.finish_with_error("No annotation data was provided.")
				return
			f_handle = io.StringIO(content)

		# Parse data
		try:
			reader = csv.reader(f_handle, delimiter=separator)
			header = next(reader, None)
		except csv.Error:
			self.dataset.finish_with_error("Could not parse the uploaded data. Make sure the correct separator is used between columns.")
			return

		if not header or len(header) < 2:
			self.dataset.finish_with_error(
				"Data must have at least two columns: the first for item IDs, and at least one for annotations."
			)
			return

		annotation_labels = [h.strip() for h in header[1:]]

		# Check max 20 annotations
		if len(annotation_labels) > 20:
			self.dataset.finish_with_error("A maximum of 20 annotation fields per upload is allowed.")
			return

		# Check for duplicate annotation field names in existing annotations
		source_dataset = self.source_dataset
		existing_labels = source_dataset.get_annotation_field_labels()
		conflicts = [label for label in annotation_labels if label in existing_labels]
		if conflicts:
			self.dataset.finish_with_error(
				"Annotation field(s) already exist: %s. Please rename them in your input data." % ", ".join(conflicts)
			)
			return

		# Get valid item IDs from the source dataset
		self.dataset.update_status("Reading source dataset item IDs")
		valid_item_ids = set()
		for item in source_dataset.iterate_items():
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while reading item IDs")
			valid_item_ids.add(str(item["id"]))

		# Process annotations
		self.dataset.update_status("Processing annotations")
		annotations = []
		saved = 0
		skipped = 0

		rows = list(reader)
		total_rows = len(rows)

		results = []

		for row_num, row in enumerate(rows):
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while processing annotations")

			if not row or not row[0].strip():
				skipped += 1
				continue

			item_id = row[0].strip()

			# Skip items not in the dataset
			if item_id not in valid_item_ids:
				skipped += 1
				continue

			# Save the annotations for this item
			# We're also going to save the processed annotations as an output to this processor.
			result = {"id": item_id}
			for i, label in enumerate(annotation_labels):
				value = row[i + 1].strip() if i + 1 < len(row) else ""
				if value:
					annotations.append({
						"label": label,
						"item_id": item_id,
						"value": value
					})
					saved += 1

				result[label] = value

			if len(result) > 1:
				results.append(result)

			if len(annotations) >= 2500:
				self.save_annotations(annotations, source_dataset=source_dataset)
				annotations = []
				self.dataset.update_status("Added %i annotations, processed rows %i/%i" % (saved, row_num, total_rows))
				self.dataset.update_progress(row_num / max(1, total_rows))

		# Save remaining annotations
		if annotations:
			self.save_annotations(annotations, source_dataset=source_dataset)

		# Delete uploaded file
		if f_handle:
			f_handle.close()
		if import_file and import_file.exists():
			import_file.unlink(missing_ok=True)

		if saved == 0:
			self.dataset.finish_with_error("No valid annotations found. Make sure item IDs in the "
															"first column match the dataset."
			)
			return

		# Write uploaded annotations as output file
		warning = None
		if skipped:
			warning = "Uploaded %i annotation(s) for %i item(s). Skipped %i row(s) (item ID not found in dataset or empty)." % (saved, total_rows, skipped)
		self.write_csv_items_and_finish(results, warning=warning)
