"""
DMI Service Manager
"""
import datetime
import os
import time
from json import JSONDecodeError
from werkzeug.utils import secure_filename

import requests
from pathlib import Path


__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"

from common.lib.helpers import strip_tags


class DmiServiceManagerException(Exception):
    """
    Raised when there is a problem with the configuration settings.
    """
    pass

class DsmOutOfMemory(DmiServiceManagerException):
    """
    Raised when there is a problem with the configuration settings.
    """
    pass


class DsmConnectionError(DmiServiceManagerException):
    """
    Raised when there is a problem with the configuration settings.
    """
    pass

class DmiServiceManager:
    """
    Class to manage interactions with a DMI Service Manager server.

    Found here:
    https://github.com/digitalmethodsinitiative/dmi_service_manager
    """
    def __init__(self, processor):
        """
        """
        self.processor = processor
        self.local_or_remote = processor.config.get("dmi-service-manager.ac_local_or_remote")
        self.server_address = processor.config.get("dmi-service-manager.ab_server_address").rstrip("/") + "/api/"

        self.processed_files = 0

        self.num_files_to_process = None
        self.server_file_collection_name = None
        self.server_results_folder_name = None
        self.path_to_files = None
        self.path_to_results = None

    def check_gpu_memory_available(self, service_endpoint):
        """
        Returns tuple with True if server has some memory available and  False otherwise as well as the JSON response
        from server containing the memory information.
        """
        api_endpoint = self.server_address + "check_gpu_mem/" + service_endpoint
        resp = requests.get(api_endpoint, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 503:
            # TODO: retry later (increase delay in dmi_service_manager class and interrupt w/ retry)? DSM could possibly manage jobs in queue
            # Processor could run CPU mode, but DSM needs to run different container (container fails if GPU enabled but not available)
            raise DsmOutOfMemory("DMI Service Manager server out of GPU memory.")
        else:
            try:
                reason = resp.json()['reason']
            except JSONDecodeError:
                reason = strip_tags(resp.text)
            raise DsmConnectionError(f"Connection Error {resp.status_code}: {reason}")

    def process_files(self, input_file_dir, filenames, output_file_dir, server_file_collection_name, server_results_folder_name):
        """
        Process files according to DMI Service Manager local or remote settings
        """
        self.num_files_to_process = len(filenames)

        # Upload files if necessary
        if self.local_or_remote == "local":
            # Relative to PATH_DATA which should be where Docker mounts the container volume
            # TODO: path is just the staging_area name, but what if we move staging areas? DMI Service manager needs to know...
            path_to_files = input_file_dir.absolute().relative_to(self.processor.config.get("PATH_DATA").absolute())
            path_to_results = output_file_dir.absolute().relative_to(self.processor.config.get("PATH_DATA").absolute())

        elif self.local_or_remote == "remote":

            # Upload files
            self.server_file_collection_name = server_file_collection_name
            self.server_results_folder_name = server_results_folder_name
            path_to_files, path_to_results = self.send_files(server_file_collection_name, server_results_folder_name, filenames, input_file_dir)

        else:
            raise DmiServiceManagerException("dmi_service_manager.local_or_remote setting must be 'local' or 'remote'")

        self.path_to_files = path_to_files
        self.path_to_results = path_to_results
        return path_to_files, path_to_results

    def check_progress(self):
        if self.local_or_remote == "local":
            current_completed = self.count_local_files(self.processor.config.get("PATH_DATA").joinpath(self.path_to_results))
        elif self.local_or_remote == "remote":
            existing_files = self.request_folder_files(self.server_file_collection_name)
            current_completed = len(existing_files.get(self.server_results_folder_name, []))
        else:
            raise DmiServiceManagerException("dmi_service_manager.local_or_remote setting must be 'local' or 'remote'")

        if current_completed != self.processed_files:
            self.processor.dataset.update_status(
                f"Processed {current_completed} of {self.num_files_to_process} files")
            self.processor.dataset.update_progress(current_completed / self.num_files_to_process)
            self.processed_files = current_completed

    def send_request_and_wait_for_results(self, service_endpoint, data, wait_period=60, check_process=True, callback=None):
        """
        Send request and wait for results to be ready.

        Check process assumes a one to one ratio of input files to output files. If this is not the case, set to False.
        If counts the number of files in the output folder and compares it to the number of input files.
        """
        if self.local_or_remote == "local":
            service_endpoint += "_local"
        elif self.local_or_remote == "remote":
            service_endpoint += "_remote"
        else:
            raise DmiServiceManagerException("dmi_service_manager.local_or_remote setting must be 'local' or 'remote'")

        api_endpoint = self.server_address + service_endpoint
        try:
            resp = requests.post(api_endpoint, json=data, timeout=30)
        except requests.exceptions.ConnectionError as e :
            raise DmiServiceManagerException(f"Unable to connect to DMI Service Manager server: {str(e)}")

        if resp.status_code == 202:
            # New request successful
            results_url = api_endpoint + "?key=" + resp.json()['key']
        else:
            try:
                resp_json = resp.json()
                if resp.status_code == 400 and 'key' in resp_json and 'error' in resp_json and resp_json['error'] == f"future_key {resp_json['key']} already exists":
                    # Request already exists
                    results_url = api_endpoint + "?key=" + resp_json['key']
                else:
                    raise DmiServiceManagerException(f"DMI Service Manager error: {str(resp.status_code)}: {str(resp_json)}")
            except JSONDecodeError:
                # Unexpected Error
                raise DmiServiceManagerException(f"DMI Service Manager error: {str(resp.status_code)}: {str(resp.text)}")

        # Wait for results to be ready
        self.processor.dataset.update_status(f"Generating results for {service_endpoint}...")

        check_time = time.time()
        success = False
        connection_error = 0
        while True:
            time.sleep(1)
            # If interrupted is called, attempt to finish dataset while server still running
            if self.processor.interrupted:
                self.processor.dataset.update_status(f"4CAT interrupted; Processing successful {service_endpoint} results...",
                                           is_final=True)
                break

            # Send request to check status every wait_period seconds
            if (time.time() - check_time) > wait_period:
                check_time = time.time()
                # Update progress
                if check_process:
                    self.check_progress()

                if callback:
                    callback(self)
                try:
                    result = requests.get(results_url, timeout=30)
                except requests.exceptions.ConnectionError as e:
                    # Have seen the Service Manager fail particularly when another processor is uploading many consecutive files
                    connection_error += 1
                    if connection_error > 3:
                        raise DmiServiceManagerException(f"Unable to connect to DMI Service Manager server: {str(e)}")
                    continue

                if 'status' in result.json().keys() and result.json()['status'] == 'running':
                    # Still running
                    continue
                elif 'report' in result.json().keys() and result.json()['returncode'] == 0:
                    # Complete without error
                    self.processor.dataset.update_status(f"Completed {service_endpoint}!")
                    success = True
                    break

                elif 'returncode' in result.json().keys() and int(result.json()['returncode']) == 1:
                    # Error
                    if 'error' in result.json().keys():
                        error = result.json()['error']
                        if "CUDA error: out of memory" in error:
                            raise DmiServiceManagerException("DMI Service Manager server ran out of memory; try reducing the number of files processed at once or waiting until the server is less busy.")
                        else:
                            raise DmiServiceManagerException(f"Error {service_endpoint}: " + error)
                    else:
                        raise DmiServiceManagerException(f"Error {service_endpoint}: " + str(result.json()))
                else:
                    # Something botched
                    raise DmiServiceManagerException(f"Error {service_endpoint}: " + str(result.json()))

        return success

    def process_results(self, local_output_dir):
        if self.local_or_remote == "local":
            # Output files are already in local directory
            pass
        elif self.local_or_remote == "remote":
            results_path = os.path.join(self.server_file_collection_name, self.server_results_folder_name)
            self.processor.dataset.log(f"Downloading results from {results_path}...")
            # Collect result filenames from server
            result_files = self.request_folder_files(results_path)
            for path, files in result_files.items():
                if path == '.':
                    self.download_results(files, results_path, local_output_dir)
                else:
                    Path(os.path.join(local_output_dir, path)).mkdir(exist_ok=True, parents=True)
                    self.download_results(files, os.path.join(results_path, path), local_output_dir.joinpath(path))

    def request_folder_files(self, folder_name):
        """
        Request files from a folder on the DMI Service Manager server.
        """
        filename_url = f"{self.server_address}list_filenames/{folder_name}"
        retries = 0
        while True:
            try:
                filename_response = requests.get(filename_url, timeout=30)
                break
            except requests.exceptions.ConnectionError as e:
                retries += 1
                if retries > 3:
                    raise DmiServiceManagerException(f"Connection Error {e} (retries {retries}) while downloading files from: {folder_name}")
                continue

        # Check if 4CAT has access to this server
        if filename_response.status_code == 403:
            raise DmiServiceManagerException("403: 4CAT does not have permission to use the DMI Service Manager server")
        elif filename_response.status_code in [400, 405]:
            raise DmiServiceManagerException(f"400: DMI Service Manager server {filename_response.json()['reason']}")
        elif filename_response.status_code == 404:
            # Folder not found; no files
            return {}
        elif filename_response.status_code != 200:
            raise DmiServiceManagerException(f"Unknown response from DMI Service Manager: {filename_response.status_code} - {filename_response.reason}")
        return filename_response.json()

    def send_files(self, file_collection_name, results_name, files_to_upload, dir_with_files):
        """
        Send files to the DMI Service Manager server. This is only relevant for remote mode based on file management.
        The path on the server to both the files and results will be returned.

        A "files" folder will be created in the under the file_collection_name folder. The files_to_upload will be be
        stored there. A unique results folder will be created under the results_name folder so that multiple results
        can be created based on a file collection if needed (without needing to re-upload files).

        :param str file_collection_name:    Name of collection; files will be uploaded to 'files' subfolder
        :param str results_name:            Name of results subfolder where output will be stored (and can be downloaded)
        :param list files_to_upload:        List of filenames to upload
        :param Path dir_with_files:         Local Path to files
        :param Dataset dataset:             Dataset object for status updates and unique key
        :return Path, Path:                 Server's Path to files, Server's Path to results
        """
        data = {'folder_name': file_collection_name}

        # Check if files have already been sent
        self.processor.dataset.update_status("Connecting to DMI Service Manager...")
        existing_files = self.request_folder_files(file_collection_name)
        uploaded_files = existing_files.get('4cat_uploads', [])
        if len(uploaded_files) > 0:
            self.processor.dataset.update_status("Found %i files previously uploaded" % (len(uploaded_files)))

        # Compare files with previously uploaded
        to_upload_filenames = [filename for filename in files_to_upload if filename not in uploaded_files]
        total_files_to_upload = len(to_upload_filenames)

        # Check if results folder exists
        empty_placeholder = None
        if results_name not in existing_files:
            total_files_to_upload += 1
            # Create a blank file to upload into results folder
            empty_placeholder = f"4CAT_{results_name}_blank.txt"
            with open(dir_with_files.joinpath(empty_placeholder), 'w') as file:
                file.write('')
            to_upload_filenames = [empty_placeholder] + to_upload_filenames

        if total_files_to_upload > 0:
            api_upload_endpoint = f"{self.server_address}send_files"

            self.processor.dataset.update_status(f"Uploading {total_files_to_upload} files")
            files_uploaded = 0
            while to_upload_filenames:
                upload_file = to_upload_filenames.pop()
                self.processor.dataset.log(f"Uploading {upload_file}")
                # Upload files
                if upload_file == empty_placeholder:
                    # Upload a blank results file to results folder
                    response = requests.post(api_upload_endpoint,
                                             files=[(results_name, open(dir_with_files.joinpath(upload_file), 'rb'))],
                                             data=data, timeout=120)
                else:
                    # All other files uploading to general upload folder belonging to parent dataset collection
                    response = requests.post(api_upload_endpoint,
                                             files=[('4cat_uploads', open(dir_with_files.joinpath(upload_file), 'rb'))],
                                             data=data, timeout=120)

                if response.status_code == 200:
                    files_uploaded += 1
                    if files_uploaded % 1000 == 0:
                        self.processor.dataset.update_status(f"Uploaded {files_uploaded} of {total_files_to_upload} files!")
                    self.processor.dataset.update_progress(files_uploaded / total_files_to_upload)
                elif response.status_code == 403:
                    raise DmiServiceManagerException("403: 4CAT does not have permission to use the DMI Service Manager server")
                elif response.status_code == 405:
                    raise DmiServiceManagerException("405: Method not allowed; check DMI Service Manager server address (perhaps http is being used instead of https)")
                else:
                    self.processor.dataset.log(f"Unable to upload file ({response.status_code} - {response.reason}): {upload_file}")

                try:
                    response_json = response.json()
                except JSONDecodeError:
                    response_json = None
                if response_json and "errors" in response.json():
                    self.processor.dataset.log(
                        f"Unable to upload file ({response.status_code} - {response.reason}): {upload_file} - {response.json()['errors']}")

            self.processor.dataset.update_status(f"Uploaded {files_uploaded} files!")

        server_path_to_files = Path(file_collection_name).joinpath("4cat_uploads")
        server_path_to_results = Path(file_collection_name).joinpath(results_name)

        return server_path_to_files, server_path_to_results

    def download_results(self, filenames_to_download, folder_name, local_output_dir, timeout=30):
        """
        Download results from the DMI Service Manager server.

        :param list filenames_to_download:  List of filenames to download
        :param str folder_name:             Name of subfolder where files are localed (e.g. "results_name" or "files")
        :param Path local_output_dir:       Local Path to download files to
        :param int timeout:                 Number of seconds to wait for a response from the server
        """
        # Download the result files
        api_upload_endpoint = f"{self.server_address}download/"
        total_files_to_download = len(filenames_to_download)
        files_downloaded = 0
        self.processor.dataset.update_status(f"Downloading {total_files_to_download} files from {folder_name}...")
        for filename in filenames_to_download:
            retries = 0
            while True:
                try:
                    file_response = requests.get(api_upload_endpoint + f"{folder_name}/{filename}", timeout=timeout)
                    break
                except requests.exceptions.ConnectionError as e:
                    retries += 1
                    if retries > 3:
                        raise DmiServiceManagerException(f"Connection Error {e} (retries {retries}) while downloading file: {folder_name}/{filename}")
                    continue
            files_downloaded += 1
            if files_downloaded % 1000 == 0:
                self.processor.dataset.update_status(f"Downloaded {files_downloaded} of {total_files_to_download} files")
            self.processor.dataset.update_progress(files_downloaded / total_files_to_download)

            with open(local_output_dir.joinpath(filename), 'wb') as file:
                file.write(file_response.content)

    def sanitize_filenames(self, filename):
        """
        If source is local, no sanitization needed. If source is remote, the server sanitizes and as such, we need to
        ensure our filenames match what the server expects.
        """
        if self.local_or_remote == "local":
            return filename
        elif self.local_or_remote == "remote":
            return secure_filename(filename)
        else:
            raise DmiServiceManagerException("dmi_service_manager.local_or_remote setting must be 'local' or 'remote'")

    @staticmethod
    def get_folder_name(dataset):
        """
        Creates a unique folder name based on a dataset and timestamp. In some instances it may make sense to use the
        parent dataset in order to group files (e.g., in order to ensure files are not uploaded multiple times).

        This is only relevant for remote mode based on file management.
        """
        return datetime.datetime.fromtimestamp(dataset.timestamp).strftime("%Y-%m-%d-%H%M%S") + '-' + \
            ''.join(e if e.isalnum() else '_' for e in dataset.get_label()) + '-' + \
            str(dataset.key)

    @staticmethod
    def count_local_files(directory):
        """
        Get number of files in directory
        """
        return len(os.listdir(directory))
