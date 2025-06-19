"""
Delete old datasets
"""

import shutil
import re
import json
from datetime import datetime
from pathlib import Path

from common.config_manager import config
from backend.lib.worker import BasicWorker
from common.lib.dataset import DataSet
from common.lib.exceptions import WorkerInterruptedException, DataSetException


class TempFileCleaner(BasicWorker):
    """
    Clean up discarded temporary files

    If 4CAT crashes while processing something, it may result in staging
    folders that are never cleaned up. This worker checks for finished
    datasets with staging area folders and cleans them up.

    Also cleans up orphaned result files for datasets that no longer exist.
    """

    type = "clean-temp-files"
    max_workers = 1

    ensure_job = {"remote_id": "localhost", "interval": 10800}

    # Use tracking file to delay deletion of files that may still be in use
    tracking_file = config.get("PATH_DATA").joinpath(".temp_file_cleaner")
    days_to_keep = 7

    def work(self):
        """
        Go through result files, and for each one check if it should still
        exist
        :return:
        """
        # Load tracking file
        if not self.tracking_file.exists():
            tracked_files = {}
        else:
            tracked_files = json.loads(self.tracking_file.read_text())

        result_files = Path(config.get("PATH_DATA")).glob("*")
        for file in result_files:
            if file.stem.startswith("."):
                # skip hidden files
                continue

            if self.interrupted:
                self.tracking_file.write_text(json.dumps(tracked_files))
                raise WorkerInterruptedException(
                    "Interrupted while cleaning up orphaned result files"
                )

            # the key of the dataset files belong to can be extracted from the
            # file name in a predictable way.
            possible_keys = re.findall(r"[abcdef0-9]{32}", file.stem)
            if not possible_keys:
                self.log.warning(
                    "File %s does not seem to be a result file - clean up manually"
                    % file
                )
                continue

            # if for whatever reason there are multiple hashes in the filename,
            # the key would always be the last one
            key = possible_keys.pop()

            try:
                dataset = DataSet(key=key, db=self.db)
            except DataSetException:
                # the dataset has been deleted since, but the result file still
                # exists - should be safe to clean up
                if file.name not in tracked_files:
                    self.log.info(
                        f"No matching dataset with key {key} for file {file}; marking for deletion"
                    )
                    tracked_files[file.name] = datetime.now().timestamp() + (
                        self.days_to_keep * 86400
                    )
                elif tracked_files[file.name] < datetime.now().timestamp():
                    self.log.info(
                        f"File {file} marked for deletion since {datetime.fromtimestamp(tracked_files[file.name]).strftime('%Y-%m-%d %H:%M:%S')}, deleting file"
                    )
                    if file.is_dir():
                        try:
                            shutil.rmtree(file)
                        except PermissionError:
                            self.log.info(
                                f"Folder {file} does not belong to a dataset but cannot be deleted (no "
                                f"permissions), skipping"
                            )

                    else:
                        try:
                            file.unlink()
                        except FileNotFoundError:
                            # the file has been deleted since
                            pass

                    # Remove from tracking
                    del tracked_files[file.name]

                continue

            if file.is_dir() and "-staging" in file.stem and dataset.is_finished():
                # staging area exists but dataset is marked as finished
                # if the dataset is finished, the staging area should have been
                # compressed into a zip file, or deleted, so this is also safe
                # to clean up
                if file.name not in tracked_files:
                    self.log.info(
                        "Dataset %s is finished, but staging area remains at %s, marking for deletion"
                        % (dataset.key, str(file))
                    )
                    tracked_files[file.name] = datetime.now().timestamp() + (
                        self.days_to_keep * 86400
                    )
                elif tracked_files[file.name] < datetime.now().timestamp():
                    self.log.info(
                        "Dataset %s is finished, but staging area remains at %s, deleting folder"
                        % (dataset.key, str(file))
                    )
                    shutil.rmtree(file)

        # Update tracked files
        self.tracking_file.write_text(json.dumps(tracked_files))

        self.job.finish()
