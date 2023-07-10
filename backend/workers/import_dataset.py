"""
Custom data upload to create bespoke datasets
"""
import requests

from backend.lib.worker import BasicWorker
from common.lib.exceptions import FourcatException, WorkerInterruptedException
from common.lib.dataset import DataSet

from common.config_manager import config


class FourcatImportException(FourcatException):
    """
    Exception to raise if an error occurs fetching a dataset from another 4CAT server
    """
    pass


class SearchImportFromFourcat(BasicWorker):
    type = "import-4cat-dataset"  # job ID
    title = "Import from 4CAT"  # title displayed in UI

    max_workers = 1
    import_log = None

    def multilog(self, dataset=None, message=""):
        """
        Writes to both the dataset and import log

        If either is `None`, it is skipped.

        :param dataset:  Dataset object to write to the log of
        :param str message:  Message to write
        """
        if dataset:
            dataset.update_status(message)

        if self.import_log:
            self.import_log.write(message + "\n")

    def work(self):
        """
        Import a dataset from another 4CAT instance
        """
        urls = [url.strip() for url in self.job.details.get("url").split(",")]
        owners = self.job.details.get("owner").split(",")
        base = urls[0].split("/results/")[0]
        keys = [url.split("/results/")[-1].split("/")[0].split("#")[0].split("?")[0] for url in urls]
        api_key = self.job.details.get("api-key")
        file_paths = []
        imported_keys = []

        self.import_log = config.get("PATH_ROOT").joinpath(config.get("PATH_LOGS")).joinpath("import.log").open("a")
        version_file = config.get("PATH_ROOT").joinpath("config/.current-version")
        with version_file.open() as infile:
            version = infile.readline().strip()

        for index, dataset_key in enumerate(keys):
            if self.interrupted:
                self.multilog(dataset=None, message="Import interrupted, cleaning up partially imported datasets")
                for path in file_paths:
                    if path.exists():
                        # clean up partially implemented datasets and delete imported datasets
                        path.unlink()
                self.db.delete("datasets", where={"key": tuple(imported_keys)})
                self.db.delete("datasets_owners", where={"key": tuple(imported_keys)})

                raise WorkerInterruptedException()

            # first, metadata!
            try:
                metadata = SearchImportFromFourcat.fetch_from_4cat(base, dataset_key, api_key, "metadata")
                metadata = metadata.json()
            except FourcatImportException as e:
                self.multilog(dataset=None, message=str(e))
                continue
            except ValueError:
                self.multilog(dataset=None, message=f"Could not read metadata for dataset {dataset_key}")
                continue

            if metadata["version"] != version:
                self.multilog(dataset=None, message=f"Dataset {urls[index]} is from a different version of 4CAT "
                                                    f"({metadata['version']}) than this one ({version}), skipping "
                                                    f"import.")

            self.db.insert("datasets", data=metadata["data"])
            new_dataset = DataSet(key=metadata["data"]["key"], db=self.db)
            imported_keys.append(new_dataset.key)

            # add owners
            for owner in owners:
                new_dataset.add_owner(owner)

            # then, the log
            new_dataset.update_status("Importing log file")
            file_paths.append(new_dataset.get_results_path().with_suffix(".log"))
            with new_dataset.get_results_path().with_suffix(".log").open("w") as outfile:
                try:
                    log_stream = SearchImportFromFourcat.fetch_from_4cat(base, dataset_key, api_key, "log", stream=True)
                except FourcatImportException as e:
                    self.multilog(new_dataset, f"Could not read log file for dataset {dataset_key}, deleting and "
                                               f"skipping data transfer")
                    new_dataset.delete()
                    continue

                for line in log_stream.iter_lines():
                    outfile.write(line)

            # then, the data file!
            progress = 0
            previous_progress = 0
            expected_megabytes = round(metadata["filesize"] / 1024 / 1024, 1)
            file_paths.append(new_dataset.get_results_path())
            with new_dataset.get_results_path().open("wb") as outfile:
                try:
                    data_stream = SearchImportFromFourcat.fetch_from_4cat(base, dataset_key, api_key, "data",
                                                                          stream=True)
                    for chunk in data_stream.iter_content(1024):
                        outfile.write(chunk)
                        progress += len(chunk)
                        if progress > previous_progress + (1024 * 1024):
                            megabytes = round(progress / 1024 / 1024, 1)
                            self.multilog(new_dataset,
                                          f"Importing data file for dataset {new_dataset.key}: transferred {megabytes}/{expected_megabytes} MB")
                except FourcatImportException as e:
                    self.multilog(new_dataset, f"Could not read data file for dataset {dataset_key}, deleting and "
                                               f"skipping data transfer")
                    new_dataset.delete()
                    continue

            # then, do the same for all children!
            try:
                children = SearchImportFromFourcat.fetch_from_4cat(base, dataset_key, api_key, "children")
                children = children.json()
                for child in children:
                    self.queue.add_job(self.type, {"url": child, "api-key": api_key})
                    self.multilog(new_dataset, f"Queued import of child dataset {child} of parent {new_dataset.key}.")
            except ValueError:
                # not fatal, still bad
                self.multilog(new_dataset, message=f"Could not import child datasets for dataset {new_dataset.key}.")

            self.multilog(new_dataset, f"Finished import dataset {new_dataset.key} from {urls[index]}.")

        self.multilog(dataset=None, message="Finished importing batch of {len(urls)} datasets.")
        self.job.finish()

    @staticmethod
    def fetch_from_4cat(base, dataset_key, api_key, component, stream=False):
        try:
            response = requests.get(f"{base}/api/export-packed-dataset/{dataset_key}/{component}/", timeout=5, headers={
                "User-Agent": "4cat/import",
                "Authentication": api_key
            }, stream=stream)
        except requests.Timeout:
            raise FourcatImportException(f"The 4CAT server at {base} took too long to respond. Make sure it is "
                                         f"accessible to external connections and try again.")
        except requests.RequestException as e:
            raise FourcatImportException(f"Could not connect to the 4CAT server at {base} ({e}). Make sure it is "
                                         f"accessible to external connections and try again.")

        if response.status_code == 404:
            raise FourcatImportException(
                f"Dataset {dataset_key} not found at server {base}. Make sure all URLs point to "
                f"a valid dataset.")
        elif response.status_code == 403:
            raise FourcatImportException(
                f"Dataset {dataset_key} not accessible at server {base}. Make sure you have access to this "
                f"dataset and are using the correct API key.")
        elif response.status_code != 200:
            raise FourcatImportException(
                f"Unexpected error while trying to import dataset {dataset_key} from server {base}: {response.text}")

        return response
