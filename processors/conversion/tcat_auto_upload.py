"""
Send TCAT-ready json to a particular TCAT instance
"""
import requests
from urllib.parse import urlparse

from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorException

import config

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "d.l.wahl@uva.nl"


class ConvertNDJSONToJSON(BasicProcessor):
    """
    Send TCAT-ready json to a particular TCAT instance.
    File to  be imported by TCAT's import-jsondump.php
    """
    type = "tcat_auto_upload"  # job type ID
    category = "Conversion"  # category
    title = "Upload to TCAT"  # title displayed in UI
    description = "Send TCAT-ready json to a particular TCAT instance."  # description displayed in UI
    extension = "html"  # extension of result file, used internally and in UI

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Determine if processor is compatible with dataset

        :param module: Dataset or processor to determine compatibility with
        """
        return module.type == "convert-ndjson-for-tcat" and \
            hasattr(config, 'TCAT_SERVER') and \
            config.TCAT_SERVER and \
            hasattr(config, 'TCAT_TOKEN') and \
            hasattr(config, 'TCAT_USERNAME') and \
            hasattr(config, 'TCAT_PASSWORD')

    def process(self):
        """
        Send TCAT-ready json to a particular TCAT instance.
        """
        self.dataset.update_status("Preparing Arguments")
        bin_name = ''.join(e if e.isalnum() else '_' for e in self.dataset.top_parent().get_label())
        self.dataset.log('Label for TCAT bin_name: ' + bin_name)

        url_to_file = self.dataset.get_parent().get_result_url()
        self.dataset.log('File location URL: ' + url_to_file)

        # DOCKER shenanigans
        self.dataset.log('Docker search: ' + str('host.docker.internal' in config.TCAT_SERVER))
        if 'host.docker.internal' in config.TCAT_SERVER:
            url_to_file = url_to_file.replace('localhost', 'host.docker.internal')
            self.dataset.log('New URL: ' + url_to_file)

        query = str(self.dataset.top_parent().get_parameters().get("query", ""))
        self.dataset.log('Twitter query: ' + query)

        # TCAT authorization information
        auth = (config.TCAT_USERNAME, config.TCAT_PASSWORD)

        # from urlparse import urlparse  # Python 2
        parsed_uri = urlparse(config.TCAT_SERVER)
        post_json_url = '{uri.scheme}://{uri.netloc}'.format(uri=parsed_uri)
        post_json_url = post_json_url + '/api/import-from-4cat.php'
        self.dataset.update_status("Sending to TCAT: %s" % post_json_url)
        response = requests.post(post_json_url, auth=auth, data={
                                                'url': url_to_file,
                                                'name': bin_name,
                                                'query': query,
                                                'token': config.TCAT_TOKEN,
                                                })

        if response.status_code == 404:
            raise ProcessorException('TCAT URL 404 error at %s' % config.TCAT_SERVER)
        elif response.status_code != 200:
            raise ProcessorException('TCAT Connection Error %i error: %s' % (response.status_code, str(response.reason)))
        else:
            pass

        try:
            resp_content = response.json()
        except ValueError:
            # If import-jsondump.php fails, no json response is returned
            if 'The query bin' in response.text and 'already exists' in response.text:
                # Query bin already uploaded
                # TODO: look at possibility to add to existing bin?
                self.dataset.update_status("TCAT bin already exists; unable to add to existing bin.", is_final=True)
    			self.dataset.finish(0)
    			return
            else:
                # Something else is wrong...
                raise ProcessorException('TCAT Unexpected response: %s - %s - %s' %  (response.status_code, str(response.reason), response.text))

        if 'success' not in resp_content:
            # A json response was returned, but not the one we're expecting!
            raise ProcessorException('TCAT Unexpected response: %s - %s - %s' %  (response.status_code, str(response.reason), response.text))
        elif not resp_content['success']:
            # success should be True if upload was successful
            raise ProcessorException('TCAT Import failure: %s' % str(resp_content))
        else:
            pass

        self.dataset.update_status("Waiting for upload to complete")
        # Unsure how to query TCAT, invalid bin_name still returns 200 response
        # Could attempt to parse the resultant HTML

        self.dataset.update_status("Upload complete, writing HTML file")
        # Create HTML file
        tcat_result_url = config.TCAT_SERVER.replace('/api/import-from-4cat.php', '').rstrip('/') + '/analysis/index.php?dataset=' + bin_name
        html_file = self.get_html_page(tcat_result_url)

        # Write HTML file
        with self.dataset.get_results_path().open("w", encoding="utf-8") as output_file:
            output_file.write(html_file)

        # Finish
        self.dataset.update_status("Finished")
        self.dataset.finish(1)

    def get_html_page(self, url):
        """
        Returns a html string to redirect to PixPlot.
        """
        return f"<head><meta http-equiv='refresh' content='0; URL={url}'></head>"
