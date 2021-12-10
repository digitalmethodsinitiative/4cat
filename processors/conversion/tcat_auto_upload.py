"""
Send TCAT-ready json to a particular TCAT instance
"""
import requests
import random
from urllib.parse import urlparse

from backend.abstract.processor import BasicProcessor
from common.lib.user_input import UserInput

import config

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl", "Stijn Peeters"]
__maintainer__ = "Dale Wahl"
__email__ = "d.l.wahl@uva.nl"


class FourcatToDmiTcatUploader(BasicProcessor):
    """
    Send TCAT-ready json to a particular TCAT instance.
    File to  be imported by TCAT's import-jsondump.php
    """
    type = "tcat-auto-upload"  # job type ID
    category = "Conversion"  # category
    title = "Upload to DMI-TCAT"  # title displayed in UI
    description = "Send TCAT-ready json to a particular DMI-TCAT instance."  # description displayed in UI
    extension = "html"  # extension of result file, used internally and in UI

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Determine if processor is compatible with dataset

        It is if TCAT credentials have been configured and the input is a
        TCAT-compatible file.

        :param module: Dataset or processor to determine compatibility with
        """
        return module.type == "convert-ndjson-for-tcat" and \
            hasattr(config, 'TCAT_SERVER') and \
            config.TCAT_SERVER and \
            hasattr(config, 'TCAT_TOKEN') and \
            hasattr(config, 'TCAT_USERNAME') and \
            hasattr(config, 'TCAT_PASSWORD')

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        """
        Get processor options

        Give the user the choice of where to upload the dataset, if multiple
        TCAT servers are configured. Otherwise, no options are given since
        there is nothing to choose.

        :param DataSet parent_dataset:  Dataset that will be uploaded
        :param User user:  User that will be uploading it
        :return dict:  Option definition
        """
        if hasattr(config, "TCAT_SERVER") and type(config.TCAT_SERVER) in (set, list, tuple) and len(config.TCAT_SERVER) > 1:
            return {
                "server": {
                    "type": UserInput.OPTION_CHOICE,
                    "options": {
                        "random": "Choose one based on available capacity",
                        **{
                            url: url for url in config.TCAT_SERVER
                        }
                    },
                    "default": "random",
                    "help": "Instance to upload to",
                    "tooltip": "Which TCAT instance to upload the dataset to. If you do not choose one, 4CAT will "
                               "upload the dataset to the instance with the highest available capacity."
                }
                # todo: actually make it choose one that way instead of choosing at random
            }
        else:
            return {}

    def process(self):
        """
        Send TCAT-ready json to a particular TCAT instance.
        """
        self.dataset.update_status("Preparing upload")
        bin_name = ''.join(e if e.isalnum() else '_' for e in self.dataset.top_parent().get_label())
        self.dataset.log('Label for DMI-TCAT bin_name: ' + bin_name)

        url_to_file = self.dataset.get_parent().get_result_url()
        self.dataset.log('File location URL: ' + url_to_file)

        query = str(self.dataset.top_parent().get_parameters().get("query", ""))
        self.dataset.log('Twitter query: ' + query)

        # TCAT authorization information
        auth = (config.TCAT_USERNAME, config.TCAT_PASSWORD)

        # find server URL
        server_choice = self.parameters.get("server", "random")
        if type(config.TCAT_SERVER) in (list, set, tuple):
            if server_choice == "random" or server_choice not in config.TCAT_SERVER:
                server_choice = random.choice(config.TCAT_SERVER)
        else:
            server_choice = config.TCAT_SERVER

        # DOCKER shenanigans
        if 'host.docker.internal' in server_choice:
            url_to_file = url_to_file.replace('localhost', 'host.docker.internal')
            self.dataset.log('Server is a Docker container, new URL: ' + url_to_file)

        # sanitize server URL and send the file to it
        # todo: chunk it
        parsed_uri = urlparse(server_choice)
        post_json_url = '{uri.scheme}://{uri.netloc}'.format(uri=parsed_uri)
        post_json_url = post_json_url + '/api/import-from-4cat.php'
        self.dataset.update_status("Sending dataset to DMI-TCAT: %s" % post_json_url)
        response = requests.post(post_json_url, auth=auth, data={
                                                'url': url_to_file,
                                                'name': bin_name,
                                                'query': query,
                                                'token': config.TCAT_TOKEN,
                                                })

        if response.status_code == 404:
            return self.dataset.finish_with_error("Cannot upload dataset to DMI-TCAT server: server responded with 404 not found.")
        elif response.status_code != 200:
            return self.dataset.finish_with_error("Cannot upload dataset to DMI-TCAT server: server responded with %i %s." % (response.status_code, str(response.reason)))

        try:
            resp_content = response.json()
        except ValueError:
            # If import-jsondump.php fails, no json response is returned
            if 'The query bin' in response.text and 'already exists' in response.text:
                # Query bin already uploaded
                # This should not happen - a duplicate is created instead
                # TODO: look at possibility to add to existing bin?
                return self.dataset.finish_with_error("DMI-TCAT bin already exists; unable to add to existing bin.")
            else:
                # Something else is wrong...
                self.log.error('DMI-TCAT Unexpected response: %s - %s - %s' % (response.status_code, str(response.reason), response.text))
                return self.dataset.finish_with_error( "DMI-TCAT returned an unexpected response; the server may be misconfigured. Could not upload.")

        if 'success' not in resp_content:
            # A json response was returned, but not the one we're expecting!
            self.log.error('DMI-TCAT Unexpected response: %s - %s - %s' %  (response.status_code, str(response.reason), response.text))
            return self.dataset.finish_with_error("DMI-TCAT returned an unexpected response; the server may be misconfigured. Could not upload.")

        elif not resp_content['success']:
            # success should be True if upload was successful
            return self.dataset.finish_with_error("Error while importing to DMI-TCAT: %s" % resp_content['error'])

        self.dataset.update_status("Waiting for upload to complete")

        self.dataset.update_status("Upload complete, writing HTML file")
        # Create HTML file
        tcat_result_url = server_choice.replace('/api/import-from-4cat.php', '').rstrip('/') + '/analysis/index.php?dataset=' + bin_name
        html_file = self.get_html_page(tcat_result_url)

        # Write HTML file
        with self.dataset.get_results_path().open("w", encoding="utf-8") as output_file:
            output_file.write(html_file)

        # Finish
        self.dataset.update_status("Finished")
        self.dataset.finish(self.dataset.top_parent().num_rows)

    def get_html_page(self, url):
        """
        Returns a html string to redirect to the location of the DMI-TCAT dataset.
        """
        return f"<head><meta http-equiv='refresh' content='0; URL={url}'></head>"
