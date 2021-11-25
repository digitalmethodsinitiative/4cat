"""
Delete old datasets
"""
import shutil
import re

from pathlib import Path

import config
from backend.abstract.worker import BasicWorker
from common.lib.dataset import DataSet


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

    def work(self):
        """
        Go through result files, and for each one check if it should still
        exist
        :return:
        """

        result_files = Path(config.PATH_DATA).glob("*")
        for file in result_files:
            # the key of the dataset files belong to can be extracted from the
            # file name in a predictable way
            if file.is_dir():
                key = file.stem.split("-staging")[0].split("-")[-1]
            else:
                key = file.stem.split("-")[-1]

            key = key[:32]
            if not re.match(r"[abcdef0-9]{32}", key):
                # skip these files, since we don't know if they're somehow
                # important, as they're not recognizable as dataset files
                self.log.warning("Unknown dataset key format '%s'" % key)
                continue

            try:
                dataset = DataSet(key=key, db=self.db)
            except TypeError:
                # the dataset has been deleted since, but the result file still
                # exists - should be safe to clean up
                self.log.debug("No matching dataset with key %s for file %s, deleting file" % (key, str(file)))
                if file.is_dir():
                    shutil.rmtree(file)
                else:
                    file.unlink()
                continue

            if file.is_dir() and "-staging" in file.stem and dataset.is_finished():
                # staging area exists but dataset is marked as finished
                # if the dataset is finished, the staging area should have been
                # compressed into a zip file, or deleted, so this is also safe
                # to clean up
                self.log.debug("Dataset %s is finished, but staging area remains at %s, deleting folder" % (
                dataset.key, str(file)))
                shutil.rmtree(file)
