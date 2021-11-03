"""
Send TCAT-ready json to a particular TCAT instance
"""
import requests

from backend.abstract.processor import BasicProcessor

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
    extension = "json"  # extension of result file, used internally and in UI

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
            config.TCAT_TOKEN

    def process(self):
        """
        Send TCAT-ready json to a particular TCAT instance.
        """
        self.dataset.update_status("Preparing Arguments")
        bin_name = self.dataset.top_parent().get_label()
        self.dataset.log('Label for TCAT bin_name: ' + bin_name)

        filename = self.dataset.get_parent().get_results_path().name
        self.dataset.log('Filename of TCAT ready JSON: ' + filename)
        url_to_file = ('https://' if config.FlaskConfig.SERVER_HTTPS else 'http://') + \
                      config.FlaskConfig.SERVER_NAME + '/result/' + filename
        self.dataset.log('URL: ' + url_to_file)

        query = str(self.dataset.top_parent().get_parameters().get("query", ""))
        self.dataset.log('Twitter query: ' + query)

        self.dataset.update_status("Sending to TCAT")
        requests.post(config.TCAT_SERVER, data={
                                                'url': url_to_file,
                                                'name': bin_name,
                                                'query': query,
                                                'token': config.TCAT_TOKEN,
                                                })

        self.dataset.update_status("Waiting for upload to complete")
        # Unsure how to query TCAT, invalid bin_name still returns 200 response
        # Could attempt to parse the resultant HTML

        self.dataset.update_status("Upload complete, writing HTML file")
        # Create HTML file
        tcat_result_url = config.TCAT_SERVER.rstrip('/') + '/analysis/index.php?dataset=' + bin_name
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
