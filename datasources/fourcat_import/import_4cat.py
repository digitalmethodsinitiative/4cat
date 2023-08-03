"""
Custom data upload to create bespoke datasets
"""
import requests
import time

import datasources.upload.import_formats as import_formats

from dateutil.parser import parse as parse_datetime
from datetime import datetime

from backend.lib.processor import BasicProcessor
from common.lib.exceptions import QueryParametersException, FourcatException, ProcessorInterruptedException
from common.lib.helpers import strip_tags, sniff_encoding, UserInput, HashCache, get_software_version
from common.lib.dataset import DataSet

from common.config_manager import config


class FourcatImportException(FourcatException):
    pass


class SearchImportFromFourcat(BasicProcessor):
    type = "import_4cat-search"  # job ID
    category = "Search"  # category
    title = "Import from 4CAT"  # title displayed in UI
    description = "Import a dataset from another 4CAT instance"  # description displayed in UI
    is_local = False  # Whether this datasource is locally scraped
    is_static = False  # Whether this datasource is still updated

    max_workers = 1
    options = {
        "intro": {
            "type": UserInput.OPTION_INFO,
            "help": "Provide the URL of a dataset in another 4CAT server that you would like to copy to this one here. "
                    "You can import multiple datasets; enter multiple URLs in that case, separated by commas. You will "
                    "be directed to the first imported dataset after importing has completed. All URLs need to point "
                    "to the same 4CAT server.\n\nTo import a dataset across servers, both servers need to be running "
                    "the same version of 4CAT. You can find the current version in the footer at the bottom of the "
                    "interface."
        },
        "url": {
            "type": UserInput.OPTION_TEXT,
            "help": "Dataset URL",
            "tooltip": "URL to the dataset's page, for example https://4cat.local/results/28da332f8918e6dc5aacd1c3b0170f01b80bd95f8ff9964ac646cecd33bfee49/."
        },
        "intro2": {
            "type": UserInput.OPTION_INFO,
            "help": "You can create an API key via the 'API Access' item in 4CAT's navigation menu. Note that you need "
                    "an API key from **the server you are importing from**, not the one you are looking at right now. "
                    "Additionally, you need to have owner access to the dataset you want to import."
        },
        "api-key": {
            "type": UserInput.OPTION_TEXT,
            "help": "4CAT API Key"
        }
    }

    def process(self):
        """
        Process uploaded CSV file

        Applies the provided mapping and makes sure the file is in a format
        4CAT will understand.
        """
        urls = [url.strip() for url in self.parameters.get("url").split(",")]
        base = urls[0].split("/results/")[0]
        keys = [url.split("/results/")[-1].split("/")[0].split("#")[0].split("?")[0] for url in urls]
        api_key = self.parameters.get("api-key")
        file_paths = []
        imported_keys = []
        log_buffer = []

        for dataset_key in keys:
            if self.interrupted:
                for path in file_paths:
                    # clean up partially implemented datasets and delete imported datasets
                    path.unlink()
                    self.db.delete("datasets", where={"key": tuple(imported_keys)})
                    self.db.delete("datasets_owners", where={"key": tuple(imported_keys)})

                raise ProcessorInterruptedException()

            # first, metadata!
            try:
                metadata = SearchImportFromFourcat.fetch_from_4cat(base, dataset_key, api_key, "metadata")
                metadata = metadata.json()
            except FourcatImportException as e:
                log_buffer.append(str(e))
                continue
            except ValueError:
                log_buffer.append(f"Could not read metadata for dataset {dataset_key}")
                continue
            metadata.pop("current_4CAT_version")
            self.db.insert("datasets", data=metadata)
            # TODO: any chance keys are not unique?
            new_dataset = DataSet(key=metadata["key"], db=self.db)
            imported_keys.append(new_dataset.key)

            # then, the log

    @staticmethod
    def fetch_from_4cat(base, dataset_key, api_key, component):
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
        keys = [url.split("/results/")[-1].split("/")[0].split("#")[0].split("?")[0] for url in urls]
        if len(bases) != 1:
            return QueryParametersException("All URLs need to point to the same 4CAT server. You can only import from "
                                            "one 4CAT server at a time.")

        base = urls[0].split("/results/")[0]
        try:
            test = SearchImportFromFourcat.fetch_from_4cat(base, keys[0], query.get("api-key"), "metadata")
        except FourcatImportException as e:
            raise QueryParametersException(str(e))

        try:
            metadata = test.json()
        except ValueError:
            raise QueryParametersException(f"Unexpected response when trying to fetch metadata for dataset {keys[0]}.")

        version = get_software_version()

        if metadata.get("current_4CAT_version") != version:
            raise QueryParametersException(f"This 4CAT server is running a different version of 4CAT ({version}) than "
                                           f"the one you are trying to import from ({metadata.get('version')}). Make "
                                           "sure both are running the same version of 4CAT and try again.")

        # OK, we can import at least one dataset
        return {
            "url": ",".join(urls),
            "api-key": query.get("api-key")
        }
