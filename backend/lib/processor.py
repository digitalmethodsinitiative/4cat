"""
Basic post-processor worker - should be inherited by workers to post-process results
"""
import traceback
import zipfile
import typing
import shutil
import abc
import csv
import os
import re
import time

from pathlib import PurePath

from backend.lib.worker import BasicWorker
from common.lib.dataset import DataSet
from common.lib.fourcat_module import FourcatModule
from common.lib.helpers import get_software_commit, remove_nuls, send_email, hash_to_md5
from common.lib.exceptions import (WorkerInterruptedException, ProcessorInterruptedException, ProcessorException,
                                   DataSetException, MapItemException)
from common.config_manager import ConfigWrapper
from common.lib.user import User

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
    define a `is_compatible_with(FourcatModule module=None, config=None):) -> bool` class
    method which takes a dataset as argument and returns a bool that determines
    if this processor is considered compatible with that dataset. For example:

    .. code-block:: python

        @classmethod
        def is_compatible_with(cls, module=None, config=None):
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

    #: Is this processor hidden in the front-end, and only used internally/in presets?
    is_hidden = False

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
            self.dataset = DataSet(key=self.job.data["remote_id"], db=self.db, modules=self.modules)
            self.owner = self.dataset.creator
        except DataSetException:
            # query has been deleted in the meantime. finish without error,
            # as deleting it will have been a conscious choice by a user
            self.job.finish()
            return

        # set up config reader wrapping the worker's config manager, which is
        # in turn the one passed to it by the WorkerManager, which is the one
        # originally loaded in bootstrap
        self.config = ConfigWrapper(config=self.config, user=User.get_by_name(self.db, self.owner))

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
        self.dataset.update_version(get_software_commit(self))

        # get parameters
        # if possible, fill defaults where parameters are not provided
        given_parameters = self.dataset.parameters.copy()
        all_parameters = self.get_options(self.dataset, config=self.config)
        self.parameters = {
            param: given_parameters.get(param, all_parameters.get(param, {}).get("default"))
            for param in [*all_parameters.keys(), *given_parameters.keys()]
        }

        # now the parameters have been loaded into memory, clear any sensitive
        # ones. This has a side-effect that a processor may not run again
        # without starting from scratch, but this is the price of progress
        options = self.get_options(self.dataset.get_parent(), config=self.config)
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
                stack = traceback.extract_tb(e.__traceback__)
                frames = [frame.filename.split("/").pop() + ":" + str(frame.lineno) for frame in stack[1:]]
                location = "->".join(frames)

                # Not all datasets have source_dataset keys
                if len(self.dataset.get_genealogy()) > 1:
                    parent_key = " (via " + self.dataset.get_genealogy()[0].key + ")"
                else:
                    parent_key = ""

                print("Processor %s raised %s while processing dataset %s%s in %s:\n   %s\n" % (
                    self.type, e.__class__.__name__, self.dataset.key, parent_key, location, str(e)))
                
                # Clean up partially created datasets/files
                self.clean_up_on_error()

                raise ProcessorException("Processor %s raised %s while processing dataset %s%s in %s:\n   %s\n" % (
                    self.type, e.__class__.__name__, self.dataset.key, parent_key, location, str(e)), frame=stack)
        else:
            # dataset already finished, job shouldn't be open anymore
            self.log.warning("Job %s/%s was queued for a dataset already marked as finished, deleting..." % (
            self.job.data["jobtype"], self.job.data["remote_id"]))
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
                available_processors = self.dataset.get_available_processors(config=self.config)
            except ValueError:
                self.log.info("Trying to queue next processor, but parent dataset no longer exists, halting")
                break


            # run it only if the post-processor is actually available for this query
            if self.dataset.data["num_rows"] <= 0:
                can_run_next = False
                self.log.info(
                    "Not running follow-up processor of type %s for dataset %s, no input data for follow-up" % (
                        next_type, self.dataset.key))

            elif next_type in available_processors:
                next_analysis = DataSet(
                    parameters=next_parameters,
                    type=next_type,
                    db=self.db,
                    parent=self.dataset.key,
                    extension=available_processors[next_type].extension,
                    is_private=self.dataset.is_private,
                    owner=self.dataset.creator,
                    modules=self.modules
                )
                # copy ownership from parent dataset
                next_analysis.copy_ownership_from(self.dataset)
                # add to queue
                self.queue.add_job(next_type, remote_id=next_analysis.key)
            else:
                can_run_next = False
                self.log.warning("Dataset %s (of type %s) wants to run processor %s next, but it is incompatible" % (
                self.dataset.key, self.type, next_type))

            if not can_run_next:
                # We are unable to continue the chain of processors, so we check to see if we are attaching to a parent
                # preset; this allows the parent (for example a preset) to be finished and any successful processors displayed
                if "attach_to" in self.parameters:
                    # Probably should not happen, but for some reason a mid processor has been designated as the processor
                    # the parent should attach to
                    pass
                else:
                    # Check for "attach_to" parameter in descendents
                    while True:
                        if "attach_to" in next_parameters:
                            self.parameters["attach_to"] = next_parameters["attach_to"]
                            break
                        else:
                            if "next" in next_parameters:
                                next_parameters = next_parameters["next"][0]["parameters"]
                            else:
                                # No more descendents
                                # Should not happen; we cannot find the source dataset
                                self.log.warning(
                                    "Cannot find preset's source dataset for dataset %s" % self.dataset.key)
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
                surrogate = DataSet(key=self.parameters["attach_to"], db=self.db, modules=self.modules)

                if self.dataset.get_results_path().exists():
                    # Update the surrogate's results file suffix to match this dataset's suffix
                    surrogate.data["result_file"] = surrogate.get_results_path().with_suffix(
                        self.dataset.get_results_path().suffix)
                    shutil.copyfile(str(self.dataset.get_results_path()), str(surrogate.get_results_path()))

                try:
                    surrogate.finish(self.dataset.data["num_rows"])
                except RuntimeError:
                    # already finished, could happen (though it shouldn't)
                    pass

                surrogate.update_status(self.dataset.get_status())

            except DataSetException:
                # dataset with key to attach to doesn't exist...
                self.log.warning("Cannot attach dataset chain containing %s to %s (dataset does not exist, may have "
                                 "been deleted in the meantime)" % (self.dataset.key, self.parameters["attach_to"]))

        self.job.finish()

        if self.config.get('mail.server') and self.dataset.get_parameters().get("email-complete", False):
            owner = self.dataset.get_parameters().get("email-complete", False)
            # Check that username is email address
            if re.match(r"[^@]+\@.*?\.[a-zA-Z]+", owner):
                from email.mime.multipart import MIMEMultipart
                from email.mime.text import MIMEText
                from smtplib import SMTPException
                import socket
                import html2text

        if self.config.get('mail.server') and self.dataset.get_parameters().get("email-complete", False):
            owner = self.dataset.get_parameters().get("email-complete", False)
            # Check that username is email address
            if re.match(r"[^@]+\@.*?\.[a-zA-Z]+", owner):
                from email.mime.multipart import MIMEMultipart
                from email.mime.text import MIMEText
                from smtplib import SMTPException
                import socket
                import html2text

                self.log.debug("Sending email to %s" % owner)
                dataset_url = ('https://' if self.config.get('flask.https') else 'http://') + self.config.get('flask.server_name') + '/results/' + self.dataset.key
                sender = self.config.get('mail.noreply')
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
                    send_email([owner], message, self.config)
                except (SMTPException, ConnectionRefusedError, socket.timeout):
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

    def clean_up_on_error(self):
        try:
            # ensure proxied requests are stopped
            self.flush_proxied_requests()
            # delete annotations that have been generated as part of this processor
            self.db.delete("annotations", where={"from_dataset": self.dataset.key}, commit=True)
            # remove any result files that have been created so far
            self.remove_files()
        except Exception as e:
            self.log.error("Error during processor cleanup after error: %s" % str(e))

    def abort(self):
        """
        Abort dataset creation and clean up so it may be attempted again later
        """
        self.clean_up_on_error()

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

    def iterate_proxied_requests(self, urls, preserve_order=True, **kwargs):
        """
        Request an iterable of URLs and return results

        This method takes an iterable yielding URLs and yields the result for
        a GET request for that URL in return. This is done through the worker
        manager's DelegatedRequestHandler, which can run multiple requests in
        parallel and divide them over the proxies configured in 4CAT (if any).
        Proxy cooloff and queueing is shared with other processors, so that a
        processor will never accidentally request from the same site as another
        processor, potentially triggering rate limits.

        :param urls:  Something that can be iterated over and yields URLs
        :param kwargs:  Other keyword arguments are passed on to `add_urls`
        and eventually to `requests.get()`.
        :param bool preserve_order:  Return items in the original order. Use
        `False` to potentially speed up processing, if order is not important.
        :return:  A generator yielding request results, i.e. tuples of a
        URL and a `requests` response objects
        """
        queue_name = self._proxy_queue_name()
        delegator = self.manager.proxy_delegator

        delegator.refresh_settings(self.config)

        # 50 is an arbitrary batch size - but we top up every 0.05s, so
        # that should be sufficient
        batch_size = 50

        # we need an iterable, so we can use next() and StopIteration
        urls = iter(urls)

        have_urls = True
        while (queue_length := delegator.get_queue_length(queue_name)) > 0 or have_urls:
            if queue_length < batch_size and have_urls:
                batch = []
                while len(batch) < (batch_size - queue_length):
                    try:
                        batch.append(next(urls))
                    except StopIteration:
                        have_urls = False
                        break

                delegator.add_urls(batch, queue_name, **kwargs)

            time.sleep(0.05)  # arbitrary...
            for url, result in delegator.get_results(queue_name, preserve_order=preserve_order):
                # result may also be a FailedProxiedRequest!
                # up to the processor to decide how to deal with it
                yield url, result

    def push_proxied_request(self, url, position=-1, **kwargs):
        """
        Add a single URL to the proxied requests queue

        :param str url:  URL to add
        :param position:  Position to add to queue; can be used to add priority
        requests, adds to end of queue by default
        :param kwargs:
        """
        self.manager.proxy_delegator.add_urls([url], self._proxy_queue_name(), position=position, **kwargs)

    def flush_proxied_requests(self):
        """
        Get rid of remaining proxied requests

        Can be used if enough results are available and any remaining ones need
        to be stopped ASAP and are otherwise unneeded.

        Blocking!
        """
        self.manager.proxy_delegator.halt_and_wait(self._proxy_queue_name())

    def _proxy_queue_name(self):
        """
        Get proxy queue name

        For internal use.

        :return str:
        """
        return f"{self.type}-{self.dataset.key}"

    def iterate_archive_contents(self, path, staging_area=None, immediately_delete=True, filename_filter=[]):
        """
        A generator that iterates through files in an archive

        With every iteration, the processor's 'interrupted' flag is checked,
        and if set a ProcessorInterruptedException is raised, which by default
        is caught and subsequently stops execution gracefully.

        Files are temporarily unzipped and deleted after use.

        :param Path path:     Path to zip file to read
        :param Path staging_area:  Where to store the files while they're
          being worked with. If omitted, a temporary folder is created and
          deleted after use
        :param bool immediately_delete:  Temporary files are removed after yielded;
          False keeps files until the staging_area is removed (usually during processor
          cleanup)
        :param list filename_filter:  Whitelist of filenames to iterate.
        Other files will be ignored. If empty, do not ignore anything.
        :return:  An iterator with a Path item for each file
        """

        if not path.exists():
            return

        if not staging_area:
            staging_area = self.dataset.get_staging_area()

        if not staging_area.exists() or not staging_area.is_dir():
            raise RuntimeError("Staging area %s is not a valid folder")

        with zipfile.ZipFile(path, "r") as archive_file:
            # sorting is important because it ensures .metadata.json is read
            # first
            archive_contents = sorted(archive_file.namelist())

            for archived_file in archive_contents:
                if filename_filter and archived_file not in filename_filter:
                    continue

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

        :param Path path:     Path to zip file to read
        :param Path staging_area:  Where to store the files while they're
          being worked with. If omitted, a temporary folder is created and
          deleted after use
        :param int max_number_files:  Maximum number of files to unpack. If None, all files unpacked
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

    def extract_archived_file_by_name(self, filename, archive_path, staging_area=None):
        """
        Extract a file from an archive by name

        :param str filename:  Name of file to extract
        :param Path archive_path:  Path to zip file to read
        :param Path staging_area:  Where to store the files while they're
                  being worked with. If omitted, a temporary folder is created
        :return Path:  A path to the extracted file
        """
        if not archive_path.exists():
            return

        if not staging_area:
            staging_area = self.dataset.get_staging_area()

        if not staging_area.exists() or not staging_area.is_dir():
            raise RuntimeError("Staging area %s is not a valid folder")

        with zipfile.ZipFile(archive_path, "r") as archive_file:
            if filename not in archive_file.namelist():
                raise FileNotFoundError("File %s not found in archive %s" % (filename, archive_path))
            else:
                archive_file.extract(filename, staging_area)
                return staging_area.joinpath(filename)

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

    def write_archive_and_finish(self, files, num_items=None, compression=zipfile.ZIP_STORED, finish=True):
        """
        Archive a bunch of files into a zip archive and finish processing

        :param list|Path files: If a list, all files will be added to the
          archive and deleted afterwards. If a folder, all files in the folder
          will be added and the folder will be deleted afterwards.
        :param int num_items: Items in the dataset. If None, the amount of
          files added to the archive will be used.
        :param int compression:  Type of compression to use. By default, files
          are not compressed, to speed up unarchiving.
        :param bool finish:  Finish the dataset/job afterwards or not?
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

        if finish:
            self.dataset.finish(num_items)

    def create_standalone(self, item_ids=None):
        """
        Copy this dataset and make that copy standalone.

        This has the benefit of allowing for all analyses that can be run on
        full datasets on the new, filtered copy as well.
        
        This also transfers annotations and annotation fields.

        :param list item_ids:   The item_ids that are copied-over. Used to check what annotations need to be copied.

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

        if top_parent.annotation_fields and top_parent.num_annotations() > 0:
            # Get column names dynamically
            annotation_cols = self.db.fetchone("SELECT * FROM annotations LIMIT 1")
            annotation_cols = list(annotation_cols.keys())
            annotation_cols.remove("id")  # Set by the DB
            cols_str = ",".join(annotation_cols)

            cols_list = ["a." + col for col in annotation_cols if col != "dataset"]
            query = f"INSERT INTO annotations ({cols_str}) OVERRIDING USER VALUE " \
                    f"SELECT %s, {', '.join(cols_list)} " \
                    f"FROM annotations AS a WHERE a.dataset = %s"

            # Copy over all annotations if no item_ids are given
            if not item_ids or top_parent.num_rows == standalone.num_rows:
                self.db.execute(query, replacements=(standalone.key, top_parent.key))
            else:
                query += " AND a.item_id = ANY(%s)"
                self.db.execute(query, replacements=(standalone.key, top_parent.key, item_ids))

        # Copy over annotation fields and update annotations with new field IDs
        if top_parent.annotation_fields:
            # New field IDs based on the new dataset key
            annotation_fields = {
                hash_to_md5(old_field_id + standalone.key): field_values
                for old_field_id, field_values in top_parent.annotation_fields.items()
            }
            standalone.annotation_fields = {}  # Reset to insert everything without checking for changes
            standalone.save_annotation_fields(annotation_fields)  # Save to db

            # Also update field IDs in annotations
            for i, old_field_id in enumerate(top_parent.annotation_fields.keys()):
                self.db.update(
                    "annotations",
                    where={"field_id": old_field_id, "dataset": standalone.key},
                    data={"field_id": hash_to_md5(old_field_id + standalone.key)
                })

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

    def save_annotations(self, annotations: list, source_dataset=None, hide_in_explorer=False) -> int:
        """
        Saves annotations made by this processor on the basis of another dataset.
        Also adds some data regarding this processor: set `author` and `label` to processor name,
        and add parameters to `metadata` (unless explicitly indicated).

        :param annotations:				List of dictionaries with annotation items. Must have `item_id` and `value`.
                                        E.g. [{"item_id": "12345", "label": "Valid", "value": "Yes"}]
        :param source_dataset:			The dataset that these annotations will be saved on. If None, will use the
                                        top parent.
        :param bool hide_in_explorer:	Whether this annotation is included in the Explorer. 'Hidden' annotations
                                        are still shown in `iterate_items()`).

        :returns int:					How many annotations were saved.

        """

        if not annotations:
            return 0

        # Default to parent dataset
        if not source_dataset:
            source_dataset = self.source_dataset.top_parent()

        # Check if this dataset already has annotation fields, and if so, store some values to use per annotation.
        annotation_fields = source_dataset.annotation_fields

        # Keep track of what fields we've already seen, so we don't need to hash every time.
        seen_fields = {(field_items["from_dataset"], field_items["label"]): field_id
                       for field_id, field_items in annotation_fields.items() if "from_dataset" in field_items}

        # Loop through all annotations. This may be batched.
        for annotation in annotations:

            # Keep track of what dataset generated this annotation
            annotation["from_dataset"] = self.dataset.key
            # Set the author to this processor's name
            if not annotation.get("author"):
                annotation["author"] = self.name
            if not annotation.get("author_original"):
                annotation["author_original"] = self.name
            annotation["by_processor"] = True

            # Only use a default label if no custom one is given
            if not annotation.get("label"):
                annotation["label"] = self.name

            # Store info on the annotation field if this from_dataset/label combo hasn't been seen yet.
            # We need to do this within this loop because this function may be called in batches and with different
            # annotation types.
            if (annotation["from_dataset"], annotation["label"]) not in seen_fields:
                # Generating a unique field ID based on the source dataset's key, the label, and this dataset's key.
                # This should create unique fields, even if there's multiple annotation types for one processor.
                field_id = hash_to_md5(self.source_dataset.key + annotation["label"] + annotation["from_dataset"])
                seen_fields[(annotation["from_dataset"], annotation["label"])] = field_id
                annotation_fields[field_id] = {
                    "label": annotation["label"],
                    "type": annotation["type"] if annotation.get("type") else "text",
                    "from_dataset": annotation["from_dataset"],
                    "hide_in_explorer": hide_in_explorer
                }
            else:
                # Else just get the field ID
                field_id = seen_fields[(annotation["from_dataset"], annotation["label"])]

            # Add field ID to the annotation
            annotation["field_id"] = field_id

        annotations_saved = source_dataset.save_annotations(annotations)
        source_dataset.save_annotation_fields(annotation_fields)

        return annotations_saved

    @classmethod
    def map_item_method_available(cls, dataset):
        """
        Check if this processor can use map_item

        Checks if map_item method exists and is compatible with dataset. If
        dataset has a different extension than the default for this processor,
        or if the dataset has no extension, this means we cannot be sure the
        data is in the right format to be mapped, so `False` is returned in
        that case even if a map_item() method is available.

        :param BasicProcessor processor:    The BasicProcessor subclass object
        with which to use map_item
        :param DataSet dataset:                The DataSet object with which to
        use map_item
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
    def get_options(cls, parent_dataset=None, config=None) -> dict:
        """
        Get processor options

        This method by default returns the class's "options" attribute, or an
        empty dictionary. It can be redefined by processors that need more
        fine-grained options, e.g. in cases where the availability of options
        is partially determined by the parent dataset's parameters.

        :param parent_dataset DataSet:  An object representing the dataset that
            the processor would be or was run on. Can be used, in conjunction with
            config, to show some options only to privileged users.
        :param config ConfigManager|None config:  Configuration reader (context-aware)
        :return dict:   Options for this processor
        """

        return cls.options if hasattr(cls, "options") else {}

    @classmethod
    def get_status(cls):
        """
        Get processor status

        :return list:    Statuses of this processor
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
    def exclude_followup_processors(cls, processor_type=None):
        """
        Used for processor compatibility

        To be defined by the child processor if it should exclude certain follow-up processors.
        e.g.:

        def exclude_followup_processors(cls, processor_type):
            if processor_type in ["undesirable-followup-processor"]:
                return True
            return False

        :param str processor_type:  Processor type to exclude
        :return bool:  True if processor should be excluded, False otherwise
        """
        return False

    @abc.abstractmethod
    def process(self):
        """
        Process data

        To be defined by the child processor.
        """
        pass

    @staticmethod
    def is_4cat_processor():
        """
        Is this a 4CAT processor?

        This is used to determine whether a class is a 4CAT
        processor.

        :return:  True
        """
        return True
