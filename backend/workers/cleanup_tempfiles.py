"""
Delete old datasets
"""
import shutil
import re

from pathlib import Path

import config
from backend.abstract.worker import BasicWorker
from common.lib.dataset import DataSet
from common.lib.exceptions import WorkerInterruptedException


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
            if self.interrupted:
                raise WorkerInterruptedException("Interrupted while cleaning up orphaned result files")

            # the key of the dataset files belong to can be extracted from the
            # file name in a predictable way.
            possible_keys = re.findall(r"[abcdef0-9]{32}", file.stem)
            if not possible_keys:
                self.log.warning("File %s does not seem to be a result file - clean up manually" % file)
                continue

            # if for whatever reason there are multiple hashes in the filename,
            # the key would always be the last one
            key = possible_keys.pop()

            try:
                dataset = DataSet(key=key, db=self.db)
            except TypeError:
                # the dataset has been deleted since, but the result file still
                # exists - should be safe to clean up
                self.log.info("No matching dataset with key %s for file %s, deleting file" % (key, str(file)))
                if file.is_dir():
                    shutil.rmtree(file)
                else:
                    try:
                        file.unlink()
                    except FileNotFoundError:
                        # the file has been deleted since
                        pass
                continue

            if file.is_dir() and "-staging" in file.stem and dataset.is_finished():
                # staging area exists but dataset is marked as finished
                # if the dataset is finished, the staging area should have been
                # compressed into a zip file, or deleted, so this is also safe
                # to clean up
                self.log.debug("Dataset %s is finished, but staging area remains at %s, deleting folder" % (
                dataset.key, str(file)))
                shutil.rmtree(file)
