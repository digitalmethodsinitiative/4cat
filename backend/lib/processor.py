"""
Basic post-processor worker - should be inherited by workers to post-process results
"""
import re
import traceback
import zipfile
import typing
import shutil
import json
import abc
import csv
import os

from pathlib import Path, PurePath

from backend.lib.worker import BasicWorker
from common.lib.dataset import DataSet
from common.lib.fourcat_module import FourcatModule
from common.lib.helpers import get_software_commit, remove_nuls, send_email
from common.lib.exceptions import (WorkerInterruptedException, ProcessorInterruptedException, ProcessorException,
								   DataSetException, MapItemException)
from common.config_manager import config, ConfigWrapper


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
	define a `is_compatible_with(FourcatModule module=None, str user=None):) -> bool` class
	method which takes a dataset as argument and returns a bool that determines
	if this processor is considered compatible with that dataset. For example:

	.. code-block:: python

        @classmethod
        def is_compatible_with(cls, module=None, user=None):
            return module.type == "linguistic-features"


	"""

	#: Database handler to interface with the 4CAT database
	db = None

	#: Job object that requests the execution of this processor
	job = None

	#: The dataset object that the processor is *creating*.
	dataset = None

	#: Owner (username) of the dataset
	owner = None

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

	#: 4CAT settings from the perspective of the dataset's owner
	config = None

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
			# a dataset can have multiple owners, but the creator is the user
			# that actually queued the processor, so their config is relevant
			self.dataset = DataSet(key=self.job.data["remote_id"], db=self.db)
			self.owner = self.dataset.creator
		except DataSetException as e:
			# query has been deleted in the meantime. finish without error,
			# as deleting it will have been a conscious choice by a user
			self.job.finish()
			return

		# set up config reader using the worker's DB connection and the dataset
		# creator. This ensures that if a value has been overriden for the owner,
		# the overridden value is used instead.
		config.with_db(self.db)
		self.config = ConfigWrapper(config=config, user=self.owner)

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

			except DataSetException:
				# we need to know what the source_dataset dataset was to properly handle the
				# analysis
				self.log.warning("Processor %s queued for orphan dataset %s: cannot run, cancelling job" % (
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
		self.dataset.update_version(get_software_commit())

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
				last_frame = frames[-1]
				frames = [frame.filename.split("/").pop() + ":" + str(frame.lineno) for frame in frames[1:]]
				location = "->".join(frames)

				# Not all datasets have source_dataset keys
				if len(self.dataset.get_genealogy()) > 1:
					parent_key = " (via " + self.dataset.get_genealogy()[0].key + ")"
				else:
					parent_key = ""

				# remove any result files that have been created so far
				self.remove_files()

				raise ProcessorException("Processor %s raised %s while processing dataset %s%s in %s:\n   %s\n" % (
				self.type, e.__class__.__name__, self.dataset.key, parent_key, location, str(e)), frame=last_frame)
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

		self.dataset.remove_staging_areas()

		# see if we have anything else lined up to run next
		for next in self.parameters.get("next", []):
			can_run_next = True
			next_parameters = next.get("parameters", {})
			next_type = next.get("type", "")
			try:
				available_processors = self.dataset.get_available_processors(user=self.dataset.creator)
			except ValueError:
				self.log.info("Trying to queue next processor, but parent dataset no longer exists, halting")
				break

			# run it only if the post-processor is actually available for this query
			if self.dataset.data["num_rows"] <= 0:
				can_run_next = False
				self.log.info("Not running follow-up processor of type %s for dataset %s, no input data for follow-up" % (next_type, self.dataset.key))

			elif next_type in available_processors:
				next_analysis = DataSet(
					parameters=next_parameters,
					type=next_type,
					db=self.db,
					parent=self.dataset.key,
					extension=available_processors[next_type].extension,
					is_private=self.dataset.is_private,
					owner=self.dataset.creator
				)
				self.queue.add_job(next_type, remote_id=next_analysis.key)
			else:
				can_run_next = False
				self.log.warning("Dataset %s (of type %s) wants to run processor %s next, but it is incompatible" % (self.dataset.key, self.type, next_type))

			if not can_run_next:
				# We are unable to continue the chain of processors, so we check to see if we are attaching to a parent
				# preset; this allows the parent (for example a preset) to be finished and any successful processors displayed
				if "attach_to" in self.parameters:
					# Probably should not happen, but for some reason a mid processor has been designated as the processor
					# the parent should attach to
					pass
				else:
					# Check for "attach_to" parameter in descendents
					have_attach_to = False
					while not have_attach_to:
						if "attach_to" in next_parameters:
							self.parameters["attach_to"] = next_parameters["attach_to"]
							break
						else:
							if "next" in next_parameters:
								next_parameters = next_parameters["next"]
							else:
								# No more descendents
								# Should not happen; we cannot find the source dataset
								break


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

		if config.get('mail.server') and self.dataset.get_parameters().get("email-complete", False):
			owner = self.dataset.get_parameters().get("email-complete", False)
			# Check that username is email address
			if re.match(r"[^@]+\@.*?\.[a-zA-Z]+", owner):
				from email.mime.multipart import MIMEMultipart
				from email.mime.text import MIMEText
				from smtplib import SMTPException
				import socket
				import html2text

				self.log.debug("Sending email to %s" % owner)
				dataset_url = ('https://' if config.get('flask.https') else 'http://') + config.get('flask.server_name') + '/results/' + self.dataset.key
				sender = config.get('mail.noreply')
				message = MIMEMultipart("alternative")
				message["From"] = sender
				message["To"] = owner
				message["Subject"] = "4CAT dataset completed: %s - %s" % (self.dataset.type, self.dataset.get_label())
				mail = """
					<p>Hello %s,</p>
					<p>4CAT has finished collecting your %s dataset labeled: %s</p>
					<p>You can view your dataset via the following link:</p>
					<p><a href="%s">%s</a></p> 
					<p>Sincerely,</p>
					<p>Your friendly neighborhood 4CAT admin</p>
					""" % (owner, self.dataset.type, self.dataset.get_label(), dataset_url, dataset_url)
				html_parser = html2text.HTML2Text()
				message.attach(MIMEText(html_parser.handle(mail), "plain"))
				message.attach(MIMEText(mail, "html"))
				try:
					send_email([owner], message)
				except (SMTPException, ConnectionRefusedError, socket.timeout) as e:
					self.log.error("Error sending email to %s" % owner)

	def remove_files(self):
		"""
		Clean up result files and any staging files for processor to be attempted
		later if desired.
		"""
		# Remove the results file that was created
		if self.dataset.get_results_path().exists():
			self.dataset.get_results_path().unlink()
		if self.dataset.get_results_folder_path().exists():
			shutil.rmtree(self.dataset.get_results_folder_path())

		# Remove any staging areas with temporary data
		self.dataset.remove_staging_areas()

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
		in the parent dataset. Processes csv and ndjson. If update_existing is set to True, this can be used
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
			raise ProcessorException('Must have new data point for each record: parent dataset: %i, new data points: %i' % (which_parent.num_rows, len(new_data)))

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

	def iterate_archive_contents(self, path, staging_area=None, immediately_delete=True):
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
		:param bool immediately_delete:  Temporary files are removed after yielded;
		  False keeps files until the staging_area is removed (usually during processor
		  cleanup)
		:return:  An iterator with a Path item for each file
		"""

		if not path.exists():
			return

		if not staging_area:
			staging_area = self.dataset.get_staging_area()

		if not staging_area.exists() or not staging_area.is_dir():
			raise RuntimeError("Staging area %s is not a valid folder")

		with zipfile.ZipFile(path, "r") as archive_file:
			archive_contents = sorted(archive_file.namelist())

			for archived_file in archive_contents:
				info = archive_file.getinfo(archived_file)
				if info.is_dir():
					continue

				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while iterating zip file contents")

				temp_file = staging_area.joinpath(archived_file)
				archive_file.extract(archived_file, staging_area)

				yield temp_file
				if immediately_delete:
					temp_file.unlink()

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

		if not staging_area:
			staging_area = self.dataset.get_staging_area()

		if not staging_area.exists() or not staging_area.is_dir():
			raise RuntimeError("Staging area %s is not a valid folder")

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
		if not (isinstance(data, typing.List) or isinstance(data, typing.Tuple) or callable(data)) or isinstance(data, str):
			raise TypeError("write_csv_items requires a list or tuple of dictionaries as argument (%s given)" % type(data))

		if not data:
			raise ValueError("write_csv_items requires a dictionary with at least one item")

		self.dataset.update_status("Writing results file")
		writer = False
		with self.dataset.get_results_path().open("w", encoding="utf-8", newline='') as results:
			for row in data:
				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while writing results file")

				row = remove_nuls(row)
				if not writer:
					writer = csv.DictWriter(results, fieldnames=row.keys())
					writer.writeheader()

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

		:return DataSet:  The new standalone dataset
		"""
		top_parent = self.source_dataset

		finished = self.dataset.check_dataset_finished()
		if finished == 'empty':
			# No data to process, so we can't create a standalone dataset
			return
		elif finished is None:
			# I cannot think of why we would create a standalone from an unfinished dataset, but I'll leave it for now
			pass

		standalone = self.dataset.copy(shallow=False)
		standalone.body_match = "(Filtered) " + top_parent.query
		standalone.datasource = top_parent.parameters.get("datasource", "custom")

		try:
			standalone.board = top_parent.board
		except AttributeError:
			standalone.board = self.type

		standalone.type = top_parent.type

		standalone.detach()
		standalone.delete_parameter("key_parent")

		self.dataset.copied_to = standalone.key

		# we don't need this file anymore - it has been copied to the new
		# standalone dataset, and this one is not accessible via the interface
		# except as a link to the copied standalone dataset
		os.unlink(self.dataset.get_results_path())

		# Copy the log
		shutil.copy(self.dataset.get_log_path(), standalone.get_log_path())

		return standalone

	@classmethod
	def map_item_method_available(cls, dataset):
		"""
		Checks if map_item method exists and is compatible with dataset. If dataset does not have an extension,
		returns False

		:param BasicProcessor processor:	The BasicProcessor subclass object with which to use map_item
		:param DataSet dataset:				The DataSet object with which to use map_item
		"""
		# only run item mapper if extension of processor == extension of
		# data file, for the scenario where a csv file was uploaded and
		# converted to an ndjson-based data source, for example
		# todo: this is kind of ugly, and a better fix may be possible
		dataset_extension = dataset.get_extension()
		if not dataset_extension:
			# DataSet results file does not exist or has no extension, use expected extension
			if hasattr(dataset, "extension"):
				dataset_extension = dataset.extension
			else:
				# No known DataSet extension; cannot determine if map_item method compatible
				return False

		return hasattr(cls, "map_item") and cls.extension == dataset_extension

	@classmethod
	def get_mapped_item(cls, item):
		"""
		Get the mapped item using a processors map_item method.

		Ensure map_item method is compatible with a dataset by checking map_item_method_available first.
		"""
		try:
			mapped_item = cls.map_item(item)
		except (KeyError, IndexError) as e:
			raise MapItemException(f"Unable to map item: {type(e).__name__}-{e}")
		if not mapped_item:
			raise MapItemException("Unable to map item!")
		return mapped_item

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
	def is_top_dataset(cls):
		"""
		Confirm this is *not* a top dataset, but a processor.

		Used for processor compatibility checks.

		:return bool:  Always `False`, because this is a processor.
		"""
		return False

	@classmethod
	def is_from_collector(cls):
		"""
		Check if this processor is one that collects data, i.e. a search or
		import worker.

		:return bool:
		"""
		return cls.type.endswith("-search") or cls.type.endswith("-import")

	@classmethod
	def get_extension(self, parent_dataset=None):
		"""
		Return the extension of the processor's dataset

		Used for processor compatibility checks.

		:param DataSet parent_dataset:  An object representing the dataset that
		  the processor would be run on
		:return str|None:  Dataset extension (without leading `.`) or `None`.
		"""
		if self.is_filter():
			if parent_dataset is not None:
				# Filters should use the same extension as the parent dataset
				return parent_dataset.get_extension()
			else:
				# No dataset provided, unable to determine extension of parent dataset
				# if self.is_filter(): originally returned None, so maintaining that outcome. BUT we may want to fall back on the processor extension instead
				return None
		elif self.extension:
			# Use explicitly defined extension in class (Processor class defaults to "csv")
			return self.extension
		else:
			# A non filter processor updated the base Processor extension to None/False?
			return None

	@classmethod
	def is_rankable(cls, multiple_items=True):
		"""
		Used for processor compatibility

		:param bool multiple_items:  Consider datasets with multiple items per
		  item (e.g. word_1, word_2, etc)? Included for compatibility
		"""
		return False


	@classmethod
	def get_csv_parameters(cls, csv_library):
		"""
		Returns CSV parameters if they are changed from 4CAT's defaults.
		"""
		return {}

	@abc.abstractmethod
	def process(self):
		"""
		Process data

		To be defined by the child processor.
		"""
		pass


