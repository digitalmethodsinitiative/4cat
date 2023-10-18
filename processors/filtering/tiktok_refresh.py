"""
Refresh a TikTok datasource
"""
import asyncio
import json

from datasources.tiktok_urls.search_tiktok_urls import TikTokScraper
from backend.lib.processor import BasicProcessor


__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class UpdateTikTok(BasicProcessor):
    type = "tiktok-update-filter"  # job type ID
    category = "Filtering"  # category
    title = "Recollect TikTok data"  # title displayed in UI
    description = "Queries the same TikTok URLs in order to refresh data such as video URLs."
    extension = "ndjson"

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow processor on NDJSON and CSV files

        :param module: Module to determine compatibility with
        """
        return module.type in ["tiktok-search", "tiktok-urls-search"]

    def process(self):
        """
        Reads a file, filtering items that match in the required way, and
        creates a new dataset containing the matching values
        """
        # Write the posts
        num_posts = 0

        # Loop through items and collect URLs
        urls = []
        for original_item, mapped_item in self.source_dataset.iterate_mapped_items(self):
            url = mapped_item.get("tiktok_url")
            if url:
                urls.append(mapped_item.get("tiktok_url"))

        if not urls:
            self.dataset.update_status("Unable to extract TikTok URLs", is_final=True)
            self.dataset.finish(0)

        self.dataset.update_status(f"Collected {len(urls)} to refresh.")
        tiktok_scraper = TikTokScraper(processor=self, config=self.config)
        loop = asyncio.new_event_loop()
        items = loop.run_until_complete(tiktok_scraper.request_metadata(urls))

        with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as outfile:
            for post in items:
                outfile.write(json.dumps(post) + "\n")
                num_posts += 1

        if num_posts == 0:
            self.dataset.update_status("No URLs were able to be refreshed", is_final=True)

        if self.dataset.is_finished():
            self.dataset.log("Processor already marked dataset as finished prior to saving file!")
            return
        self.dataset.finish(num_posts)

    def after_process(self):
        super().after_process()

        # Request standalone
        standalone = self.create_standalone()
        # Update the type
        standalone.type = "tiktok-urls-search"

    @classmethod
    def is_filter(cls):
        """
        I'm a filter! And so are my children.
        """
        return True
