"""
Basic post-processor worker - should be inherited by workers to post-process results
"""
import traceback
import zipfile
import typing
import shutil
import json
import abc
import csv
import os

from pathlib import Path, PurePath

import backend
from backend.abstract.worker import BasicWorker
from common.lib.dataset import DataSet
from common.lib.fourcat_module import FourcatModule
from common.lib.helpers import get_software_version
from common.lib.exceptions import WorkerInterruptedException, ProcessorInterruptedException, ProcessorException

csv.field_size_limit(1024 * 1024 * 1024)


class BasicProcessor(FourcatModule, BasicWorker, metaclass=abc.ABCMeta):
	"""
	Abstract processor class

	A processor takes a finished dataset as input and processes its result in
	some way, with another dataset set as output. The input thus is a file, and
	the output (usually) as well. In other words, the result of a processor can
	be used as input for another processor (though whether and when this is
	useful is another question).

	To determine whether a processor can process a given dataset, you can
	define a `is_compatible_with(FourcatModule module=None):) -> bool` class
	method which takes a dataset *or* processor as argument and returns a bool
	that determines if this processor is considered compatible with that
	dataset or processor. For example:

	.. code-block:: python

        @classmethod
        def is_compatible_with(cls, module=None):
            return module.type == "linguistic-features"


	"""

	#: Database handler to interface with the 4CAT database
	db = None

	#: Job object that requests the execution of this processor
	job = None

	#: The dataset object that the processor is *creating*.
	dataset = None

	#: The dataset object that the processor is *processing*.
	source_dataset = None

	#: The file that is being processed
	source_file = None

	#: Processor description, which will be displayed in the web interface
	description = "No description available"

	#: Category identifier, used to group processors in the web interface
	category = "Other"

	#: Extension of the file created by the processor
	extension = "csv"

	#: Configurable options for this processor
	options = {}

	#: Values for the processor's options, populated by user input
	parameters = {}

	#: Is this processor running 'within' a preset processor?
	is_running_in_preset = False

	#: This will be defined automatically upon loading the processor. There is
	#: no need to override manually
	filepath = None

	def work(self):
		"""
		Process a dataset

		Loads dataset metadata, sets up the scaffolding for performing some kind
		of processing on that dataset, and then processes it. Afterwards, clean
		up.
		"""
		try:
			self.dataset = DataSet(key=self.job.data["remote_id"], db=self.db)
		except TypeError:
			# query has been deleted in the meantime. finish without error,
			# as deleting it will have been a conscious choice by a user
			self.job.finish()
			return

		if self.dataset.data.get("key_parent", None):
			# search workers never have parents (for now), so we don't need to
			# find out what the source_dataset dataset is if it's a search worker
			try:
				self.source_dataset = self.dataset.get_parent()

				# for presets, transparently use the *top* dataset as a source_dataset
				# since that is where any underlying processors should get
				# their data from. However, this should only be done as long as the
				# preset is not finished yet, because after that there may be processors
				# that run on the final preset result
				while self.source_dataset.type.startswith("preset-") and not self.source_dataset.is_finished():
					self.is_running_in_preset = True
					self.source_dataset = self.source_dataset.get_parent()
					if self.source_dataset is None:
						# this means there is no dataset that is *not* a preset anywhere
						# above this dataset. This should never occur, but if it does, we
						# cannot continue
						self.log.error("Processor preset %s for dataset %s cannot find non-preset parent dataset",
									   (self.type, self.dataset.key))
						self.job.finish()
						return

			except TypeError:
				# we need to know what the source_dataset dataset was to properly handle the
				# analysis
				self.log.warning("Processor %s queued for orphan query %s: cannot run, cancelling job" % (
					self.type, self.dataset.key))
				self.job.finish()
				return

			if not self.source_dataset.is_finished() and not self.is_running_in_preset:
				# not finished yet - retry after a while
				# exception for presets, since these *should* be unfinished
				# until underlying processors are done
				self.job.release(delay=30)
				return

			self.source_file = self.source_dataset.get_results_path()
			if not self.source_file.exists():
				self.dataset.update_status("Finished, no input data found.")

		self.log.info("Running processor %s on dataset %s" % (self.type, self.job.data["remote_id"]))

		processor_name = self.title if hasattr(self, "title") else self.type
		self.dataset.clear_log()
		self.dataset.log("Processing '%s' started for dataset %s" % (processor_name, self.dataset.key))

		# start log file
		self.dataset.update_status("Processing data")
		self.dataset.update_version(get_software_version())

		# get parameters
		# if possible, fill defaults where parameters are not provided
		given_parameters = self.dataset.parameters.copy()
		all_parameters = self.get_options(self.dataset)
		self.parameters = {
			param: given_parameters.get(param, all_parameters.get(param, {}).get("default"))
			for param in [*all_parameters.keys(), *given_parameters.keys()]
		}

		# now the parameters have been loaded into memory, clear any sensitive
		# ones. This has a side-effect that a processor may not run again
		# without starting from scratch, but this is the price of progress
		options = self.get_options(self.dataset.get_parent())
		for option, option_settings in options.items():
			if option_settings.get("sensitive"):
				self.dataset.delete_parameter(option)

		if self.interrupted:
			self.dataset.log("Processing interrupted, trying again later")
			return self.abort()

		if not self.dataset.is_finished():
			try:
				self.process()
				self.after_process()
			except WorkerInterruptedException as e:
				self.dataset.log("Processing interrupted (%s), trying again later" % str(e))
				self.abort()
			except Exception as e:
				self.dataset.log("Processor crashed (%s), trying again later" % str(e))
				frames = traceback.extract_tb(e.__traceback__)
				frames = [frame.filename.split("/").pop() + ":" + str(frame.lineno) for frame in frames[1:]]
				location = "->".join(frames)

				# Not all datasets have source_dataset keys
				if len(self.dataset.get_genealogy()) > 1:
					parent_key = " (via " + self.dataset.get_genealogy()[0].key + ")"
				else:
					parent_key = ""

				# remove any result files that have been created so far
				self.remove_files()

				raise ProcessorException("Processor %s raised %s while processing dataset %s%s in %s:\n   %s\n" % (self.type, e.__class__.__name__, self.dataset.key, parent_key, location, str(e)))
		else:
			# dataset already finished, job shouldn't be open anymore
			self.log.warning("Job %s/%s was queued for a dataset already marked as finished, deleting..." % (self.job.data["jobtype"], self.job.data["remote_id"]))
			self.job.finish()


	def after_process(self):
		"""
		Run after processing the dataset

		This method cleans up temporary files, and if needed, handles logistics
		concerning the result file, e.g. running a pre-defined processor on the
		result, copying it to another dataset, and so on.
		"""
		if self.dataset.data["num_rows"] > 0:
			self.dataset.update_status("Dataset completed.")

		if not self.dataset.is_finished():
			self.dataset.finish()

		if hasattr(self, "staging_area") and type(self.staging_area) == Path and self.staging_area.exists():
			shutil.rmtree(self.staging_area)

		# see if we have anything else lined up to run next
		for next in self.parameters.get("next", []):
			next_parameters = next.get("parameters", {})
			next_type = next.get("type", "")
			try:
				available_processors = self.dataset.get_available_processors()
			except ValueError:
				self.log.info("Trying to queue next processor, but parent dataset no longer exists, halting")
				break

			# run it only if the post-processor is actually available for this query
			if self.dataset.data["num_rows"] <= 0:
				self.log.info("Not running follow-up processor of type %s for dataset %s, no input data for follow-up" % (next_type, self.dataset.key))

			elif next_type in available_processors:
				next_analysis = DataSet(
					parameters=next_parameters,
					type=next_type,
					db=self.db,
					parent=self.dataset.key,
					extension=available_processors[next_type].extension,
					is_private=self.dataset.is_private,
					owner=self.dataset.owner
				)
				self.queue.add_job(next_type, remote_id=next_analysis.key)
			else:
				self.log.warning("Dataset %s (of type %s) wants to run processor %s next, but it is incompatible" % (self.dataset.key, self.type, next_type))

		# see if we need to register the result somewhere
		if "copy_to" in self.parameters:
			# copy the results to an arbitrary place that was passed
			if self.dataset.get_results_path().exists():
				shutil.copyfile(str(self.dataset.get_results_path()), self.parameters["copy_to"])
			else:
				# if copy_to was passed, that means it's important that this
				# file exists somewhere, so we create it as an empty file
				with open(self.parameters["copy_to"], "w") as empty_file:
					empty_file.write("")

		# see if this query chain is to be attached to another query
		# if so, the full genealogy of this query (minus the original dataset)
		# is attached to the given query - this is mostly useful for presets,
		# where a chain of processors can be marked as 'underlying' a preset
		if "attach_to" in self.parameters:
			try:
				# copy metadata and results to the surrogate
				surrogate = DataSet(key=self.parameters["attach_to"], db=self.db)

				if self.dataset.get_results_path().exists():
					shutil.copyfile(str(self.dataset.get_results_path()), str(surrogate.get_results_path()))

				try:
					surrogate.finish(self.dataset.data["num_rows"])
				except RuntimeError:
					# already finished, could happen (though it shouldn't)
					pass

				surrogate.update_status(self.dataset.get_status())

			except ValueError:
				# dataset with key to attach to doesn't exist...
				self.log.warning("Cannot attach dataset chain containing %s to %s (dataset does not exist)" % (
				self.dataset.key, self.parameters["attach_to"]))

		self.job.finish()

	def remove_files(self):
		"""
		Clean up result files and any staging files for processor to be attempted
		later if desired.
		"""
		if self.dataset.get_results_path().exists():
			self.dataset.get_results_path().unlink()

		if self.dataset.staging_area:
			for staging_area in self.dataset.staging_area:
				if staging_area.is_dir():
					shutil.rmtree(staging_area)

	def abort(self):
		"""
		Abort dataset creation and clean up so it may be attempted again later
		"""
		# remove any result files that have been created so far
		self.remove_files()

		# we release instead of finish, since interrupting is just that - the
		# job should resume at a later point. Delay resuming by 10 seconds to
		# give 4CAT the time to do whatever it wants (though usually this isn't
		# needed since restarting also stops the spawning of new workers)
		if self.interrupted == self.INTERRUPT_RETRY:
			# retry later - wait at least 10 seconds to give the backend time to shut down
			self.job.release(delay=10)
		elif self.interrupted == self.INTERRUPT_CANCEL:
			# cancel job
			self.job.finish()

	def add_field_to_parent(self, field_name, new_data, which_parent=source_dataset, update_existing=False):
		"""
		This function adds a new field to the parent dataset. Expects a list of data points, one for each item
		in the parent dataset. Processes csv and ndjson. If udpate_existing is set to True, this can be used
		to overwrite an existing field.

		TODO: could be improved by accepting different types of data depending on csv or ndjson.

		:param str field_name: 	name of the desired
		:param List new_data: 	List of data to be added to parent dataset
		:param DataSet which_parent: 	DataSet to be updated (e.g., self.source_dataset, self.dataset.get_parent(), self.dataset.top_parent())
		:param bool update_existing: 	False (default) will raise an error if the field_name already exists
										True will allow updating existing data
		"""
		if len(new_data) < 1:
			# no data
			raise ProcessorException('No data provided')

		if not hasattr(self, "source_dataset") and which_parent is not None:
			# no source to update
			raise ProcessorException('No source dataset to update')

		# Get the source file data path
		parent_path = which_parent.get_results_path()

		if len(new_data) != which_parent.num_rows:
			raise ProcessorException('Must have new data point for each record')

		self.dataset.update_status("Adding new field %s to the source file" % field_name)

		# Get a temporary path where we can store the data
		tmp_path = self.dataset.get_staging_area()
		tmp_file_path = tmp_path.joinpath(parent_path.name)

		# go through items one by one, optionally mapping them
		if parent_path.suffix.lower() == ".csv":
			# Get field names
			fieldnames = which_parent.get_item_keys(self)
			if not update_existing and field_name in fieldnames:
				raise ProcessorException('field_name %s already exists!' % field_name)
			fieldnames.append(field_name)

			# Iterate through the original dataset and add values to a new column
			self.dataset.update_status("Writing new source file with %s." % field_name)
			with tmp_file_path.open("w", encoding="utf-8", newline="") as output:
				writer = csv.DictWriter(output, fieldnames=fieldnames)
				writer.writeheader()

				for count, post in enumerate(which_parent.iterate_items(self, bypass_map_item=True)):
					# stop processing if worker has been asked to stop
					if self.interrupted:
						raise ProcessorInterruptedException("Interrupted while writing CSV file")

					post[field_name] = new_data[count]
					writer.writerow(post)

		elif parent_path.suffix.lower() == ".ndjson":
			# JSON cannot encode sets
			if type(new_data[0]) is set:
				# could check each if type(datapoint) is set, but that could be extensive...
				new_data = [list(datapoint) for datapoint in new_data]

			with tmp_file_path.open("w", encoding="utf-8", newline="") as output:
				for count, post in enumerate(which_parent.iterate_items(self, bypass_map_item=True)):
					# stop processing if worker has been asked to stop
					if self.interrupted:
						raise ProcessorInterruptedException("Interrupted while writing NDJSON file")

					if not update_existing and field_name in post.keys():
						raise ProcessorException('field_name %s already exists!' % field_name)

					# Update data
					post[field_name] = new_data[count]

					output.write(json.dumps(post) + "\n")
		else:
			raise NotImplementedError("Cannot iterate through %s file" % parent_path.suffix)

		# Replace the source file path with the new file
		shutil.copy(str(tmp_file_path), str(parent_path))

		# delete temporary files and folder
		shutil.rmtree(tmp_path)

		self.dataset.update_status("Parent dataset updated.")

	def iterate_archive_contents(self, path, staging_area=None):
		"""
		A generator that iterates through files in an archive

		With every iteration, the processor's 'interrupted' flag is checked,
		and if set a ProcessorInterruptedException is raised, which by default
		is caught and subsequently stops execution gracefully.

		Files are temporarily unzipped and deleted after use.

		:param Path path: 	Path to zip file to read
		:param Path staging_area:  Where to store the files while they're
		  being worked with. If omitted, a temporary folder is created and
		  deleted after use
		:return:  An iterator with a Path item for each file
		"""

		if not path.exists():
			return

		if staging_area and (not staging_area.exists() or not staging_area.is_dir()):
			raise RuntimeError("Staging area %s is not a valid folder")
		else:
			if not hasattr(self, "staging_area") and not staging_area:
				self.staging_area = self.dataset.get_staging_area()
				staging_area = self.staging_area

		with zipfile.ZipFile(path, "r") as archive_file:
			archive_contents = sorted(archive_file.namelist())

			for archived_file in archive_contents:
				if self.interrupted:
					if hasattr(self, "staging_area"):
						shutil.rmtree(self.staging_area)
					raise ProcessorInterruptedException("Interrupted while iterating zip file contents")

				file_name = archived_file.split("/")[-1]
				temp_file = staging_area.joinpath(file_name)
				archive_file.extract(file_name, staging_area)

				yield temp_file
				if hasattr(self, "staging_area"):
					temp_file.unlink()

		if hasattr(self, "staging_area"):
			shutil.rmtree(self.staging_area)
			del self.staging_area

	def unpack_archive_contents(self, path, staging_area=None):
		"""
		Unpack all files in an archive to a staging area

		With every iteration, the processor's 'interrupted' flag is checked,
		and if set a ProcessorInterruptedException is raised, which by default
		is caught and subsequently stops execution gracefully.

		Files are unzipped to a staging area. The staging area is *not*
		cleaned up automatically.

		:param Path path: 	Path to zip file to read
		:param Path staging_area:  Where to store the files while they're
		  being worked with. If omitted, a temporary folder is created and
		  deleted after use
		:return Path:  A path to the staging area
		"""

		if not path.exists():
			return

		if staging_area and (not staging_area.exists() or not staging_area.is_dir()):
			raise RuntimeError("Staging area %s is not a valid folder")
		else:
			if not hasattr(self, "staging_area"):
				self.staging_area = self.dataset.get_staging_area()

			staging_area = self.staging_area

		paths = []
		with zipfile.ZipFile(path, "r") as archive_file:
			archive_contents = sorted(archive_file.namelist())

			for archived_file in archive_contents:
				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while iterating zip file contents")

				file_name = archived_file.split("/")[-1]
				temp_file = staging_area.joinpath(file_name)
				archive_file.extract(archived_file, staging_area)
				paths.append(temp_file)

		return staging_area

	def write_csv_items_and_finish(self, data):
		"""
		Write data as csv to results file and finish dataset

		Determines result file path using dataset's path determination helper
		methods. After writing results, the dataset is marked finished. Will
		raise a ProcessorInterruptedException if the interrupted flag for this
		processor is set while iterating.

		:param data: A list or tuple of dictionaries, all with the same keys
		"""
		if not (isinstance(data, typing.List) or isinstance(data, typing.Tuple)) or isinstance(data, str):
			raise TypeError("write_csv_items requires a list or tuple of dictionaries as argument")

		if not data:
			raise ValueError("write_csv_items requires a dictionary with at least one item")

		if not isinstance(data[0], dict):
			raise TypeError("write_csv_items requires a list or tuple of dictionaries as argument")

		self.dataset.update_status("Writing results file")
		with self.dataset.get_results_path().open("w", encoding="utf-8", newline='') as results:
			writer = csv.DictWriter(results, fieldnames=data[0].keys())
			writer.writeheader()

			for row in data:
				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while writing results file")
				writer.writerow(row)

		self.dataset.update_status("Finished")
		self.dataset.finish(len(data))

	def write_archive_and_finish(self, files, num_items=None, compression=zipfile.ZIP_STORED):
		"""
		Archive a bunch of files into a zip archive and finish processing

		:param list|Path files: If a list, all files will be added to the
		  archive and deleted afterwards. If a folder, all files in the folder
		  will be added and the folder will be deleted afterwards.
		:param int num_items: Items in the dataset. If None, the amount of
		  files added to the archive will be used.
		:param int compression:  Type of compression to use. By default, files
		  are not compressed, to speed up unarchiving.
		"""
		is_folder = False
		if issubclass(type(files), PurePath):
			is_folder = files
			if not files.exists() or not files.is_dir():
				raise RuntimeError("Folder %s is not a folder that can be archived" % files)

			files = files.glob("*")

		# create zip of archive and delete temporary files and folder
		self.dataset.update_status("Compressing results into archive")
		done = 0
		with zipfile.ZipFile(self.dataset.get_results_path(), "w", compression=compression) as zip:
			for output_path in files:
				zip.write(output_path, output_path.name)
				output_path.unlink()
				done += 1

		# delete temporary folder
		if is_folder:
			shutil.rmtree(is_folder)

		self.dataset.update_status("Finished")
		if num_items is None:
			num_items = done

		self.dataset.finish(num_items)

	def create_standalone(self):
		"""
		Copy this dataset and make that copy standalone

		This has the benefit of allowing for all analyses that can be run on
		full datasets on the new, filtered copy as well.
		"""
		top_parent = self.source_dataset

		standalone = self.dataset.copy(shallow=False)
		standalone.body_match = "(Filtered) " + top_parent.query
		standalone.datasource = top_parent.parameters.get("datasource", "custom")

		try:
			standalone.board = top_parent.board
		except KeyError:
			standalone.board = self.type

		standalone.type = top_parent.type

		standalone.detach()
		standalone.delete_parameter("key_parent")

		self.dataset.copied_to = standalone.key

		# we don't need this file anymore - it has been copied to the new
		# standalone dataset, and this one is not accessible via the interface
		# except as a link to the copied standalone dataset
		os.unlink(self.dataset.get_results_path())

	@classmethod
	def is_filter(cls):
		"""
		Is this processor a filter?

		Filters do not produce their own dataset but replace the source_dataset dataset
		instead.

		:todo: Make this a bit more robust than sniffing the processor category
		:return bool:
		"""
		return hasattr(cls, "category") and cls.category and "filter" in cls.category.lower()

	@classmethod
	def get_options(cls, parent_dataset=None, user=None):
		"""
		Get processor options

		This method by default returns the class's "options" attribute, or an
		empty dictionary. It can be redefined by processors that need more
		fine-grained options, e.g. in cases where the availability of options
		is partially determined by the parent dataset's parameters.

		:param DataSet parent_dataset:  An object representing the dataset that
		  the processor would be run on
		:param User user:  Flask user the options will be displayed for, in
		  case they are requested for display in the 4CAT web interface. This can
		  be used to show some options only to privileges users.
		"""
		return cls.options if hasattr(cls, "options") else {}

	@classmethod
	def get_status(cls):
		"""
		Get processor status

		:return list:	Statuses of this processor
		"""
		return cls.status if hasattr(cls, "status") else None

	@classmethod
	def get_available_processors(cls, self):
		"""
		Get list of processors compatible with this processor

		Checks whether this dataset type is one that is listed as being accepted
		by the processor, for each known type: if the processor does not
		specify accepted types (via the `is_compatible_with` method), it is
		assumed it accepts any top-level datasets

		:return dict:  Compatible processors, `name => class` mapping
		"""
		processors = backend.all_modules.processors

		available = []
		for processor_type, processor in processors.items():
			if processor_type.endswith("-search"):
				continue

			# consider a processor compatible if its is_compatible_with
			# method returns True *or* if it has no explicit compatibility
			# check and this dataset is top-level (i.e. has no parent)
			if hasattr(processor, "is_compatible_with"):
				if processor.is_compatible_with(module=self):
					available.append(processor)

		return available

	@classmethod
	def is_dataset(cls):
		"""
		Confirm this is *not* a dataset, but a processor.

		Used for processor compatibility checks.

		:return bool:  Always `False`, because this is a processor.
		"""
		return False

	@classmethod
	def is_top_dataset(cls):
		"""
		Confirm this is *not* a top dataset, but a processor.

		Used for processor compatibility checks.

		:return bool:  Always `False`, because this is a processor.
		"""
		return False

	@classmethod
	def get_extension(self):
		"""
		Return the extension of the processor's dataset

		Used for processor compatibility checks.

		:return str|None:  Dataset extension (without leading `.`) or `None`.
		"""

		if self.extension and not self.is_filter():
			return self.extension
		return None

	@classmethod
	def is_rankable(cls, multiple_items=True):
		"""
		Used for processor compatibility

		:param bool multiple_items:  Consider datasets with multiple items per
		  item (e.g. word_1, word_2, etc)? Included for compatibility
		"""
		return False

	@abc.abstractmethod
	def process(self):
		"""
		Process data

		To be defined by the child processor.
		"""
		pass
