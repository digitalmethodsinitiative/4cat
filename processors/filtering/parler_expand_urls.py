"""
Expand Parler redirect URLs in Parler datasets
"""
import requests
import shutil
import time
import csv

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
    type = "expand-parler-urls"  # job type ID
    category = "Filtering"  # category
    title = "Expand Parler URLs"  # title displayed in UI
    description = "Expand Parler redirect URLs. By default Parler replaces all links in posts with a parler-owned redirect URL. This processor expands those URLs so they refer to the original URL. Not recommended for very large (10,000+ posts) datasets."  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    datasources = ["parler"]

    input = "csv:body"
    output = "csv"

    def process(self):
        """
        Expand Parler redirect URLs.

        By default Parler replaces all links in posts with a parler-owned redirect URL. This processor expands those
        URLs so they refer to the original URL.
        """

        # get field names
        with self.source_file.open() as input:
            reader = csv.DictReader(input)
            fieldnames = reader.fieldnames

        self.dataset.update_status("Processing posts")
        # write a new file with the updated links
        with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            processed = 0

            for post in self.iterate_csv_items(self.source_file):
                expanded_urls = []

                # go through links and do a HEAD request for all of them to figure out the redirect location
                if post["urls"]:
                    for url in post["urls"].split(","):
                        if not "api.parler.com/l" in url:
                            # skip non-redirects
                            expanded_urls.append(url)
                            continue

                        try:
                            headers = requests.head(url).headers
                        except (requests.RequestException, ConnectionError):
                            # bummer, but best to just leave as-is in this case
                            pass

                        expanded_urls.append(headers.get("Location", url))

                    post["urls"] = ",".join(expanded_urls)
                    time.sleep(0.25)  # is this needed in this case? is it big enough?

                writer.writerow(post)
                processed += 1
                if processed % 25 == 0:
                    self.dataset.update_status("Processed %i Parler posts" % processed)

        # now comes the big trick - replace original dataset with updated one
        parent = self.dataset.get_genealogy()[0]
        shutil.move(self.dataset.get_results_path(), parent.get_results_path())

        self.dataset.update_status("Parent dataset updated.")
        self.dataset.finish(processed)
