import re
import json
import time
import zipfile
import mimetypes
from io import BytesIO

from backend.lib.processor import BasicProcessor
from common.lib.exceptions import QueryParametersException, QueryNeedsExplicitConfirmationException
from common.lib.user_input import UserInput
from common.lib.helpers import andify


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
                        "Please include only one type of file per dataset (image, audio, or video) and "
                        "4CAT will be able to run various processors on these files. "
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
        bad_files = []
        seen_types = set()
        all_files = 0

        uploaded_files = request.files.getlist("option-data_upload")
        single_zip_file = uploaded_files and len(uploaded_files) == 1 and uploaded_files[0].filename.lower().endswith(".zip")

        if "option-data_upload-entries" in request.form or single_zip_file:
            # we have a zip file!
            try:
                if single_zip_file:
                    # we have a single uploaded zip file
                    # i.e. the query has already been validated (else we would have
                    # -entries and no file) and we can get the file info from the
                    # zip file itself
                    uploaded_files[0].seek(0)
                    zip_file_data = BytesIO(uploaded_files[0].read())
                    with zipfile.ZipFile(zip_file_data, "r") as uploaded_zip:
                        files = [{"filename": f} for f in uploaded_zip.namelist()]
                else:
                    # validating - get file names from entries field
                    files = json.loads(request.form["option-data_upload-entries"])

                # ignore known metadata files
                files = [f for f in files if not (
                        f["filename"].split("/")[-1].startswith(".")
                        or f["filename"].endswith(".log")
                        or f["filename"].split("/")[-1].startswith("__MACOSX")
                        or f["filename"].endswith(".DS_Store")
                        or f["filename"].endswith("/")  # sub-directory
                )]

                # figure out if we have mixed media types
                seen_types = set()
                for file in files:
                    try:
                        file_type = mimetypes.guess_type(file["filename"])[0].split("/")[0]
                        seen_types.add(file_type)
                        all_files += 1
                    except (AttributeError, TypeError):
                        bad_files.append(file["filename"])

            except (ValueError, zipfile.BadZipfile):
                raise QueryParametersException("Cannot read zip file - it may be encrypted or corrupted and cannot "
                                               "be uploaded to 4CAT.")

        elif "option-data_upload" not in request.files:
            raise QueryParametersException("No files were offered for upload.")

        elif len(uploaded_files) < 1:
            raise QueryParametersException("No files were offered for upload.")

        else:
            # we just have a bunch of separate files
            # Check file types to ensure all are same type of media
            media_type = None
            for file in uploaded_files:
                # Allow metadata files and log files to be uploaded
                if file.filename == ".metadata.json" or file.filename.endswith(".log"):
                    continue

                # when uploading multiple files, we don't want zips
                if file.filename.lower().endswith(".zip"):
                    raise QueryParametersException("When uploading media in a zip archive, please upload exactly one "
                                                   "zip file; 4CAT cannot combine multiple separate zip archives.")

                # Guess mime type from filename; we only have partial files at this point
                mime_type = mimetypes.guess_type(file.filename)[0]
                if mime_type is None:
                    bad_files.append(file.filename)
                    continue

                mime_type = mime_type.split('/')[0]
                if mime_type not in SearchMedia.accepted_file_types:
                    raise QueryParametersException(f"This data source only accepts "
                                                   f"{andify(SearchMedia.accepted_file_types)} files; "
                                                   f"'{file.filename}' was detected as {mime_type}, which 4CAT cannot "
                                                   f"process.")

            seen_types.add(media_type)
            all_files += 1

        # we need to at least be able to recognise the extension to know we can
        # do something with the file...
        if bad_files:
            separator = "\n- "
            raise QueryParametersException("The type of the following files cannot be determined; rename them or "
                                           f"remove them from the archive or rename them\n{separator.join(bad_files)}")

        # this is not fool-proof, but uncommon extensions are less likely to work
        # anyway and the user can still choose to proceed
        if len(set(seen_types)) > 1:
            raise QueryParametersException(
                f"The zip file contains files of multiple media types ({andify(seen_types)}). 4CAT processors require "
                "files of a single type to work properly. Please re-upload only a single type of media to proceed."
            )

        return {
            "time": time.time(),
            "media_type": seen_types.pop(),
            "num_files": all_files,
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
        mime_type = query.get("media_type")
        saved_files = 0
        skipped_files = []
        with (zipfile.ZipFile(dataset.get_results_path(), "w", compression=zipfile.ZIP_STORED) as new_zip_archive):
            for file in request.files.getlist("option-data_upload"):
                # Check if file is zip archive
                file_mime_type = mimetypes.guess_type(file.filename)[0]
                if file_mime_type is not None and file_mime_type.split('/')[0] == "application" and \
                        file_mime_type.split('/')[1] == "zip":
                    # Save inner files from zip archive to new zip archive with all files
                    file.seek(0)
                    zip_file_data = BytesIO(file.read())
                    with zipfile.ZipFile(zip_file_data, "r") as inner_zip_archive:
                        for inner_file in inner_zip_archive.infolist():
                            if inner_file.is_dir():
                                continue

                            guessed_file_mime_type = mimetypes.guess_type(inner_file.filename)
                            if guessed_file_mime_type[0]:
                                mime_type = guessed_file_mime_type[0].split('/')[0]

                            # skip useless metadata files
                            # also skip files not recognised as media files
                            clean_file_name = inner_file.filename.split("/")[-1]
                            if not guessed_file_mime_type[0] or (
                                    mime_type not in SearchMedia.accepted_file_types
                                    and not clean_file_name.endswith(".log")
                                    and not clean_file_name == ".metadata.json"
                            ) or clean_file_name.startswith("__MACOSX") \
                              or inner_file.filename.startswith("__MACOSX"):
                                print(f"skipping {clean_file_name} ({guessed_file_mime_type})")
                                skipped_files.append(inner_file.filename)
                                continue

                            # save inner file from the uploaded zip archive to the new zip with all files
                            new_filename = SearchMedia.get_safe_filename(inner_file.filename, new_zip_archive)
                            new_zip_archive.writestr(new_filename, inner_zip_archive.read(inner_file))

                            if not new_filename == ".metadata.json" or not new_filename.endswith(".log"):
                                saved_files += 1
                    continue

                new_filename = SearchMedia.get_safe_filename(file.filename, new_zip_archive)
                with new_zip_archive.open(new_filename, mode='w') as dest_file:
                    file.seek(0)
                    while True:
                        chunk = file.read(1024)
                        if len(chunk) == 0:
                            break
                        dest_file.write(chunk)

                if not new_filename == ".metadata.json" or not new_filename.endswith(".log"):
                    saved_files += 1

        # update the number of files in the dataset
        dataset.num_files = saved_files
        dataset.media_type = mime_type
        if skipped_files:
            # todo: this now doesn't actually get logged because the log is
            # re-initialised after after_create runs?
            dataset.log("The following files in the uploaded zip archive were skipped because they were not recognised"
                        "as media files:" + "\n  -".join(skipped_files))

    def process(self):
        """
        Step 3: Ummmm, we kinda did everything
        """
        self.dataset.finish(self.parameters.get("num_files"))

    @staticmethod
    def get_safe_filename(filename, zip_archive=None):
        new_filename = SearchMedia.disallowed_characters.sub("", filename)
        if zip_archive:
            # check if file is in zip archive
            index = 1
            while new_filename in zip_archive.namelist():
                new_filename = new_filename + "_" + str(index)
                index += 1

        return new_filename
