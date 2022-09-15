"""
Selenium Webpage HTML Scraper

Currently designed around Firefox, but can also work with Chrome; results may vary
"""
from pathlib import Path

from backend.abstract.search import Search
from common.lib.user_input import UserInput


class MakeScreenshots(Search):
    """
    Get HTML via the Selenium webdriver and Firefox browser
    """
    type = "screenshot-generator-search"  # job ID
    extension = "zip"
    max_workers = 1

    options = {
        "intro-1": {
            "type": UserInput.OPTION_INFO,
            "help": "go go go"
        }
    }

    def get_items(self, query):
        """
        Separate and check urls, then loop through each and collects the HTML.

        :param query:
        :return:
        """
        staging_area = self.dataset.get_staging_area()
        dummy_file = Path(staging_area, "test.json")
        with dummy_file.open("w") as outfile:
            outfile.write("hello")

        return [staging_area]

    @staticmethod
    def validate_query(query, request, user):
        """
        Validate input for a dataset query on the Selenium Webpage Scraper.

        Will raise a QueryParametersException if invalid parameters are
        encountered. Parameters are additionally sanitised.

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param User user:  User object of user who has submitted the query
        :return dict:  Safe query parameters
        """
        return {}
