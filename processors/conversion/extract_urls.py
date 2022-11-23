"""
Extract URLs from columns

Optionally expand shortened URLs (from Stijn's expand_url_shorteners)
"""
import csv
import re
import time
import requests

from common.lib.exceptions import ProcessorInterruptedException
from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput
from processors.filtering.expand_url_shorteners import UrlUnshortener

__author__ = "Dale Wahl"
__credits__ = ["Stijn Peeters", "Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)


class ExtractURLs(BasicProcessor):
    """
    Retain only posts where a given column matches a given value
    """
    type = "extract-urls-filter"  # job type ID
    category = "Conversion"  # category
    title = "Extract URLs (and optionally expand)"  # title displayed in UI
    description = "Extract any URLs from selected column(s) and, optionally, expand any shortened URLs. This will create" \
                  " a new dataset."
    extension = "csv"

    options = {
        "columns": {
            "type": UserInput.OPTION_TEXT,
            "help": "Columns to extract URLs",
            "default": "body",
            "inline": True,
            "tooltip": "If column contains a single URL, use that URL; else, try to find image URLs in the column's content",
        },
        "expand_urls": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Expand shortened URLs",
            "tooltip": "This can take a long time for large datasets and it is NOT recommended to run this processor on datasets larger than 10,000 items.",
        },
        "return_matches_only": {
            "type": UserInput.OPTION_TOGGLE,
            "default": True,
            "help": "Only return rows with URLs",
            "tooltip": "If selected, only rows with URLs are added to the new dataset, else all rows are retained",
        },
    }

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        All processor on CSV and NDJSON datasets
        """
        return module.is_dataset() and module.get_extension() in ["csv", "ndjson"]

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        """
        Update "columns" option with parent dataset columns
        """
        options = cls.options
        # Get the columns for the select columns option
        if parent_dataset and parent_dataset.get_columns():
            columns = parent_dataset.get_columns()
            options["columns"]["type"] = UserInput.OPTION_MULTI
            options["columns"]["options"] = {v: v for v in columns}
            options["columns"]["default"] = "body" if "body" in columns else sorted(columns,
                                                                                    key=lambda k: "text" in k).pop()
        return options

    def process(self):
        """
        Extract URLs and optionally excand them from URL shorteners

        Replaces redirect URLs on a best-effort basis. Redirects with a status
        code outside the 200-399 range are ignored.
        """
        self.dataset.update_status("Searching for URLs")

        # Get match column parameters
        columns = self.parameters.get("columns", [])
        if type(columns) == str:
            columns = [columns]
        expand_urls = self.parameters.get("expand_urls", False)
        return_matches_only = self.parameters.get("return_matches_only", True)

        # Create fieldnames
        fieldnames = ["id", "extracted_urls"] + ["extracted_from_" + column for column in columns]

        # Avoid requesting the same URL multiple times
        cache = {}

        # write a new file with the updated links
        with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()

            processed_items = 0
            url_matches_found = 0
            total_items = self.source_dataset.num_rows
            for item in self.source_dataset.iterate_items(self):
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while iterating through items")

                row = {
                    "id": item["id"],
                    "extracted_urls": set(),
                }

                for column in columns:
                    value = item.get(column)
                    if not value:
                        continue
                    if type(value) != str:
                        self.dataset.update_status(f"Column \"{column}\" is not text and will be ignored.")
                        # Remove from future
                        columns.remove(column)
                        continue

                    # Check for links
                    identified_urls = self.identify_links(value)

                    # Expand url shorteners
                    if expand_urls:
                        identified_urls = [self.resolve_redirect(url=url, redirect_domains=UrlUnshortener.redirect_domains, cache=cache) for url in identified_urls]

                    # Add identified links
                    row["extracted_from_"+column] = identified_urls
                    row["extracted_urls"] |= set(identified_urls)

                if (return_matches_only and row["extracted_urls"]) or not return_matches_only:
                    # Edit list/sets
                    for column in fieldnames:
                        if type(row[column]) in [list, set]:
                            row[column] = ','.join(row[column])
                    writer.writerow(row)
                    url_matches_found += 1

                processed_items += 1
                if processed_items % (total_items / 10) == 0:
                    self.dataset.update_status(f"Extracted {url_matches_found} URLs from {processed_items}/{total_items} items")
                    self.dataset.update_progress(processed_items / total_items)

        self.dataset.finish(url_matches_found)

    @staticmethod
    def resolve_redirect(url, redirect_domains, cache={}, depth=0):
        """
        Attempt to resolve redirects

        :param str url: URL to check for redirect
        :param tuple redirect_domains: Tuple with all domains to check for redirects
        :param dict cache: URL cache updated with original cache[original_url] = redirect_url
        :param int depth: Number of redirects to attempt to follow
        :return str: Original url or new url for redirects
        """
        # Can use regex.sub() instead of string
        if hasattr(url, "group"):
            url = url.group(0)

        # get host name to compare to list of shorteners
        host_name = re.sub(r"^[a-z]*://", "", url).split("/")[0].lower()

        if depth >= 10:
            return url

        elif "api.parler.com/l" not in url and host_name not in redirect_domains:
            # skip non-redirects
            return url

        elif url in cache:
            return cache[url]

        # to avoid infinite recursion, do not go deeper than 5 loops and
        # keep track of current depth here:
        depth += 1

        # do this explicitly because it is a known issue and will save
        # one request
        if host_name == "t.co" and "http://" in url:
            url = url.replace("http://", "https://")

        try:
            time.sleep(0.1)
            head_request = requests.head(url, timeout=5)
        except (requests.RequestException, ConnectionError, ValueError, TimeoutError) as e:
            return url

        # if the returned page's status code is in the 'valid request'
        # range, and if it has a Location header different from the page's
        # url, recursively resolve the page it redirects to up to a given
        # depth - infinite recursion is prevented by using a cache
        if 200 <= head_request.status_code < 400:
            redirected_to = head_request.headers.get("Location", url)
            if redirected_to != url:
                cache[url] = redirected_to
                return ExtractURLs.resolve_redirect(redirected_to, redirect_domains, cache, depth)

        return url

    @staticmethod
    def identify_links(text):
        """
        Search string of text for URLs that may contain links.

        :param str text:  string that may contain URLs
        :return list:  	  list containing validated URLs to videos
        """
        # Extracting all links
        # From https://stackoverflow.com/questions/6038061/regular-expression-to-find-urls-within-a-string
        link_regex = re.compile(r"(http|ftp|https):\/\/([\w_-]+(?:(?:\.[\w_-]+)+))([\w.,@?^=%&:\/~+#-]*[\w@?^=%&\/~+#-])", re.IGNORECASE)
        # Could also try: https://stackoverflow.com/questions/161738/what-is-the-best-regular-expression-to-check-if-a-string-is-a-valid-url
        return [f"{url[0]}://{url[1]}{url[2]}" for url in link_regex.findall(text)]
