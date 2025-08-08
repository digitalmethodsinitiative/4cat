"""
Manage a 4CAT extension
"""
import datetime
import subprocess
import requests
import logging
import zipfile
import shutil
import shlex
import json
import ural
import os
import re

from logging.handlers import RotatingFileHandler
from pathlib import Path

from backend.lib.worker import BasicWorker


class ExtensionManipulator(BasicWorker):
    """
    Manage 4CAT extensions

    4CAT extensions are essentially git repositories. This worker can clone the
    relevant git repository or delete it and clean up after it.

    This is done in a worker instead of in the front-end code because cloning
    a large git repository can take some time so it is best to do it
    asynchronously. This is also future-proof in that it is easy to add support
    for installation code etc here later.

    Results are logged to a separate log file that can then be inspected in the
    web interface.
    """
    type = "manage-extension"
    max_workers = 1

    def work(self):
        """
        Do something with extensions
        """
        extension_reference = self.job.data["remote_id"]
        task = self.job.details.get("task")

        # this worker uses its own log file instead of the main 4CAT log
        # this is so that it is easier to monitor error messages about failed
        # installations etc and display those separately in e.g. the web
        # interface

        log_file = self.config.get("PATH_LOGS").joinpath("extensions.log")
        logger = logging.getLogger(self.type)
        if not logger.handlers:
            handler = RotatingFileHandler(log_file, backupCount=1, maxBytes=50000)
            handler.level = logging.INFO
            handler.setFormatter(logging.Formatter("%(asctime)-15s | %(levelname)s: %(message)s",
                                                   "%d-%m-%Y %H:%M:%S"))
            logger.addHandler(handler)
        logger.level = logging.INFO
        self.extension_log = logger

        if task == "install":
            success = self.install_extension(extension_reference)
            if success:
                # Add job to restart 4CAT; include upgrade to ensure migrate.py runs which will install any extension updates and new python packages
                lock_file = self.config.get("PATH_CONFIG").joinpath("restart.lock")
                if lock_file.exists():
                    # restart already in progress
                    self.extension_log.info("4CAT restart already in progress. Upgrade will be applied on next restart.")
                else:
                    self.extension_log.info("Adding job to restart 4CAT and apply extension upgrade.")
                     # ensure lockfile exists - will be written to later by worker
                    lock_file.touch()
                    # this log file is used to keep track of the progress, and will also
                    # be viewable in the web interface
                    restart_log_file = self.config.get("PATH_LOGS").joinpath("restart.log")
                    with restart_log_file.open("w") as outfile:
                        outfile.write(
                            f"Upgrade initiated at server timestamp {datetime.datetime.now().strftime('%c')}\n")
                        outfile.write("Telling 4CAT to upgrade via job queue...\n")
                    
                    # add job to restart 4CAT
                    self.queue.add_job("restart-4cat", {}, "upgrade")
                
        elif task == "uninstall":
            self.uninstall_extension(extension_reference)

        self.job.finish()

    def uninstall_extension(self, extension_name):
        """
        Remove extension

        Currently as simple as deleting the folder, but could add further
        cleaning up code later.

        While an extension can define configuration settings, we do not
        explicitly remove these here. 4CAT has general cleanup code for
        unreferenced settings and it may be beneficial to keep them in case
        the extension is re-installed later.

        :param str extension_name:  ID of the extension (i.e. name of the
        folder it is in)
        """
        self.extension_log.info(f"Uninstalling extension {extension_name}.")
        extensions_root = self.config.get("PATH_EXTENSIONS")
        target_folder = extensions_root.joinpath(extension_name)

        if not target_folder.exists():
            return self.extension_log.error(f"Extension {extension_name} does not exist - cannot remove it.")
        
        # Collect job types and uninstall function in extension workers
        extension_jobtypes = []
        for extension_worker in self.modules.workers.values():
            if extension_worker.is_extension and extension_worker.extension_name == extension_name:
                extension_jobtypes.append(extension_worker.type)
                if hasattr(extension_worker, "uninstall"):
                    self.extension_log.info(f"Running uninstall function for extension {extension_name}.")
                    extension_worker.uninstall()
        
        # Remove existing jobs for this extension
        for job in self.queue.get_all_jobs(restrict_claimable=False):
            if job.data["jobtype"] in extension_jobtypes:
                self.extension_log.info(f"Removing job {job.data['jobtype']} - {job.data['remote_id']}.")
                job.finish(delete=True)     

        try:
            shutil.rmtree(target_folder)
            self.extension_log.info(f"Finished uninstalling extension {extension_name}.")
        except OSError as e:
            self.extension_log.error(f"Could not uninstall extension {extension_name}. There may be an issue with "
                                     f"file privileges, or the extension is installed via a symbolic link which 4CAT "
                                     f"cannot manipulate. The system error message was: '{e}'")

    def install_extension(self, repository_reference, overwrite=False):
        """
        Install a 4CAT extension

        4CAT extensions can be installed from a git URL or a zip archive. In
        either case, the files are first put into a temporary folder, after
        which the manifest in that folder is read to complete installation.

        :param str repository_reference:  Git repository URL, or zip archive
        path.
        :param bool overwrite:  Overwrite extension if one exists? Set to
        `true` to upgrade existing extensions (for example)
        :return bool:  `True` if installation was successful, `False` otherwise
        """
        if self.job.details.get("source") == "remote":
            extension_folder, extension_name = self.clone_from_url(repository_reference)
        else:
            extension_folder, extension_name = self.unpack_from_zip(repository_reference)

        if not extension_name:
            self.extension_log.error("The 4CAT extension could not be installed.")
            return False

        # read manifest file
        manifest_file = extension_folder.joinpath("metadata.json")
        if not manifest_file.exists():
            shutil.rmtree(extension_folder)
            self.extension_log.error(f"Manifest file of newly cloned 4CAT extension {repository_reference} does "
                                            f"not exist. Cannot install as a 4CAT extension.")
            return False
        else:
            try:
                with manifest_file.open() as infile:
                    manifest_data = json.load(infile)
            except json.JSONDecodeError:
                shutil.rmtree(extension_folder)
                self.extension_log.error(f"Manifest file of newly cloned 4CAT extension {repository_reference} "
                                                f"could not be parsed. Cannot install as a 4CAT extension.")
                return False

        canonical_name = manifest_data.get("name", extension_name)
        canonical_id = manifest_data.get("id", extension_name)

        canonical_folder = extension_folder.with_name(canonical_id)
        existing_name = canonical_id
        existing_version = "unknown"

        if canonical_folder.exists():
            if canonical_folder.joinpath("metadata.json").exists():
                with canonical_folder.joinpath("metadata.json").open() as infile:
                    try:
                        existing_manifest = json.load(infile)
                        existing_name = existing_manifest.get("name", canonical_id)
                        existing_version = existing_manifest.get("version", "unknown")
                    except json.JSONDecodeError:
                        pass

            if overwrite:
                self.extension_log.warning(f"Uninstalling existing 4CAT extension {existing_name} (version "
                                           f"{existing_version}.")
                shutil.rmtree(canonical_folder)
            else:
                self.extension_log.error(f"An extension with ID {canonical_id} is already installed "
                                                f"({extension_name}, version {existing_version}). Cannot install "
                                                f"another one with the same ID - uninstall it first.")
                return False

        extension_folder.rename(canonical_folder)
        self.extension_log.info(f"Finished installing extension {canonical_name} (version {manifest_data.get('version', 'unknown')}) with ID "
                                f"{canonical_id}.")
        return True


    def unpack_from_zip(self, archive_path):
        """
        Unpack extension files from a zip archive

        Pretty straightforward - Make a temporary folder and extract the zip
        archive's contents into it.

        :param str archive_path: Path to the zip file to extract
        :return tuple:  Tuple of folder and extension name, or `None, None` on
        failure.
        """
        archive_path = Path(archive_path)
        if not archive_path.exists():
            return self.extension_log.error(f"Extension file does not exist at {archive_path} - cannot install."), None

        extension_name = archive_path.stem
        extensions_root = self.config.get("PATH_EXTENSIONS")
        temp_name = self.get_temporary_folder(extensions_root)
        try:
            with zipfile.ZipFile(archive_path, "r") as archive_file:
                archive_file.extractall(temp_name)
        except Exception as e:
            return self.extension_log.error(f"Could not extract extension zip archive {archive_path.name}: {e}. Cannot "
                                            f"install."), None
        finally:
            archive_path.unlink()

        return temp_name, extension_name


    def clone_from_url(self, repository_url):
        """
        Clone the extension files from a git repository URL

        :param str repository_url:  Git repository URL to clone extension from
        :return tuple:  Tuple of folder and extension name, or `None, None` on
        failure.
        """
        # we only know how to install extensions from URLs for now
        if not ural.is_url(repository_url):
            return self.extension_log.error(f"Cannot install 4CAT extension - invalid repository url: "
                                            f"{repository_url}"), None

        # normalize URL and extract name
        repository_url = repository_url.strip().split("#")[-1]
        if repository_url.endswith("/"):
            repository_url = repository_url[:-1]
        repository_url_name = re.sub(r"\.git$", "", repository_url.split("/")[-1].split("?")[0].lower())

        try:
            test_url = requests.head(repository_url)
            if test_url.status_code >= 400:
                return self.extension_log.error(
                    f"Cannot install 4CAT extension - the repository URL is unreachable (status code "
                    f"{test_url.status_code})"), None
        except requests.RequestException as e:
            return self.extension_log.error(
                f"Cannot install 4CAT extension - the repository URL seems invalid or unreachable ({e})"), None

        # ok, we have a valid URL that is reachable - try cloning from it
        extensions_root = self.config.get("PATH_EXTENSIONS")
        os.chdir(extensions_root)

        temp_name = self.get_temporary_folder(extensions_root)

        extension_folder = extensions_root.joinpath(temp_name)
        clone_command = f"git clone {shlex.quote(repository_url)} {temp_name}"
        clone_outcome = subprocess.run(shlex.split(clone_command), stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        cloned_correctly = True
        if clone_outcome.returncode != 0:
            cloned_correctly = False
            self.extension_log.info(clone_outcome.stdout.decode("utf-8"))
            self.extension_log.error(f"Could not clone 4CAT extension repository from {repository_url}:\n\n{clone_outcome.stderr}")

        if not cloned_correctly:
            if extension_folder.exists():
                shutil.rmtree(extension_folder)
            return self.extension_log.error(f"4CAT extension {repository_url} was not installed."), None

        return extension_folder, repository_url_name


    def get_temporary_folder(self, extensions_root):
        # clone into a temporary folder, which we will rename as needed
        # this is because the repository name is not necessarily the extension
        # name
        temp_base = "new-extension"
        temp_name = temp_base
        temp_index = 0
        while extensions_root.joinpath(temp_name).exists():
            temp_index += 1
            temp_name = f"{temp_base}-{temp_index}"

        return extensions_root.joinpath(temp_name)
