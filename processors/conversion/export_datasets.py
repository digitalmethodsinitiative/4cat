"""
Export a dataset and all its children to a ZIP file
"""
import shutil
import json
import datetime

from backend.lib.processor import BasicProcessor
from common.lib.dataset import DataSet
from common.lib.exceptions import DataSetException

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"



class ExportDatasets(BasicProcessor):
	"""
	Export a dataset and all its children to a ZIP file
	"""
	type = "export-datasets"  # job type ID
	category = "Conversion"  # category
	title = "Export Dataset and All Analyses"  # title displayed in UI
	description = "Creates a ZIP file containing the dataset and all analyses to be archived and uploaded to a 4CAT instance in the future. Filters are *not* included and must be exported separately as new datasets. Results automatically expire after 1 day, after which you must run again."  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI

	@classmethod
	def is_compatible_with(cls, module=None, config=None):
		"""
		Determine if processor is compatible with dataset

		:param module: Module to determine compatibility with
		"""
		return module.is_top_dataset() and module.is_accessible_by(config.user, role="owner")

	def process(self):
		"""
		This takes a CSV file as input and writes the same data as a JSON file
		"""
		self.dataset.update_status("Collecting dataset and all analyses")
		primary_dataset = self.dataset.top_parent()
		if not primary_dataset.is_finished():
			# This ought not happen as processors (i.e., this processor) should only be available for finished datasets
			self.dataset.finish_with_error("You cannot export unfinished datasets; please wait until dataset is finished to export.")
			return

		results_path = self.dataset.get_staging_area()

		exported_datasets = []
		failed_exports = []  # keys that failed to import
		keys = [self.dataset.top_parent().key] # get the key of the top parent
		while keys:
			dataset_key = keys.pop(0)
			self.dataset.log(f"Exporting dataset {dataset_key}.")

			try:
				dataset = DataSet(key=dataset_key, db=self.db)
			except DataSetException:
				self.dataset.update_status(f"Dataset {dataset_key} not found: it may have been deleted prior to export; skipping.")
				failed_exports.append(dataset_key)
				continue
			if not dataset.is_finished():
				self.dataset.update_status(f"Dataset {dataset_key} not finished: cannot export unfinished datasets; skipping.")
				failed_exports.append(dataset_key)
				continue

			# get metadata
			metadata = dataset.get_metadata()
			if metadata["num_rows"] == 0:
				self.dataset.update_status(f"Dataset {dataset_key} has no results; skipping.")
				failed_exports.append(dataset_key)
				continue

			# get data
			data_file = dataset.get_results_path()
			if not data_file.exists():
				self.dataset.update_status(f"Dataset {dataset_key} has no data file; skipping.")
				failed_exports.append(dataset_key)
				continue

			# get log
			log_file = dataset.get_results_path().with_suffix(".log")

			# All good, add to ZIP
			with results_path.joinpath(f"{dataset_key}_metadata.json").open("w", encoding="utf-8") as outfile:
				outfile.write(json.dumps(metadata))
			shutil.copy(data_file, results_path.joinpath(data_file.name))
			if log_file.exists():
				shutil.copy(log_file, results_path.joinpath(log_file.name))

			# add children to queue
			# Not using get_all_children() because we want to skip unfinished datasets and only need the keys
			children = [d["key"] for d in self.db.fetchall("SELECT key FROM datasets WHERE key_parent = %s AND is_finished = TRUE", (dataset_key,))]
			keys.extend(children)

			self.dataset.update_status(f"Exported dataset {dataset_key}.")
			exported_datasets.append(dataset_key)

		# Add export log to ZIP
		self.dataset.log(f"Exported datasets: {exported_datasets}")
		self.dataset.log(f"Failed to export datasets: {failed_exports}")
		shutil.copy(self.dataset.get_log_path(), results_path.joinpath("export.log"))

		# set expiration date
		# these datasets can be very large and are just copies of the existing datasets, so we don't need to keep them around for long
		# TODO: convince people to stop using hyphens in python variables and file names...
		self.dataset.__setattr__("expires-after", (datetime.datetime.now() + datetime.timedelta(days=1)).timestamp())

		# done!
		self.write_archive_and_finish(results_path, len(exported_datasets))