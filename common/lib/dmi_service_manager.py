"""
DMI Service Manager
"""
import datetime
import os
import time
from json import JSONDecodeError

import requests
from pathlib import Path


__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


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


class DmiServiceManager:
    """

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
            return True, resp.json()
        elif resp.status_code in [400, 500, 503]:
            return False, resp.json()
        else:
            self.processor.log.warning("Unknown response from DMI Service Manager: %s" % resp.text)
            return False, None

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
            current_completed = self.count_local_files(self.path_to_results)
        elif self.local_or_remote == "remote":
            existing_files = self.request_folder_files(self.server_file_collection_name)
            current_completed = len(existing_files.get(self.server_results_folder_name, []))
        else:
            raise DmiServiceManagerException("dmi_service_manager.local_or_remote setting must be 'local' or 'remote'")

        if current_completed != self.processed_files:
            self.processor.dataset.update_status(
                f"Collected text from {current_completed} of {self.num_files_to_process} files")
            self.processor.dataset.update_progress(current_completed / self.num_files_to_process)
            self.processed_files = current_completed

    def send_request_and_wait_for_results(self, service_endpoint, data, wait_period=60):
        """
        Send request and wait for results to be ready.
        """
        if self.local_or_remote == "local":
            service_endpoint += "_local"
        elif self.local_or_remote == "remote":
            service_endpoint += "_remote"
        else:
            raise DmiServiceManagerException("dmi_service_manager.local_or_remote setting must be 'local' or 'remote'")

        api_endpoint = self.server_address + service_endpoint
        resp = requests.post(api_endpoint, json=data, timeout=30)
        if resp.status_code == 202:
            # New request successful
            results_url = api_endpoint + "?key=" + resp.json()['key']
        else:
            try:
                resp_json = resp.json()
                raise DmiServiceManagerException(f"DMI Service Manager error: {str(resp.status_code)}: {str(resp_json)}")
            except JSONDecodeError:
                # Unexpected Error
                raise DmiServiceManagerException(f"DMI Service Manager error: {str(resp.status_code)}: {str(resp.text)}")

        # Wait for results to be ready
        self.processor.dataset.update_status(f"Generating results for {service_endpoint}...")

        check_time = time.time()
        success = False
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
                self.check_progress()

                result = requests.get(results_url, timeout=30)
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
            # Update list of result files
            existing_files = self.request_folder_files(self.server_file_collection_name)
            result_files = existing_files.get(self.server_results_folder_name, [])

            self.download_results(result_files, self.server_file_collection_name, self.server_results_folder_name, local_output_dir)

    def request_folder_files(self, folder_name):
        """
        Request files from a folder on the DMI Service Manager server.
        """
        filename_url = f"{self.server_address}list_filenames?folder_name={folder_name}"
        filename_response = requests.get(filename_url, timeout=30)

        # Check if 4CAT has access to this PixPlot server
        if filename_response.status_code == 403:
            raise DmiServiceManagerException("403: 4CAT does not have permission to use the DMI Service Manager server")

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
        uploaded_files = existing_files.get('files', [])
        if len(uploaded_files) > 0:
            self.processor.dataset.update_status("Found %i files previously uploaded" % (len(uploaded_files)))

        # Compare files with previously uploaded
        to_upload_filenames = [filename for filename in files_to_upload if filename not in uploaded_files]

        if len(to_upload_filenames) > 0 or results_name not in existing_files:
            # TODO: perhaps upload one at a time?
            api_upload_endpoint = f"{self.server_address}send_files"

            # Create a blank file to upload into results folder
            empty_placeholder = f"4CAT_{results_name}_blank.txt"
            with open(dir_with_files.joinpath(empty_placeholder), 'w') as file:
                file.write('')

            self.processor.dataset.update_status(f"Uploading {len(to_upload_filenames)} files")
            response = requests.post(api_upload_endpoint,
                                     files=[('files', open(dir_with_files.joinpath(file), 'rb')) for file in
                                            to_upload_filenames] + [
                                               (results_name, open(dir_with_files.joinpath(empty_placeholder), 'rb'))],
                                     data=data, timeout=120)

            if response.status_code == 200:
                self.processor.dataset.update_status(f"Files uploaded: {len(to_upload_filenames)}")
            elif response.status_code == 403:
                raise DmiServiceManagerException("403: 4CAT does not have permission to use the DMI Service Manager server")
            elif response.status_code == 405:
                raise DmiServiceManagerException("405: Method not allowed; check DMI Service Manager server address (perhaps http is being used instead of https)")
            else:
                self.processor.dataset.update_status(f"Unable to upload {len(to_upload_filenames)} files!")

        server_path_to_files = Path(file_collection_name).joinpath("files")
        server_path_to_results = Path(file_collection_name).joinpath(results_name)

        return server_path_to_files, server_path_to_results

    def download_results(self, filenames_to_download, file_collection_name, folder_name, local_output_dir):
        """
        Download results from the DMI Service Manager server.

        :param list filenames_to_download:  List of filenames to download
        :param str file_collection_name:    Name of collection where files were uploaded and results stored
        :param str folder_name:             Name of subfolder where files are localed (e.g. "results_name" or "files")
        :param Path local_output_dir:       Local Path to download files to
        :param Dataset dataset:             Dataset object for status updates
        """
        # Download the result files
        api_upload_endpoint = f"{self.server_address}uploads/"
        for filename in filenames_to_download:
            file_response = requests.get(api_upload_endpoint + f"{file_collection_name}/{folder_name}/{filename}", timeout=30)
            self.processor.dataset.update_status(f"Downloading {filename}...")
            with open(local_output_dir.joinpath(filename), 'wb') as file:
                file.write(file_response.content)

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
