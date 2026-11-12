"""
Extract most-used images from corpus
"""
from collections import Counter, OrderedDict
from backend.lib.processor import BasicProcessor
from common.lib.helpers import UserInput, urls_in_text, looks_like_image_url
from common.lib.compatibility import Compatibility

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class TopImageCounter(BasicProcessor):
    """
    Top Image listing

    Collects all images used in a data set, and sorts by most-used.
    """
    type = "top-images"  # job type ID
    category = "Metrics"  # category
    title = "Rank image URLs"  # title displayed in UI
    description = "Collect all image URLs and sort by most-occurring."  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    # top-level csv/ndjson datasets, except Telegram (which has its own image logic)
    compatibility = Compatibility(top_dataset_only=True, excluded_types={"telegram-search"}, extensions={"csv", "ndjson"}, preferred_followups=["image-downloader"])

    @classmethod
    def get_options(cls, parent_dataset=None, config=None):
        """
        Get processor options

        The feature of this processor that overwrites the parent dataset can
        only work properly on csv datasets so check the extension before
        showing it.

        :param config:
        :param parent_dataset:  Dataset to get options for
        :return dict:
        """

        return {
            "save_annotations": {
                "type": UserInput.OPTION_ANNOTATION,
                "label": "image_urls",
                "default": False,
            }
        }

    def process(self):
        """
        This takes a 4CAT results file as input, and outputs a new CSV file
        with one column with image hashes, one with the first file name used
        for the image, and one with the amount of times the image was used
        """

        all_links = []  # Used for overwrite
        save_annotations = self.parameters.get("save_annotations", False)

        self.dataset.update_status("Extracting image links from source file")

        img_links = list()

        for post in self.source_dataset.iterate_items(self):
            post_img_links = set()  # set to only count images once per post
            for field, value in post.items():
                if value and (field == "body" or "url" in field.lower() or "image" in field.lower()):
                    # these fields also hold links that are not images, such as a link to the post itself, so only
                    # URLs that look like image links are counted
                    post_img_links |= {url for url in urls_in_text(value) if looks_like_image_url(url)}

            # Always add to all_links, so we can easily add to the source file if needed.
            all_links.append((post['id'], post_img_links))

            # Only add valid links to img_links.
            img_links += post_img_links

        # OrderedDict for Counter, since we need to URLs ordered from most- to to least-linked to.
        img_ranked = OrderedDict(Counter(img_links).most_common())

        results = [{
            "date": "all",
            "item": k,
            "value": v,
            "ids": ",".join([link[0] for link in all_links if k in link[1]]),
        } for k, v in img_ranked.items()]

        if not results:
            self.dataset.finish_as_empty("No image URLs detected.")
            return

        # Also add the data to the original file, if indicated.
        if save_annotations:
            annotations = []
            for link in all_links:
                annotation = {
                    "label": "image_urls",
                    "value": ",".join(link[1]),
                    "item_id": link[0]
                }
                annotations.append(annotation)
            self.save_annotations(annotations)

        self.write_csv_items_and_finish(results)
