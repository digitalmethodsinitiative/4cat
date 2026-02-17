"""
Download images linked in dataset
"""
import requests
import urllib3
import shutil
import json
import re

from PIL import Image, UnidentifiedImageError
from requests.structures import CaseInsensitiveDict

from common.lib.helpers import UserInput, url_to_filename
from backend.lib.processor import BasicProcessor
from backend.lib.proxied_requests import FailedProxiedRequest
from common.lib.exceptions import ProcessorInterruptedException, FourcatException

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class InvalidDownloadedFileException(FourcatException):
    pass


class ImageDownloader(BasicProcessor):
    """
    Image downloader

    Downloads top images and saves as zip archive
    """

    type = "image-downloader"  # job type ID
    category = "Visual"  # category
    title = "Download images"  # title displayed in UI
    description = (
        "Download images and store in a a zip file. May take a while to complete as images are retrieved "
        "externally. Note that not always all images can be saved. For imgur galleries, only the first "
        "image is saved. For animations (GIFs), only the first frame is saved if available. A JSON metadata file "
        "is included in the output archive."
    )  # description displayed in UI
    extension = "zip"  # extension of result file, used internally and in UI
    media_type = "image"  # media type of the dataset

    followups = [
        "image-wall",
        "image-category-wall",
        "pix-plot",
        "image-to-categories",
        "image-captions",
        "text-from-images",
        "metadata-viewer",
        "clarifai-api",
        "google-vision-api",
    ]

    config = {
        "image-downloader.max": {
            "type": UserInput.OPTION_TEXT,
            "coerce_type": int,
            "default": 1000,
            "help": "Max images to download",
            "tooltip": "Only allow downloading up to this many images per batch. Increasing this can easily lead to "
            "very long-running processors and large datasets. Set to 0 for no limit.",
        }
    }

    @classmethod
    def get_options(cls, parent_dataset=None, config=None):
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
        options = {
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "default": 100,
            },
            "columns": {
                "type": UserInput.OPTION_TEXT,
                "help": "Column to get image links from",
                "default": "image_url",
                "inline": True,
                "tooltip": "If column contains a single URL, use that URL; else, try to find image URLs in the column's content",
            },
            "split-comma": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Split column values by comma?",
                "default": True,
                "tooltip": "If enabled, columns can contain multiple URLs separated by commas, which will be considered "
                "separately",
            },
        }

        # Update the amount max and help from config
        max_number_images = int(config.get("image-downloader.max", 1000))
        if max_number_images != 0:
            options["amount"]["help"] = f"No. of images (max {max_number_images})"
            options["amount"]["max"] = max_number_images
            options["amount"]["min"] = 1
        else:
            # 0 can download all images
            options["amount"]["help"] = "No. of images"
            options["amount"]["min"] = 0
            options["amount"]["tooltip"] = "Set to 0 to download all images"

        # Get the columns for the select columns option
        if parent_dataset and parent_dataset.get_columns():
            columns = parent_dataset.get_columns()
            options["columns"]["type"] = UserInput.OPTION_MULTI
            options["columns"]["options"] = {v: v for v in columns}
            # Pick a good default
            if "image_url" in columns:
                options["columns"]["default"] = "image_url"
            elif any("image" in (col or "").lower() for col in columns):
                # Any image will do
                image_cols = sorted(
                    [col for col in columns if "image" in (col or "").lower()],
                    key=lambda c: (len(c), c.lower()),
                )
                options["columns"]["default"] = image_cols[0] if image_cols else "body"
            else:
                options["columns"]["default"] = "body"

        return options

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Allow processor on top image rankings, collectors, but not specific collectors with their own image
        collection methods

        :param module: Dataset or processor to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        """
        return (
            (module.type == "top-images" or module.is_from_collector())
            and module.type
            not in [
                "tiktok-search",
                "tiktok-urls-search",
                "telegram-search",
                "fourchan-search",
            ]
            and module.get_extension() in ("csv", "ndjson")
        )

    def process(self):
        """
        This takes a 4CAT results file as input, and outputs a zip file with
        files along with a file, .metadata.json, that contains identifying
        information.
        """
        # don't care about certificates for this one
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        # Get the source file data path
        amount = self.parameters.get("amount", 100)
        split_comma = self.parameters.get("split-comma", False)

        if amount == 0:
            amount = self.config.get("image-downloader.max", 1000)

        columns = self.parameters.get("columns")
        if type(columns) is str:
            columns = [columns]

        # is there anything for us to download?
        if self.source_dataset.num_rows == 0:
            return self.dataset.finish_with_error("No files to download.")

        if not columns:
            return self.dataset.finish_with_error(
                "No columns selected; no URLs can be extracted from the dataset"
            )

        # prepare
        self.staging_area = self.dataset.get_staging_area()
        self.complete = False
        urls = list()

        # first, get URLs to download files from
        self.dataset.update_status("Reading source file")
        item_index = 0
        item_map = {}
        for item in self.source_dataset.iterate_items(self):
            if self.interrupted:
                raise ProcessorInterruptedException()

            # note that we do not check if the amount of URLs exceeds the max
            # `amount` of files; downloads may fail, so the limit is on the
            # amount of downloaded files, not the amount of potentially
            # downloadable file URLs
            item_index += 1
            if item_index % 50 == 0:
                self.dataset.update_status(
                    f"Extracting URLs from item {item_index:,} of {self.source_dataset.num_rows:,}"
                )

            # loop through all columns and process values for item
            item_urls = set()
            for column in columns:
                value = item.get(column)
                if not value:
                    continue

                # remove all whitespace from beginning and end (needed for single URL check)
                values = [str(value).strip()]
                if split_comma:
                    values = values[0].split(",")

                for value in values:
                    if re.match(r"https?://(\S+)$", value):
                        # single URL
                        item_urls.add(value)
                    else:
                        # search for URLs in string
                        for regex in self.get_link_regexes():
                            item_urls |= set(regex.findall(value))

            item_urls = self.preprocess_urls(item_urls)
            for item_url in item_urls:
                if item_url not in item_map:
                    item_map[item_url] = []

                item_map[item_url].extend(
                    item.get("ids").split(",") if "ids" in item else [item.get("id", "")]
                )
                urls.append(item_url)

        if not urls:
            return self.dataset.finish_with_error(
                "No download URLs could be extracted from the dataset within the given parameters."
            )
        else:
            # dedupe
            urls = set(urls)
            self.dataset.update_status(
                f"Extracted {len(urls):,} URLs to try to download."
            )

        # next, loop through files and download them - until we have as many files
        # as required. Note that files that cannot be downloaded or parsed do
        # not count towards that limit
        ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0"
        downloaded_files = set()
        failures = []
        metadata = {}

        self.dataset.log(f"Filename prep for {len(urls)} URLs")
        # prepare filenames for each url
        self.filenames = CaseInsensitiveDict()
        self.url_redirects = {}

        # Use a set for O(1) membership during filename uniqueness checks
        url_filenames_seen = set()
        for i, url in enumerate(urls):
            url_filename = url_to_filename(
                url,
                staging_area=None,  # we do not check on-disk here as we know we have a new empty staging area
                default_name="file",
                default_ext=".png",
                existing_filenames=url_filenames_seen,  # set instead of list
            )
            
            self.filenames[url] = url_filename
            url_filenames_seen.add(url_filename)  # record membership
            if i in (0, 9, 49) or ((i + 1) % 200 == 0):
                # Log progress every 10, 50, then every 200
                self.dataset.log(f"Filename progress {i+1}/{len(urls)} filenames done")

        max_images = min(len(urls), amount) if amount > 0 else len(urls)
        self.dataset.log(f"Starting download of up to {max_images:,} image(s).")
        for url, response in self.iterate_proxied_requests(
            urls,
            preserve_order=False,
            headers={"User-Agent": ua},
            hooks={
                # use hooks to download the content (stream=True) in parallel
                "response": self.stream_url
            },
            verify=False,
            timeout=20,
            stream=True,
        ):
            downloaded_file = self.staging_area.joinpath(self.filenames[url])
            failure = False

            if self.interrupted:
                self.completed = True
                self.flush_proxied_requests()
                shutil.rmtree(self.staging_area)
                raise ProcessorInterruptedException()

            if type(response) is FailedProxiedRequest:
                if type(response.context) is requests.exceptions.Timeout:
                    self.dataset.log(
                        f"Error: Timeout while trying to download from {url}: {response.context}"
                    )
                elif type(response.context) is requests.exceptions.SSLError:
                    self.dataset.log(
                        f"Error: SSL Error for URL {url}: {response.context}"
                    )
                elif type(response.context) is requests.exceptions.TooManyRedirects:
                    self.dataset.log(
                        f"Error: Too many redirects for URL {url}: {response.context}"
                    )
                elif type(response.context) is requests.exceptions.ConnectionError:
                    self.dataset.log(
                        f"Error: Connection Error for URL {url}: {response.context}"
                    )
                else:
                    self.dataset.log(f"Error: Error for URL {url}: {response.context}")

                failure = True

            elif response.status_code != 200:
                self.dataset.log(
                    f"Error: File not found (status {response.status_code}) at {url}"
                )
                failure = True

            if not failure:
                url_domain = url.split("/")[2].lower()
                url_trail = url.split("/")[-1]
                if url_domain in ("www.imgur.com", "imgur.com") and (
                    url.endswith(".json") or "." not in url_trail
                ):
                    # imgur galleries or previews - not actual images
                    # but they contain a reference to one...
                    with downloaded_file.open() as infile:
                        try:
                            if url.endswith(".json"):
                                # extract URL from gallery metadata and push it to the
                                # front of the queue so it gets downloaded next
                                gallery = json.load(infile)
                                imgur_ref = gallery["data"]["image"]["album_images"][
                                    "images"
                                ]
                                imgur_ref = imgur_ref[0]
                                image_url = f"https://i.imgur.com/{imgur_ref['hash']}{imgur_ref['ext']}"
                            else:
                                # get reference from HTML meta for preview pages
                                image_url = (
                                    infile.read()
                                    .split('<meta property="og:image"')[1]
                                    .split('content="')[1]
                                    .split('?fb">')[0]
                                )

                            image_url = self.clean_url(image_url)
                            self.url_redirects[url] = image_url
                            self.filenames[image_url] = url_to_filename(image_url, staging_area=self.staging_area, default_name="file", default_ext=".png")
                            self.push_proxied_request(image_url, 0)
                            item_map[image_url] = item_map[url]
                            del self.filenames[url], item_map[url]
                            downloaded_file.unlink(missing_ok=True)

                            # skip the metadata addition, we'll add one for
                            # the 'real' URL later
                            continue

                        except (json.JSONDecodeError, KeyError, IndexError):
                            self.dataset.log(
                                f"Error: Could not get image URL for Imgur album {url}"
                            )
                            failures.append(url)

                elif not response.headers.get("content-type", "").startswith("image"):
                    self.dataset.log(
                        f"Error: URL does not seem to be of the required type ({response.headers.get('content-type', '').split(';')[0]} found instead) at {url}"
                    )
                    failure = True

                else:
                    # file has been downloaded, but is it also a valid file?
                    # test by trying to read it with PIL
                    try:
                        extension = self.get_valid_file_extension(downloaded_file)
                        downloaded_file.rename(downloaded_file.with_suffix(extension))
                        # update filename mapping to reflect new extension
                        self.filenames[url] = self.filenames[url].rsplit(".", 1)[0] + extension

                    except InvalidDownloadedFileException as e:
                        self.dataset.log(
                            f"Error: File downloaded from {url}, but does not seem to be valid file ({e})"
                        )
                        failure = True

                if not failure:
                    if len(downloaded_files) < amount or amount == 0:
                        downloaded_files.add(url)
                        self.dataset.update_status(
                            f"Downloaded {len(downloaded_files):,} of {max_images:,} file(s)"
                        )
                        self.dataset.update_progress(len(downloaded_files) / max_images)

                    if len(downloaded_files) >= amount and amount != 0:
                        # parallel requests may still be running so halt these
                        # before ending the loop and wrapping up
                        self.complete = True

            if failure:
                failures.append(url)
                downloaded_file.unlink(missing_ok=True)

            metadata[url] = {
                "filename": self.filenames[url],
                "url": self.resolve_url(url),
                "success": not failure,
                "from_dataset": self.source_dataset.key,
                "post_ids": item_map[url],
            }

            if self.complete:
                break

        with self.staging_area.joinpath(".metadata.json").open(
            "w", encoding="utf-8"
        ) as outfile:
            json.dump(metadata, outfile)

        # delete supernumerary partially downloaded files
        self.flush_proxied_requests()  # get rid of remaining queue

        for url, filename in self.filenames.items():
            url_file = self.staging_area.joinpath(filename)
            if url_file.exists() and url not in downloaded_files:
                url_file.unlink()

        # finish up
        self.dataset.update_progress(1.0)
        self.write_archive_and_finish(
            self.staging_area, len([x for x in metadata.values() if x.get("success")])
        )

    def clean_url(self, url):
        # always lower case domain
        url = url.split("/")
        url[2] = url[2].lower()
        url = "/".join(url)

        if url.endswith("?"):
            url = url[:-1]

        if url.endswith("/"):
            url = url[:-1]

        return url.split("#")[0].replace(" ", "%20")

    def preprocess_urls(self, urls):
        """
        Clean up (potential) image URLs

        Most URLs can be requested as is, but some big image hosts require a
        little bit of extra treatment to make sure we get images or image
        metadata from the right place.

        Imgur in particular is annoying and sometimes necessitates an extra
        request to get the right URL for an album or gallery link. This is
        mostly handled in `process()`, but this method makes sure we start that
        request chain with the right URL.

        :param list urls:  Unprocessed URL list
        :return list:  Processed URL list
        """
        for url in urls:
            domain = url.split("/")[2].lower()
            url_ext = url.split(".")[-1].lower()
            image_exts = ["png", "jpg", "jpeg", "gif", "gifv"]

            url = self.clean_url(url)

            if domain in ("www.imgur.com", "imgur.com"):
                # gifv files on imgur are actually small mp4 files. Since
                # downloading videos complicates this and follow-up processors,
                # just save the first frame that imgur also hosts as a .gif file.
                if url_ext == "gifv":
                    yield url[:-1]

                # Check for image extensions and directly download
                # Some imgur.com links are directly to images (not just i.imgur.com)
                elif any([ext == url_ext for ext in image_exts]):
                    yield url

                # If there's no file extension at the end of the url, and the link
                # is a so-called "gallery", use the image's .json endpoint imgur so
                # graciously provides
                # this adds the json to the download queue: when it is downloaded,
                # the URL will be extrapolated and added to the queue
                elif "gallery" in url:
                    yield url + ".json"

                # image preview page
                # these will be parsed once they are downloaded to extract the
                # actual image URL
                else:
                    yield url

            else:
                yield url

    def stream_url(self, response, fourcat_original_url=None, *args, **kwargs):
        """
        Helper function for iterate_proxied_requests

        Simply streams data from a request; allows for stream=True with a
        request, meaning we do not need to buffer everything in memory.

        :param requests.Response response: requests response object
        """
        if fourcat_original_url is None:
            raise KeyError("Missing fourcat_original_url for response hook; proxied requests must pass it")

        # Final URL after requests has handled redirects
        response_url = self.clean_url(response.url)

        # Strict requirement: we must have a filename for the original URL
        original_url = fourcat_original_url
        if original_url not in self.filenames:
            raise KeyError(
                f"Missing filename for original request URL: {original_url}"
            )

        # Record redirect mapping from original -> final, if any
        final_url = response_url
        # If requests followed redirects, response.history contains prior responses
        if response.history:
            # Trust the current response URL as final; record mapping only if different
            final_url = response_url

        if final_url != original_url:
            self.url_redirects[original_url] = final_url

        destination = self.staging_area.joinpath(self.filenames[original_url])

        while chunk := response.raw.read(1024, decode_content=True):
            if not response.ok or self.interrupted or self.complete:
                # stop reading when request is bad, or we have enough already
                # try to make the request finish ASAP so it can be cleaned up
                response._content_consumed = True
                response._content = False
                response.raw.close()
                return

            with destination.open("ab") as outfile:
                try:
                    outfile.write(chunk)
                except FileNotFoundError:
                    # this can happen if processing finished *after* the while
                    # loop started (i.e. self.complete flipped); safe to ignore
                    # in that case
                    pass


    def resolve_url(self, url):
        """
        Find final redirect for URL

        While downloading files, we may encounter redirects, and the final file
        may be downloaded from a different URL than originally given. These are
        saved in `self.url_redirects` and this simple function maps the original
        to the redirected URL if one exists.

        :param str url:  URL to resolve
        :return str:  Final URL
        """
        while url in self.url_redirects:
            url = self.url_redirects[url]

        return url

    def get_link_regexes(self):
        """
        Get regexes to extract relevant links from text

        :return list:  List of compiled regular expressions
        """
        return [
            # for image URL extraction, we use the following heuristic:
            # Makes sure that it gets "http://site.com/img.jpg", but also
            # more complicated ones like
            # https://preview.redd.it/3thfhsrsykb61.gif?format=mp4&s=afc1e4568789d2a0095bd1c91c5010860ff76834
            re.compile(
                r"(?:www\.|https?:\/\/)[^\s\(\)\]\[,']*\.(?:png|jpg|jpeg|gif|gifv)[^\s\(\)\]\[,']*",
                re.IGNORECASE,
            ),
            # Imgur and gfycat links that do not end in an extension are also accepted.
            # These can later be downloaded by adding an extension.
            re.compile(
                r"(?:https:\/\/gfycat\.com\/|https:\/\/imgur\.com\/)[^\s\(\)\]\[,']*",
                re.IGNORECASE,
            ),
        ]

    def get_valid_file_extension(self, file):
        """
        Get file extension for file

        URLs don't necessarily come with a file extension included; determine
        it based on the file that was downloaded. If the file is not a valid
        file and should be discarded, raise an InvalidDownloadedFileException
        to mark the file as such.

        :param Path file:  Path to the file
        :return:  File extension including leading period
        """
        try:
            picture = Image.open(file)
            if not picture.format:
                raise TypeError("Image format could not be determined")

            return f".{picture.format.lower()}"

        except (UnidentifiedImageError, AttributeError, TypeError) as e:
            raise InvalidDownloadedFileException(getattr(e, "message", str(e))) from e

    @staticmethod
    def map_metadata(url, data):
        """
        Iterator to yield modified metadata for CSV

        :param str url:  string that may contain URLs
        :param dict data:  dictionary with metadata collected previously
        :yield dict:  	  iterator containing reformated metadata
        """
        row = {
            "url": url,
            "number_of_posts_with_url": len(data.get("post_ids", [])),
            "post_ids": ", ".join(data.get("post_ids", [])),
            "filename": data.get("filename"),
            "download_successful": data.get("success", ""),
        }

        yield row
