"""
Send TCAT-ready json to a particular TCAT instance
"""
import requests
import random
import json
from urllib.parse import urlparse

from backend.abstract.processor import BasicProcessor
from common.lib.user_input import UserInput
from common.lib.helpers import get_last_line

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

    config = {
    	# TCAT Server Connection Info
        'tcat-auto-upload.TCAT_SERVER': {
            'type': UserInput.OPTION_TEXT,
            'default' : "",
            'help': 'TCAT Server Address/URL',
            'tooltip': "",
            },
        'tcat-auto-upload.TCAT_USERNAME': {
            'type': UserInput.OPTION_TEXT,
            'default' : "",
            'help': 'TCAT Username',
            'tooltip': "",
            },
        'tcat-auto-upload.TCAT_PASSWORD': {
            'type': UserInput.OPTION_TEXT,
            'default' : "",
            'help': 'TCAT Password',
            'tooltip': "",
            },
        'tcat-auto-upload.TCAT_TOKEN': {
            'type': UserInput.OPTION_TEXT,
            'default' : "",
            'help': 'TCAT Security Token',
            'tooltip': "An Optional TCAT settting",
            },
        }

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Determine if processor is compatible with dataset

        It is if TCAT credentials have been configured and the input is a
        TCAT-compatible file.

        :param module: Dataset or processor to determine compatibility with
        """
        return module.type == "convert-ndjson-for-tcat" and \
            config.get('tcat-auto-upload.TCAT_SERVER') and \
            config.get('tcat-auto-upload.TCAT_TOKEN') and \
            config.get('tcat-auto-upload.TCAT_USERNAME') and \
            config.get('tcat-auto-upload.TCAT_PASSWORD')

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
        if config.get('tcat-auto-upload.TCAT_SERVER') and type(config.get('tcat-auto-upload.TCAT_SERVER')) in (set, list, tuple) and len(config.get('tcat-auto-upload.TCAT_SERVER')) > 1:
            return {
                "server": {
                    "type": UserInput.OPTION_CHOICE,
                    "options": {
                        "random": "Choose one based on available capacity",
                        **{
                            url: url for url in config.get('tcat-auto-upload.TCAT_SERVER')
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
        bin_name = ''.join(e if e.isalnum() else '_' for e in self.dataset.top_parent().get_label()).lower()
        self.dataset.log('Label for DMI-TCAT bin_name: ' + bin_name)

        url_to_file = self.dataset.get_parent().get_result_url()
        self.dataset.log('File location URL: ' + url_to_file)

        query = str(self.dataset.top_parent().get_parameters().get("query", ""))
        self.dataset.log('Twitter query: ' + query)

        # TCAT authorization information
        auth = (config.get('tcat-auto-upload.TCAT_USERNAME'), config.get('tcat-auto-upload.TCAT_PASSWORD'))

        # find server URL
        server_choice = self.parameters.get("server", "random")
        if type(config.get('tcat-auto-upload.TCAT_SERVER')) in (list, set, tuple):
            if server_choice == "random" or server_choice not in config.get('tcat-auto-upload.TCAT_SERVER'):
                server_choice = random.choice(config.get('tcat-auto-upload.TCAT_SERVER'))
        else:
            server_choice = config.get('tcat-auto-upload.TCAT_SERVER')

        # DOCKER shenanigans
        if 'host.docker.internal' in server_choice:
            url_to_file = url_to_file.replace('localhost', 'host.docker.internal')
            self.dataset.log('Server is a Docker container, new URL: ' + url_to_file)

        # Send request to TCAT server
        response = self.send_request_to_TCAT(server_choice, auth, url_to_file, bin_name, query)

        if response.status_code == 404:
            return self.dataset.finish_with_error("Cannot upload dataset to DMI-TCAT server: server responded with 404 not found.")
        if response.status_code == 504:

            # TODO: try a new TCAT server if there are more than one
            # TODO: save point: converted date could be saved and processor resumed here at a later point
            self.dataset.update_status("TCAT server currently busy; please try again later")
            return self.dataset.finish(0)
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
        # TODO: check for completion

        # Create HTML file
        self.dataset.update_status("Upload complete, writing HTML file")
        # GET first and last dates
        parent_file = self.dataset.get_parent().get_results_path()
        start_date, end_date = self.get_first_and_last_dates(parent_file)

        tcat_result_url = server_choice.replace('/api/import-from-4cat.php', '').rstrip('/') + '/analysis/index.php?dataset=' + bin_name + '&startdate=' + start_date + '&enddate=' + end_date
        html_file = self.get_html_page(tcat_result_url)

        # Write HTML file
        with self.dataset.get_results_path().open("w", encoding="utf-8") as output_file:
            output_file.write(html_file)

        # Finish
        self.dataset.update_status("Finished")
        self.dataset.finish(self.dataset.top_parent().num_rows)

    def send_request_to_TCAT(self, server_choice, auth, url_to_file, bin_name, query):
        """
        Send request to a TCAT server. Request contains authoriaztion to the TCAT instance,
        a url pointing where the file is stored on the 4CAT server, a name for the tweet "bin",
        and the original query used to collect the tweet data. TCAT will download the actual
        file.

        :param str server_choice:  url to a TCAT instance
        :param tuple auth:  (username, password) for TCAT instance
        :param str url_to_file:  url to file location on 4CAT
        :param str bin_name:  desired name of tweet bin for TCAT
        :param dict query:  parameters used to collect Twitter data
    	:return Response: requests response object
        """
        # sanitize server URL and send the url to the file location to it
        parsed_uri = urlparse(server_choice)
        post_json_url = '{uri.scheme}://{uri.netloc}'.format(uri=parsed_uri)
        post_json_url = post_json_url + '/api/import-from-4cat.php'
        self.dataset.update_status("Sending dataset to DMI-TCAT: %s" % post_json_url)
        response = requests.post(post_json_url, auth=auth, data={
                                                'url': url_to_file,
                                                'name': bin_name,
                                                'query': query,
                                                'token': config.get('tcat-auto-upload.TCAT_TOKEN'),
                                                })
        return response

    def get_html_page(self, url):
        """
        Returns a html string to redirect to the location of the DMI-TCAT dataset.
        """
        return f"<head><meta http-equiv='refresh' content='0; URL={url}'></head>"

    def get_first_and_last_dates(self, filename):
        """
        Grabs the first and last lines of filename and finds their 'created_at'
        dates to return
        """
        last_tweet = get_last_line(filename)
        last_tweet = json.loads(last_tweet)
        start_date = last_tweet.get('created_at', '')
        if start_date:
            # Just the date
            start_date = start_date[:10]

        with open(filename) as file:
            first_tweet = json.loads(file.readline())
        end_date = first_tweet.get('created_at', '')
        if end_date:
            end_date = end_date[:10]
        return start_date, end_date
