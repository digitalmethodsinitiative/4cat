import re
import time
import zipfile
import mimetypes

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
    accepted_file_types = ["audio", "video", "image"]

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        return {
        "intro": {
            "type": UserInput.OPTION_INFO,
            "help": "You can upload files here that will be available for further analysis "
                    "and processing. "
                    "Please include only one type of file per dataset (image, audio, or video) and based on that, "
                    "the 4CAT will be able to run various processors on these files. "
        },
        "data_upload": {
            "type": UserInput.OPTION_FILE,
            "multiple": True,
            "help": "Files"
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

        # Check file types to ensure all are same type of media
        media_type = None
        for file in request.files.getlist("option-data_upload"):
            # python-magic sniffs files to determine their type, but from request stream always seems to return
            # application/octet-stream. if appears that we would need to save the whole files first so here we guess
            # mime_type = magic.from_buffer(file.stream.read(2048), mime=True).split('/')[0]
            mime_type = mimetypes.guess_type(file.filename)[0]
            if mime_type is None:
                raise QueryParametersException(f"Could not determine the type of file {file.filename}.")
            else:
                mime_type = mime_type.split('/')[0]

            if mime_type not in SearchMedia.accepted_file_types:
                raise QueryParametersException(f"This datasource only accepts files of {SearchMedia.accepted_file_types} (file {file.filename} detected type {mime_type}.")

            if media_type is None:
                media_type = mime_type
            elif media_type != mime_type:
                raise QueryParametersException(f"All files must be of the same type. {file.filename} is not of type {media_type}")

        # TODO: if media_type is zip...

        return {
            "time": time.time(),
            "media_type": media_type,
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