import re
import time
import zipfile

from backend.lib.processor import BasicProcessor
from common.lib.exceptions import QueryParametersException
from common.lib.user_input import UserInput


class SearchMedia(BasicProcessor):
    type = "media-import-search"  # job ID
    category = "Search"  # category
    title = "Upload Media"  # title displayed in UI
    description = "Upload your own audio, video, or image files to be used as a dataset"  # description displayed in UI
    extension = "zip"  # extension of result file, used internally and in UI
    is_local = False  # Whether this datasource is locally scraped
    is_static = False  # Whether this datasource is still updated

    max_workers = 1

    disallowed_characters = re.compile(r"[^a-zA-Z0-9._+-]")

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        return {
        "intro": {
            "type": UserInput.OPTION_INFO,
            "help": "You can upload files here that will be available for further analysis "
                    "and processing. "
                    "You can indicate what type of files are uploaded (image, audio, or video) and based on that, "
                    "the 4CAT will be able to run various processors on these files. "
        },
        "data_upload": {
            "type": UserInput.OPTION_FILES,
            "help": "Files"
        },
        "media_type": {
            "type": UserInput.OPTION_CHOICE,
            "help": "Media type",
            "options": {
                "audio": "Audio",
                "video": "Videos",
                "image": "Images",
            },
            "default": "image"
        },
    }

    @staticmethod
    def validate_query(query, request, user):
        """
        Step 1: Validate query and files

        Confirms that the uploaded files exist and that the media type is valid.

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param User user:  User object of user who has submitted the query
        :return dict:  Safe query parameters
        """
        # do we have uploaded files?
        if "option-data_upload" not in request.files:
            raise QueryParametersException("No files were offered for upload.")
        files = request.files.getlist("option-data_upload")
        if len(files) < 1:
            raise QueryParametersException("No files were offered for upload.")

        # do we have a media type?
        if query.get("media_type") not in ["audio", "video", "image"]:
            raise QueryParametersException(f"Cannot import files of type {query.get('media_type')}.")

        # TODO: check file types against media type

        return {
            "time": time.time(),
            "media_type": query.get("media_type"),
            "num_files": len(files),
        }

    @staticmethod
    def after_create(query, dataset, request):
        """
        Step 2: Hook to execute after the dataset for this source has been created

        In this case, save the files in a zip archive.

        :param dict query:  Sanitised query parameters
        :param DataSet dataset:  Dataset created for this query
        :param request:  Flask request submitted for its creation
        """
        saved_files = 0
        with zipfile.ZipFile(dataset.get_results_path(), "w", compression=zipfile.ZIP_STORED) as zip_file:
            for file in request.files.getlist("option-data_upload"):
                new_filename = SearchMedia.disallowed_characters.sub("", file.filename)
                with zip_file.open(new_filename, mode='w') as dest_file:
                    file.seek(0)
                    while True:
                        chunk = file.read(1024)
                        if len(chunk) == 0:
                            break
                        dest_file.write(chunk)
                saved_files += 1

    def process(self):
        """
        Step 3: Ummmm, we kinda did everything
        """
        self.dataset.finish(self.parameters.get("num_files"))