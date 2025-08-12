"""
Import datasets from other 4CATs
"""
import requests
import json
import time
import zipfile
from pathlib import Path

from backend.lib.processor import BasicProcessor
from common.lib.exceptions import (QueryParametersException, FourcatException, ProcessorInterruptedException,
                                   DataSetException)
from common.lib.helpers import UserInput, get_software_version
from common.lib.dataset import DataSet


class FourcatImportException(FourcatException):
    pass


class SearchImportFromFourcat(BasicProcessor):
    type = "import_4cat-search"  # job ID
    category = "Search"  # category
    title = "Import 4CAT dataset and analyses"  # title displayed in UI
    description = "Import a dataset from another 4CAT server or from a zip file (exported from a 4CAT server)"  # description displayed in UI
    is_local = False  # Whether this datasource is locally scraped
    is_static = False  # Whether this datasource is still updated

    max_workers = 1  # this cannot be more than 1, else things get VERY messy

    options = {
        "intro": {
            "type": UserInput.OPTION_INFO,
            "help": "Provide the URL of a dataset in another 4CAT server that you would like to copy to this one here. "
                    "\n\nTo import a dataset across servers, both servers need to be running the same version of 4CAT. "
                    "You can find the current version in the footer at the bottom of the interface."
        },
        "method": {
            "type": UserInput.OPTION_CHOICE,
            "help": "Import Type",
            "options": {
                "zip": "Zip File",
                "url": "4CAT URL",
            },
            "default": "url"
        },
        "url": {
            "type": UserInput.OPTION_TEXT,
            "help": "Dataset URL",
            "tooltip": "URL to the dataset's page, for example https://4cat.example/results/28da332f8918e6dc5aacd1c3b0170f01b80bd95f8ff9964ac646cecd33bfee49/.",
            "requires": "method^=url"
        },
        "intro2": {
            "type": UserInput.OPTION_INFO,
            "help": "You can create an API key via the 'API Access' item in 4CAT's navigation menu. Note that you need "
                    "an API key from **the server you are importing from**, not the one you are looking at right now. "
                    "Additionally, you need to have owner access to the dataset you want to import.",
            "requires": "method^=url"
        },
        "api-key": {
            "type": UserInput.OPTION_TEXT,
            "help": "4CAT API Key",
            "sensitive": True,
            "cache": True,
            "requires": "method^=url"
        },
        "data_upload": {
            "type": UserInput.OPTION_FILE,
            "help": "File",
            "tooltip": "Upload a ZIP file containing a dataset exported from a 4CAT server.",
            "requires": "method^=zip"
        },

    }

    created_datasets = None
    base = None
    remapped_keys = None
    dataset_owner = None

    def process(self):
        """
        Import 4CAT dataset either from another 4CAT server or from the uploaded zip file
        """
        self.created_datasets = set()  # keys of created datasets - may not be successful!
        self.remapped_keys = {}  # changed dataset keys
        self.dataset_owner = self.dataset.get_owners()[0]  # at this point it has 1 owner
        try:
            if self.parameters.get("method") == "zip":
                self.process_zip()
            else:
                self.process_urls()
        except Exception as e:
            # Catch all exceptions and finish the job with an error
            # Resuming is impossible because this dataset was overwritten with the importing dataset
            # halt_and_catch_fire() will clean up and delete the datasets that were created
            self.interrupted = True
            try:
                self.halt_and_catch_fire()
            except ProcessorInterruptedException:
                pass
            # Reraise the original exception for logging
            raise e

    def after_create(query, dataset, request):
        """
        Hook to execute after the dataset for this source has been created

        In this case, put the file in a temporary location so it can be
        processed properly by the related Job later.

        :param dict query:  Sanitised query parameters
        :param DataSet dataset:  Dataset created for this query
        :param request:  Flask request submitted for its creation
        """
        if query.get("method") == "zip":
            file = request.files["option-data_upload"]
            file.seek(0)
            with dataset.get_results_path().with_suffix(".importing").open("wb") as outfile:
                while True:
                    chunk = file.read(1024)
                    if len(chunk) == 0:
                        break
                    outfile.write(chunk)
        else:
            # nothing to do for URLs
            pass


    def process_zip(self):
        """
        Import 4CAT dataset from a ZIP file
        """
        self.dataset.update_status("Importing datasets and analyses from ZIP file.")
        temp_file = self.dataset.get_results_path().with_suffix(".importing")

        imported = []
        processed_files = 1 # take into account the export.log file
        failed_imports = []
        primary_dataset_original_log = None
        with zipfile.ZipFile(temp_file, "r") as zip_ref:
            zip_contents = zip_ref.namelist()

            # Get all metadata files and determine primary dataset
            metadata_files = [file for file in zip_contents if file.endswith("_metadata.json")]
            if not metadata_files:
                self.dataset.finish_with_error("No metadata files found in ZIP file; is this a 4CAT export?")
                return

            # Get the primary dataset
            primary_dataset_keys = set()
            datasets = []
            parent_child_mapping = {}
            for file in metadata_files:
                with zip_ref.open(file) as f:
                    content = f.read().decode('utf-8')  # Decode the binary content using the desired encoding
                    metadata = json.loads(content)
                    if not metadata.get("key_parent"):
                        primary_dataset_keys.add(metadata.get("key"))
                        datasets.append(metadata)
                    else:
                        # Store the mapping of parent to child datasets
                        parent_key = metadata.get("key_parent")
                        if parent_key not in parent_child_mapping:
                            parent_child_mapping[parent_key] = []
                        parent_child_mapping[parent_key].append(metadata)

            # Primary dataset will overwrite this dataset; we could address this to support multiple primary datasets
            if len(primary_dataset_keys) != 1:
                self.dataset.finish_with_error("ZIP file contains multiple primary datasets; only one is allowed.")
                return

            # Import datasets
            while datasets:
                self.halt_and_catch_fire()

                # Create the datasets
                metadata = datasets.pop(0)
                dataset_key = metadata.get("key")
                processed_metadata = self.process_metadata(metadata)
                new_dataset = self.create_dataset(processed_metadata, dataset_key, dataset_key in primary_dataset_keys)
                processed_files += 1

                # Copy the log file
                self.halt_and_catch_fire()
                log_filename = Path(metadata["result_file"]).with_suffix(".log").name
                if log_filename in zip_contents:
                    self.dataset.update_status(f"Transferring log file for dataset {new_dataset.key}")
                    with zip_ref.open(log_filename) as f:
                        content = f.read().decode('utf-8')
                        if new_dataset.key == self.dataset.key:
                            # Hold the original log for the primary dataset and add at the end
                            primary_dataset_original_log = content
                        else:
                            new_dataset.log("Original dataset log included below:")
                            with new_dataset.get_log_path().open("a") as outfile:
                                outfile.write(content)
                    processed_files += 1
                else:
                    self.dataset.log(f"Log file not found for dataset {new_dataset.key} (original key {dataset_key}).")

                # Copy the results
                self.halt_and_catch_fire()
                results_filename = metadata["result_file"]
                if results_filename in zip_contents:
                    self.dataset.update_status(f"Transferring data file for dataset {new_dataset.key}")
                    with zip_ref.open(results_filename) as f:
                        with new_dataset.get_results_path().open("wb") as outfile:
                            outfile.write(f.read())
                    processed_files += 1

                    if not imported:
                        # first dataset - use num rows as 'overall'
                        num_rows = metadata["num_rows"]
                else:
                    self.dataset.log(f"Results file not found for dataset {new_dataset.key} (original key {dataset_key}).")
                    new_dataset.finish_with_error(f"Results file not found for dataset {new_dataset.key} (original key {dataset_key}).")
                    failed_imports.append(dataset_key)
                    continue

                # finally, the kids
                self.halt_and_catch_fire()
                if dataset_key in parent_child_mapping:
                    datasets.extend(parent_child_mapping[dataset_key])
                    self.dataset.log(f"Adding ({len(parent_child_mapping[dataset_key])}) child datasets to import queue")

                # done - remember that we've imported this one
                imported.append(new_dataset)
                new_dataset.update_status(metadata["status"])

                if new_dataset.key != self.dataset.key:
                    # only finish if this is not the 'main' dataset, or the user
                    # will think the whole import is done
                    new_dataset.finish(metadata["num_rows"])

            # Check that all files were processed
            missed_files = []
            if len(zip_contents) != processed_files:
                for file in zip_contents:
                    if file not in processed_files:
                        missed_files.append(file)

            # todo: this part needs updating if/when we support importing multiple datasets!
            if failed_imports:
                self.dataset.update_status(f"Dataset import finished, but not all data was imported properly. "
                                           f"{len(failed_imports)} dataset(s) were not successfully imported. Check the "
                                           f"dataset log file for details.", is_final=True)
            elif missed_files:
                self.dataset.log(f"ZIP file contained {len(missed_files)} files that were not processed: {missed_files}")
                self.dataset.update_status(f"Dataset import finished, but not all files were processed. "
                                           f"{len(missed_files)} files were not successfully imported. Check the "
                                           f"dataset log file for details.", is_final=True)
            else:
                self.dataset.update_status(f"{len(imported)} dataset(s) succesfully imported.",
                                           is_final=True)

            if not self.dataset.is_finished():
                # now all related datasets are imported, we can finish the 'main'
                # dataset, and the user will be alerted that the full import is
                # complete
                self.dataset.finish(num_rows)

            # Add the original log for the primary dataset
            if primary_dataset_original_log:
                self.dataset.log("Original dataset log included below:\n")
                with self.dataset.get_log_path().open("a") as outfile:
                    outfile.write(primary_dataset_original_log)


    @staticmethod
    def process_metadata(metadata):
        """
        Process metadata for import
        """
        # get rid of some keys that are server-specific and don't need to
        # be stored (or don't correspond to database columns)
        metadata.pop("current_4CAT_version")
        metadata.pop("id")
        metadata.pop("job")
        metadata.pop("is_private")
        metadata.pop("is_finished")  # we'll finish it ourselves, thank you!!!

        # extra params are stored as JSON...
        metadata["parameters"] = json.loads(metadata["parameters"])
        if "copied_from" in metadata["parameters"]:
            metadata["parameters"].pop("copied_from")
        metadata["parameters"] = json.dumps(metadata["parameters"])

        return metadata

    def create_dataset(self, metadata, original_key, primary=False):
        """
        Create a new dataset
        """
        if primary:
            self.dataset.update_status(f"Importing primary dataset {original_key}.")
            # if this is the first dataset we're importing, make it the
            # processor's "own" dataset. the key has already been set to
            # the imported dataset's key via ensure_key() (or a new unqiue
            # key if it already existed on this server)
            # by making it the "own" dataset, the user initiating the
            # import will see the imported dataset as the "result" of their
            # import query in the interface, similar to the workflow for
            # other data sources
            new_dataset = self.dataset

            # Update metadata and file
            metadata.pop("key")  # key already OK (see above)
            self.db.update("datasets", where={"key": new_dataset.key}, data=metadata)

        else:
            self.dataset.update_status(f"Importing child dataset {original_key}.")
            # supernumerary datasets - handle on their own
            # these include any children of imported datasets
            try:
                DataSet(key=metadata["key"], db=self.db, modules=self.modules)

                # if we *haven't* thrown a DatasetException now, then the
                # key is already in use, so create a "dummy" dataset and
                # overwrite it with the metadata we have (except for the
                # key). this ensures that a new unique key will be
                # generated.
                new_dataset = DataSet(parameters={}, type=self.type, db=self.db, modules=self.modules)
                metadata.pop("key")
                self.db.update("datasets", where={"key": new_dataset.key}, data=metadata)

            except DataSetException:
                # this is *good* since it means the key doesn't exist, so
                # we can re-use the key of the imported dataset
                self.db.insert("datasets", data=metadata)
                new_dataset = DataSet(key=metadata["key"], db=self.db, modules=self.modules)

        if new_dataset.key != original_key:
            # could not use original key because it was already in use
            # so update any references to use the new key
            self.remapped_keys[original_key] = new_dataset.key
            self.dataset.update_status(f"Cannot import with same key - already in use on this server. Using key "
                                      f"{new_dataset.key} instead of key {original_key}!")

        # refresh object, make sure it's in sync with the database
        self.created_datasets.add(new_dataset.key)
        new_dataset = DataSet(key=new_dataset.key, db=self.db, modules=self.modules)
        current_log = None
        if new_dataset.key == self.dataset.key:
            # this ensures that the first imported dataset becomes the
            # processor's "own" dataset, and that the import logs go to
            # that dataset's log file. For later imports, this evaluates to
            # False.

            # Read the current log and store it; it needs to be after the result_file is updated (as it is used to determine the log file path)
            current_log = self.dataset.get_log_path().read_text()
            # Update the dataset
            self.dataset = new_dataset

        # if the key of the parent dataset was changed, change the
        # reference to it that the child dataset has
        if new_dataset.key_parent and new_dataset.key_parent in self.remapped_keys:
            new_dataset.key_parent = self.remapped_keys[new_dataset.key_parent]

        # update some attributes that should come from the new server, not
        # the old
        new_dataset.creator = self.dataset_owner
        new_dataset.original_timestamp = new_dataset.timestamp
        new_dataset.imported = True
        new_dataset.timestamp = int(time.time())
        new_dataset.db.commit()

        # make sure the dataset path uses the new key and local dataset
        # path settings. this also makes sure the log file is created in
        # the right place (since it is derived from the results file path)
        extension = metadata["result_file"].split(".")[-1]
        updated = new_dataset.reserve_result_file(parameters=new_dataset.parameters, extension=extension)
        if not updated:
            self.dataset.log(f"Could not reserve result file for {new_dataset.key}!")

        if current_log:
            # Add the current log to the new dataset
            with new_dataset.get_log_path().open("a") as outfile:
                outfile.write(current_log)

        return new_dataset


    def process_urls(self):
        """
        Import 4CAT dataset from another 4CAT server

        Interfaces with another 4CAT server to transfer a dataset's metadata,
        data files and child datasets.
        """
        urls = [url.strip() for url in self.parameters.get("url").split(",")]
        self.base = urls[0].split("/results/")[0]
        keys = SearchImportFromFourcat.get_keys_from_urls(urls)
        api_key = self.parameters.get("api-key")

        imported = []  # successfully imported datasets
        failed_imports = []  # keys that failed to import
        num_rows = 0  # will be used later

        # we can add support for multiple datasets later by removing
        # this part!
        keys = [keys[0]]

        while keys:
            dataset_key = keys.pop(0)

            self.halt_and_catch_fire()
            self.dataset.log(f"Importing dataset {dataset_key} from 4CAT server {self.base}.")

            # first, metadata!
            try:
                metadata = SearchImportFromFourcat.fetch_from_4cat(self.base, dataset_key, api_key, "metadata")
                metadata = metadata.json()
            except FourcatImportException as e:
                self.dataset.log(f"Error retrieving record for dataset {dataset_key}: {e}")
                continue
            except ValueError:
                self.dataset.log(f"Could not read metadata for dataset {dataset_key}")
                continue

            # copying empty datasets doesn't really make sense
            if metadata["num_rows"] == 0:
                self.dataset.update_status(f"Skipping empty dataset {dataset_key}")
                failed_imports.append(dataset_key)
                continue

            metadata = self.process_metadata(metadata)

            # create the new dataset
            new_dataset = self.create_dataset(metadata, dataset_key, primary=True if not imported else False)

            # then, the log
            self.halt_and_catch_fire()
            try:
                self.dataset.update_status(f"Transferring log file for dataset {new_dataset.key}")
                # TODO: for the primary, this ends up in the middle of the log as we are still adding to it...
                log = SearchImportFromFourcat.fetch_from_4cat(self.base, dataset_key, api_key, "log")
                logpath = new_dataset.get_log_path()
                new_dataset.log("Original dataset log included below:")
                with logpath.open("a") as outfile:
                    outfile.write(log.text)
            except FourcatImportException as e:
                new_dataset.finish_with_error(f"Error retrieving log for dataset {new_dataset.key}: {e}")
                failed_imports.append(dataset_key)
                continue
            except ValueError:
                new_dataset.finish_with_error(f"Could not read log for dataset {new_dataset.key}: skipping dataset")
                failed_imports.append(dataset_key)
                continue

            # then, the results
            self.halt_and_catch_fire()
            try:
                self.dataset.update_status(f"Transferring data file for dataset {new_dataset.key}")
                datapath = new_dataset.get_results_path()
                SearchImportFromFourcat.fetch_from_4cat(self.base, dataset_key, api_key, "data", datapath)

                if not imported:
                    # first dataset - use num rows as 'overall'
                    num_rows = metadata["num_rows"]

            except FourcatImportException as e:
                self.dataset.log(f"Dataset {new_dataset.key} unable to import: {e}, skipping import")
                if new_dataset.key != self.dataset.key:
                    new_dataset.delete()
                continue

            except ValueError:
                new_dataset.finish_with_error(f"Could not read results for dataset {new_dataset.key}")
                failed_imports.append(dataset_key)
                continue

            # finally, the kids
            self.halt_and_catch_fire()
            try:
                self.dataset.update_status(f"Looking for child datasets to transfer for dataset {new_dataset.key}")
                children = SearchImportFromFourcat.fetch_from_4cat(self.base, dataset_key, api_key, "children")
                children = children.json()
            except FourcatImportException as e:
                self.dataset.update_status(f"Error retrieving children for dataset {new_dataset.key}: {e}")
                failed_imports.append(dataset_key)
                continue
            except ValueError:
                self.dataset.update_status(f"Could not collect children for dataset {new_dataset.key}")
                failed_imports.append(dataset_key)
                continue

            for child in children:
                keys.append(child)
                self.dataset.log(f"Adding child dataset {child} to import queue")

            # done - remember that we've imported this one
            imported.append(new_dataset)
            new_dataset.update_status(metadata["status"])

            if new_dataset.key != self.dataset.key:
                # only finish if this is not the 'main' dataset, or the user
                # will think the whole import is done
                new_dataset.finish(metadata["num_rows"])

        # todo: this part needs updating if/when we support importing multiple datasets!
        if failed_imports:
            self.dataset.update_status(f"Dataset import finished, but not all data was imported properly. "
                                       f"{len(failed_imports)} dataset(s) were not successfully imported. Check the "
                                       f"dataset log file for details.", is_final=True)
        else:
            self.dataset.update_status(f"{len(imported)} dataset(s) succesfully imported from {self.base}.",
                                       is_final=True)

        if not self.dataset.is_finished():
            # now all related datasets are imported, we can finish the 'main'
            # dataset, and the user will be alerted that the full import is
            # complete
            self.dataset.finish(num_rows)

    def halt_and_catch_fire(self):
        """
        Clean up on interrupt

        There are multiple places in the code where we can bail out on an
        interrupt, so abstract that away in its own function.
        :return:
        """
        if self.interrupted:
            # resuming is impossible because the original dataset (which
            # has the list of URLs to import) has probably been
            # overwritten by this point
            deletables = [k for k in self.created_datasets if k != self.dataset.key]
            for deletable in deletables:
                DataSet(key=deletable, db=self.db, modules=self.modules).delete()

            self.dataset.finish_with_error(f"Interrupted while importing datasets{' from '+self.base if self.base else ''}. Cannot resume - you "
                                           f"will need to initiate the import again.")

            raise ProcessorInterruptedException()

    @staticmethod
    def fetch_from_4cat(base, dataset_key, api_key, component, datapath=None):
        """
        Get dataset component from 4CAT export API

        :param str base:  Server URL base to import from
        :param str dataset_key:  Key of dataset to import
        :param str api_key:  API authentication token
        :param str component:  Component to retrieve
        :return:  HTTP response object
        """
        try:
            if component == "data" and datapath:
                # Stream data
                with requests.get(f"{base}/api/export-packed-dataset/{dataset_key}/{component}/", timeout=5, stream=True,
                                  headers={
                                            "User-Agent": "4cat/import",
                                            "Authentication": api_key
                                        }) as r:
                    r.raise_for_status()
                    with datapath.open("wb") as outfile:
                        for chunk in r.iter_content(chunk_size=8192):
                            outfile.write(chunk)
                return r
            else:
                response = requests.get(f"{base}/api/export-packed-dataset/{dataset_key}/{component}/", timeout=5, headers={
                    "User-Agent": "4cat/import",
                    "Authentication": api_key
                })
        except requests.Timeout:
            raise FourcatImportException(f"The 4CAT server at {base} took too long to respond. Make sure it is "
                                         f"accessible to external connections and try again.")
        except requests.RequestException as e:
            raise FourcatImportException(f"Could not connect to the 4CAT server at {base} ({e}). Make sure it is "
                                         f"accessible to external connections and try again.")

        if response.status_code == 404:
            raise FourcatImportException(
                f"Dataset {dataset_key} not found at server {base} ({response.text}. Make sure all URLs point to "
                f"a valid dataset.")
        elif response.status_code in (401, 403):
            raise FourcatImportException(
                f"Dataset {dataset_key} not accessible at server {base}. Make sure you have access to this "
                f"dataset and are using the correct API key.")
        elif response.status_code != 200:
            raise FourcatImportException(
                f"Unexpected error while requesting {component} for dataset {dataset_key} from server {base}: {response.text}")

        return response

    @staticmethod
    def validate_query(query, request, config):
        """
        Validate custom data input

        Confirms that the uploaded file is a valid CSV or tab file and, if so, returns
        some metadata.

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param ConfigManager|None config:  Configuration reader (context-aware)
        :return dict:  Safe query parameters
        """
        if query.get("method") == "zip":
            filename = ""
            if "option-data_upload-entries" in request.form:
                # First pass sends list of files in the zip
                pass
            elif "option-data_upload" in request.files:
                # Second pass sends the actual file
                file = request.files["option-data_upload"]
                if not file:
                    raise QueryParametersException("No file uploaded.")

                if not file.filename.endswith(".zip"):
                    raise QueryParametersException("Uploaded file must be a ZIP file.")

                filename = file.filename
            else:
                raise QueryParametersException("No file was offered for upload.")

            return {
                "method": "zip",
                "filename": filename
            }
        elif query.get("method") == "url":
            urls = query.get("url")
            if not urls:
                raise QueryParametersException("Provide at least one dataset URL.")

            urls = urls.split(",")
            bases = set([url.split("/results/")[0].lower() for url in urls])
            keys = SearchImportFromFourcat.get_keys_from_urls(urls)

            if len(keys) != 1:
                # todo: change this to < 1 if we allow multiple datasets
                raise QueryParametersException("You need to provide a single URL to a 4CAT dataset to import.")

            if len(bases) != 1:
                raise QueryParametersException("All URLs need to point to the same 4CAT server. You can only import from "
                                                "one 4CAT server at a time.")

            base = urls[0].split("/results/")[0]
            try:
                # test if API key is valid and server is reachable
                test = SearchImportFromFourcat.fetch_from_4cat(base, keys[0], query.get("api-key"), "metadata")
            except FourcatImportException as e:
                raise QueryParametersException(str(e))

            try:
                # test if we get a response we can parse
                metadata = test.json()
            except ValueError:
                raise QueryParametersException(f"Unexpected response when trying to fetch metadata for dataset {keys[0]}.")

            version = get_software_version()

            if metadata.get("current_4CAT_version") != version:
                raise QueryParametersException(f"This 4CAT server is running a different version of 4CAT ({version}) than "
                                               f"the one you are trying to import from ({metadata.get('current_4CAT_version')}). Make "
                                               "sure both are running the same version of 4CAT and try again.")

            # OK, we can import at least one dataset
            return {
                "url": ",".join(urls),
                "api-key": query.get("api-key")
            }
        else:
            raise QueryParametersException("Import method not yet implemented.")

    @staticmethod
    def get_keys_from_urls(urls):
        """
        Get dataset keys from 4CAT URLs

        :param list urls:  List of URLs
        :return list:  List of keys
        """
        return [url.split("/results/")[-1].split("/")[0].split("#")[0].split("?")[0] for url in urls]

    @staticmethod
    def ensure_key(query):
        """
        Determine key for dataset generated by this processor

        When importing datasets, it's necessary to determine the key of the
        dataset that is created before it is actually created, because we want
        to keep the original key of the imported dataset if possible. Luckily,
        we can deduce it from the URL we're importing the dataset from.

        :param dict query:  Input from the user, through the front-end
        :return str:  Desired dataset key
        """
        #TODO: Can this be done for the zip method as well? The original keys are in the zip file; we save them after
        # this method is called via `after_create`. We could download here and also identify the primary dataset key...
        urls = query.get("url", "").split(",")
        keys = SearchImportFromFourcat.get_keys_from_urls(urls)
        return keys[0]


