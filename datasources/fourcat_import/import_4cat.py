"""
Import datasets from other 4CATs
"""
import requests
import json
import time

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
    title = "Import from 4CAT"  # title displayed in UI
    description = "Import a dataset from another 4CAT server"  # description displayed in UI
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
        "url": {
            "type": UserInput.OPTION_TEXT,
            "help": "Dataset URL",
            "tooltip": "URL to the dataset's page, for example https://4cat.example/results/28da332f8918e6dc5aacd1c3b0170f01b80bd95f8ff9964ac646cecd33bfee49/."
        },
        "intro2": {
            "type": UserInput.OPTION_INFO,
            "help": "You can create an API key via the 'API Access' item in 4CAT's navigation menu. Note that you need "
                    "an API key from **the server you are importing from**, not the one you are looking at right now. "
                    "Additionally, you need to have owner access to the dataset you want to import."
        },
        "api-key": {
            "type": UserInput.OPTION_TEXT,
            "help": "4CAT API Key",
            "sensitive": True,
            "cache": True,
        }
    }

    created_datasets = None
    base = None

    def process(self):
        """
        Import 4CAT dataset from another 4CAT server

        Interfaces with another 4CAT server to transfer a dataset's metadata,
        data files and child datasets.
        """
        urls = [url.strip() for url in self.parameters.get("url").split(",")]
        self.base = urls[0].split("/results/")[0]
        keys = SearchImportFromFourcat.get_keys_from_urls(urls)
        api_key = self.parameters.get("api-key")

        self.created_datasets = set()   # keys of created datasets - may not be successful!
        imported = []  # successfully imported datasets
        failed_imports = []  # keys that failed to import
        remapped_keys = {}  # changed dataset keys
        num_rows = 0  # will be used later
        dataset_owner = self.dataset.get_owners()[0]  # at this point it has 1 owner

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

            if not imported:
                # if this is the first dataset we're importing, make it the
                # processor's "own" dataset. the key has already been set to
                # the imported dataset's key via ensure_key() (or a new unqiue
                # key if it already existed on this server)
                # by making it the "own" dataset, the user initiating the
                # import will see the imported dataset as the "result" of their
                # import query in the interface, similar to the workflow for
                # other data sources
                new_dataset = self.dataset
                metadata.pop("key")  # key already OK (see above)
                self.db.update("datasets", where={"key": new_dataset.key}, data=metadata)

            else:
                # supernumerary datasets - handle on their own
                # these include any children of imported datasets
                try:
                    key_exists = DataSet(key=metadata["key"], db=self.db)

                    # if we *haven't* thrown a DatasetException now, then the
                    # key is already in use, so create a "dummy" dataset and
                    # overwrite it with the metadata we have (except for the
                    # key). this ensures that a new unique key will be
                    # generated.
                    new_dataset = DataSet(parameters={}, type=self.type, db=self.db)
                    metadata.pop("key")
                    self.db.update("datasets", where={"key": new_dataset.key}, data=metadata)

                except DataSetException:
                    # this is *good* since it means the key doesn't exist, so
                    # we can re-use the key of the imported dataset
                    self.db.insert("datasets", data=metadata)
                    new_dataset = DataSet(key=metadata["key"], db=self.db)

            # make sure the dataset path uses the new key and local dataset
            # path settings. this also makes sure the log file is created in
            # the right place (since it is derived from the results file path)
            extension = metadata["result_file"].split(".")[-1]
            new_dataset.reserve_result_file(parameters=new_dataset.parameters, extension=extension)

            new_dataset.update_status("Imported dataset created")
            if new_dataset.key != dataset_key:
                # could not use original key because it was already in use
                # so update any references to use the new key
                remapped_keys[dataset_key] = new_dataset.key
                new_dataset.update_status(f"Cannot import with same key - already in use on this server. Using key "
                                f"{new_dataset.key} instead of key {dataset_key}!")

            # refresh object, make sure it's in sync with the database
            self.created_datasets.add(new_dataset.key)
            new_dataset = DataSet(key=new_dataset.key, db=self.db)
            if new_dataset.key == self.dataset.key:
                # this ensures that the first imported dataset becomes the
                # processor's "own" dataset, and that the import logs go to
                # that dataset's log file. For later imports, this evaluates to
                # False.
                self.dataset = new_dataset

            # if the key of the parent dataset was changed, change the
            # reference to it that the child dataset has
            if new_dataset.key_parent and new_dataset.key_parent in remapped_keys:
                new_dataset.key_parent = remapped_keys[new_dataset.key_parent]

            # update some attributes that should come from the new server, not
            # the old
            new_dataset.creator = dataset_owner
            new_dataset.original_timestamp = new_dataset.timestamp
            new_dataset.imported = True
            new_dataset.timestamp = int(time.time())
            new_dataset.db.commit()

            # then, the log
            self.halt_and_catch_fire()
            try:
                self.dataset.update_status(f"Transferring log file for dataset {new_dataset.key}")
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
                data = SearchImportFromFourcat.fetch_from_4cat(self.base, dataset_key, api_key, "data")
                datapath = new_dataset.get_results_path()
                with datapath.open("wb") as outfile:
                    outfile.write(data.content)

                if not imported:
                    # first dataset - use num rows as 'overall'
                    num_rows = metadata["num_rows"]

            except FourcatImportException as e:
                self.dataset.log(f"Dataset {new_dataset.key} does not seem to have a data file, skipping import")
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
                DataSet(key=deletable, db=self.db).delete()

            self.dataset.finish_with_error(f"Interrupted while importing datasets from {self.base}. Cannot resume - you "
                                           f"will need to initiate the import again.")

            raise ProcessorInterruptedException()

    @staticmethod
    def fetch_from_4cat(base, dataset_key, api_key, component):
        """
        Get dataset component from 4CAT export API

        :param str base:  Server URL base to import from
        :param str dataset_key:  Key of dataset to import
        :param str api_key:  API authentication token
        :param str component:  Component to retrieve
        :return:  HTTP response object
        """
        try:
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
        urls = query.get("url")
        if not urls:
            return QueryParametersException("Provide at least one dataset URL.")

        urls = urls.split(",")
        bases = set([url.split("/results/")[0].lower() for url in urls])
        keys = SearchImportFromFourcat.get_keys_from_urls(urls)

        if len(keys) != 1:
            # todo: change this to < 1 if we allow multiple datasets
            return QueryParametersException("You need to provide a single URL to a 4CAT dataset to import.")

        if len(bases) != 1:
            return QueryParametersException("All URLs need to point to the same 4CAT server. You can only import from "
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
        urls = query.get("url", "").split(",")
        keys = SearchImportFromFourcat.get_keys_from_urls(urls)
        return keys[0]


