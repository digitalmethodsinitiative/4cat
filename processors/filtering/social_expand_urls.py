"""
Expand Parler redirect URLs in Parler datasets
"""
import requests
import shutil
import time
import csv
import re

from backend.abstract.processor import BasicProcessor

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)


class ParlerURLExpander(BasicProcessor):
    """
    Expand Parler URL redirects
    """
    type = "expand-social-urls"  # job type ID
    category = "Filtering"  # category
    title = "Expand Social Media Redirect URLs"  # title displayed in UI
    description = "Expand Twitter and Parler redirect URLs. By default Parler replaces all links in posts with a parler-owned redirect URL. This processor expands those URLs so they refer to the original URL. Not recommended for very large (10,000+ posts) datasets."  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    datasources = ["parler", "custom"]

    input = "csv:body"
    output = "csv"

    def process(self):
        """
        Expand Parler redirect URLs.

        By default Parler replaces all links in posts with a parler-owned redirect URL. This processor expands those
        URLs so they refer to the original URL.
        """

        # get field names
        fieldnames = self.get_item_keys(self.source_file)

        self.dataset.update_status("Processing posts")

        def replace_url(url):
            if hasattr(url, "group"):
                url = url.group(0)

            if not "api.parler.com/l" in url and not "t.co" in url:
                # skip non-redirects
                return url

            try:
                headers = requests.head(url).headers
                time.sleep(0.25)
            except (requests.RequestException, ConnectionError):
                # bummer, but best to just leave as-is in this case
                return url

            return headers.get("Location", url)

        # write a new file with the updated links
        with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            processed = 0

            for post in self.iterate_items(self.source_file):
                expanded_urls = []

                post["body"] = re.sub(r"https?://[^\s]+", replace_url, post["body"])

                # go through links and do a HEAD request for all of them to figure out the redirect location
                if post.get("urls"):
                    for url in post["urls"].split(","):
                        expanded_urls.append(replace_url(url))

                    post["urls"] = ",".join(expanded_urls)

                writer.writerow(post)
                processed += 1
                if processed % 25 == 0:
                    self.dataset.update_status("Processed %i posts" % processed)

        # now comes the big trick - replace original dataset with updated one
        parent = self.dataset.get_genealogy()[0]
        shutil.move(self.dataset.get_results_path(), parent.get_results_path())

        self.dataset.update_status("Parent dataset updated.")
        self.dataset.finish(processed)
