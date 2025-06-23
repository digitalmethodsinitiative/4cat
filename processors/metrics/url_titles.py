"""
Retrieve HTML title (and other metadata) for URLs
"""
import csv

from backend.lib.processor import BasicProcessor
from backend.lib.proxied_requests import FailedProxiedRequest
from common.lib.helpers import UserInput
from common.lib.exceptions import ProcessorInterruptedException

import warnings
import urllib3
import ural

from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class URLFetcher(BasicProcessor):
    """
    Retrieve HTML title (and other metadata) for URLs
    """
    type = "url-metadata"  # job type ID
    category = "Post metrics"  # category
    title = "Fetch URL metadata"  # title displayed in UI
    description = ("Fetches the page title and other metadata for URLs referenced in the dataset. Makes a request to "
                   "each URL, optionally following HTTP redirects.")  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    followups = []

    options = {
        "columns": {
            "type": UserInput.OPTION_TEXT,
            "help": "Column(s) to get URLs from",
            "default": "body"
        },
        "follow-redirects": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Follow redirects?",
            "default": True,
            "tooltip": "Follow HTTP redirects (status 301 or 302) and report on the URL redirected to instead of the "
                       "original URL"
        },
        "ignore-duplicates": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Ignore duplicates?",
            "default": True,
            "tooltip": "If enabled, only include the first occurrence of a URL. Otherwise, a row will be included in "
                       "the output CSV file for each separate occurrence of the URL. Note that each URL is only "
                       "requested once regardless."
        }
    }

    config = {
        "url-metadata.timeout": {
            "type": UserInput.OPTION_TEXT,
            "coerce_type": float,
            "default": 60.0,
            "help": "Timeout",
            "tooltip": "Time to wait before cancelling a request and potentially trying again"
        }
    }

    @staticmethod
    def is_compatible_with(module=None, user=None):
        """
        Determine compatibility

        :param Dataset module:  Module ID to determine compatibility with
        :return bool:
        """
        return module.is_top_dataset() and module.get_extension() in ("csv", "ndjson")

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        """
        Get processor options

        This method by default returns the class's "options" attribute, or an
        empty dictionary. It can be redefined by processors that need more
        fine-grained options, e.g. in cases where the availability of options
        is partially determined by the parent dataset's parameters.

        :param DataSet parent_dataset:  An object representing the dataset that
        the processor would be run on
        :param User user:  Flask user the options will be displayed for, in
        case they are requested for display in the 4CAT web interface. This can
        be used to show some options only to privileges users.
        """
        options = cls.options

        if parent_dataset and parent_dataset.get_columns():
            columns = parent_dataset.get_columns()
            options["columns"]["type"] = UserInput.OPTION_MULTI
            options["columns"]["inline"] = True
            options["columns"]["options"] = {v: v for v in columns}
            options["columns"]["default"] = ["body"]

        return options

    def process(self):
        """
        Extracts URLs from the dataset, fetches metadata for each URL, and
        writes the results to a CSV file
        """

        columns = self.parameters.get("columns")
        follow_redirects = self.parameters.get("follow-redirects")
        ignore_dupes = self.parameters.get("ignore-duplicates")
        if type(columns) is not list:
            columns = [columns]

        # first fetch all URLs from the dataset
        all_urls = {}

        # we're not interested in verifying certificates
        # we *should* be, properly, but the chance of encountering a bad
        # certificate is relatively high, and we want to get metadata in that
        # case as well
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        warnings.simplefilter("ignore", category=MarkupResemblesLocatorWarning)

        self.dataset.update_status("Finding URLs in dataset")
        for item in self.source_dataset.iterate_items(self):
            # combine column contents that we need to extract URLs from
            source_text = " ".join([str(item[column]) for column in columns])
            urls = ural.urls_from_text(source_text)

            for url in urls:
                if url not in all_urls:
                    all_urls[url] = {
                        "items": [],
                        "retries": 0,
                        "retry_after": 0
                    }
                elif ignore_dupes:
                    continue

                # we're only going to request each URL once, but they might be
                # used in multiple items. so save references to all items per
                # URL; save item ID and timestamp, which we will include in the
                # output later
                all_urls[url]["items"].append({k: v for k, v in item.items() if k in ("id", "thread_id", "timestamp")})

        self.dataset.log(f"Found {len(all_urls):,} in dataset.")

        # now start fetching things
        with self.dataset.get_results_path().open("w", newline="") as outfile:
            fieldnames = ("item_id", "thread_id", "item_timestamp", "url", "final_url", "domain_name", "status",
                          "status_code", "reason", "title")

            self.writer = csv.DictWriter(outfile, fieldnames=fieldnames)
            self.writer.writeheader()
            urls_failed = 0
            urls_success = 0

            ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0"

            for url, response in self.iterate_proxied_requests(
                    all_urls,
                    preserve_order=False,
                    headers={"User-Agent": ua}, hooks={
                        # use hooks to download the content (stream=True) in parallel
                        "response": URLFetcher.stream_url
                    },
                    verify=False,
                    timeout=self.config.get("url-metadata.timeout", 70),
                    allow_redirects=follow_redirects,
                    stream=True
            ):
                if self.interrupted:
                    self.flush_proxied_requests()
                    raise ProcessorInterruptedException()

                if type(response) is FailedProxiedRequest:
                    self.dataset.log(
                        f"Error getting URL {url} ({response.context}), skipping")
                    urls_failed += 1
                else:
                    urls_success += 1
                    for item in all_urls[url]["items"]:
                        self.writer.writerow({
                            "item_id": item["id"],
                            "thread_id": item["thread_id"],
                            "item_timestamp": item["timestamp"],
                            "url": url,
                            "final_url": response.url,
                            "domain_name": ural.get_domain_name(response.url),
                            "status": "success",
                            "status_code": response.status_code,
                            "reason": response.reason,
                            "title": response.page_title
                        })

                self.dataset.update_status(f"Processed {(urls_failed + urls_success):,} of {len(all_urls):,} URLs")
                self.dataset.update_progress((urls_failed + urls_success) / len(all_urls))

        # log warning if not everything succeeded
        if urls_failed:
            self.dataset.update_status(f"URLs fetched, but {urls_failed:,} URL(s) could not be retrieved. See dataset "
                                       f"log for details.", is_final=True)

        # and write everything to a CSV
        self.dataset.finish(urls_failed + urls_success)
        self.job.finish()

    @staticmethod
    def stream_url(response, *args, **kwargs):
        """
        Helper function for fetch_urls

        To avoid very large responses clogging up the processor, we use this
        for a requests hook to only download that part of the response needed
        to determine the page title.

        We store the title in the (custom) 'page_title' property of the
        response.

        :param requests.Response response: requests response object
        """
        response._content_consumed = True
        response._content = False
        response.page_title = ""

        # we set _content_consumed and _content here because if not, requests
        # will (in some situations) attempt to read more of the data later when
        # resolving result() on the future of the request, and that will not
        # end well

        if not response.encoding and not response.ok:
            return

        # we don't know where in the page the title tag is
        # so read in chunks until we find one (or we hit the max)
        preamble = bytes()

        while len(preamble) < 500000:
            chunk = response.raw.read(1024, decode_content=True)
            if not chunk:
                break

            preamble += chunk
            soup = BeautifulSoup(preamble, "lxml")
            if soup.title and soup.title.text:
                response.page_title = soup.title.text
                break

        response.raw.close()
        response._content = preamble
