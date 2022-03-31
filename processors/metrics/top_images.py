"""
Extract most-used images from corpus
"""
import hashlib
import base64
import re
import config
import csv
import shutil

from collections import Counter, OrderedDict
from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorException
from common.lib.helpers import UserInput

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
    category = "Post metrics"  # category
    title = "Rank image URLs"  # title displayed in UI
    description = "Collect all image URLs and sort by most-occurring."  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        All top-level datasets, excluding Telegram, which has a different image logic

        :param module: Dataset or processor to determine compatibility with
        """

        if module.is_dataset() and module.is_top_dataset() and module.type != "telegram-search":
            return True
        else:
            return False

    def process(self):
        """
        This takes a 4CAT results file as input, and outputs a new CSV file
        with one column with image hashes, one with the first file name used
        for the image, and one with the amount of times the image was used
        """
        images = {}

        all_links = []  # Used for overwrite

        # 4chan data has specific columns for image information, so treat this a bit differently.
        if self.source_dataset.parameters["datasource"] == "4chan":

            self.dataset.update_status("Extracting image links from source file")

            # Variables used for overwriting source file
            board = self.source_dataset.parameters["board"]
            boards_4plebs = ["pol", "lgbt", "adv", "f", "o", "sp", "tg", "trv", "tv", "x"]
            boards_fireden = ["cm", "co", "ic", "sci", "v", "vip", "y"]

            for post in self.source_dataset.iterate_items(self):

                post_img_links = []

                if not post["image_file"]:
                    all_links.append((post['id'], []))
                    continue

                if post["image_md5"] not in images:
                    # md5 is stored encoded; make it normal ascii
                    md5 = hashlib.md5()
                    md5.update(base64.b64decode(post["image_md5"]))

                    images[post["image_md5"]] = {
                        "filename": post["image_file"],
                        "md5": md5.hexdigest(),
                        "hash": post["image_md5"],
                        "count": 0
                    }

                # If we need to add image links to the source csv,
                # link to archives - we can't assume 4CAT has it saved.
                if self.parameters.get("overwrite"):

                    # 4plebs boards
                    if board in boards_4plebs:
                        post_img_links.append(
                            "https://archive.4plebs.org/_/search/image/" + post["image_md5"].replace("/", "_"))

                    # Fireden boards
                    elif board in boards_fireden:
                        post_img_links.append(
                            "https://boards.fireden.net/_/search/image/" + post["image_md5"].replace("/", "_"))

                    # Else, assume archived.moe has it
                    else:
                        post_img_links.append(
                            "https://archived.moe/_/search/image/" + post["image_md5"].replace("/", "_"))

                all_links.append((post['id'], post_img_links))
                images[post["image_md5"]]["count"] += 1

            top_images = {id: images[id] for id in sorted(images, key=lambda id: images[id]["count"], reverse=True)}

            results = [{
                "md5_hash": images[id]["md5"],
                "filename": images[id]["filename"],
                "num_posts": images[id]["count"],
                "url_4cat": (
                                "https" if config.FlaskConfig.SERVER_HTTPS else "http") + "://" + config.FlaskConfig.SERVER_NAME + "/api/image/" +
                            images[id]["md5"] + "." + images[id]["filename"].split(".")[
                                -1],
                "url_4plebs": "https://archive.4plebs.org/_/search/image/" + images[id]["hash"].replace("/", "_"),
                "url_fireden": "https://boards.fireden.net/_/search/image/" + images[id]["hash"].replace("/", "_"),
                "url_archivedmoe": "https://archived.moe/_/search/image/" + images[id]["hash"].replace("/", "_")
            } for id in top_images]

        else:

            # Important: image link regex.
            # Makes sure that it gets "http://site.com/img.jpg", but also
            # more complicated ones like
            # https://preview.redd.it/3thfhsrsykb61.gif?format=mp4&s=afc1e4568789d2a0095bd1c91c5010860ff76834
            img_link_regex = re.compile(
                r"(?:www\.|https?:\/\/)[^\s\(\)\]\[,']*\.(?:png|jpg|jpeg|gif|gifv)[^\s\(\)\]\[,']*", re.IGNORECASE)

            # Imgur and gfycat links that do not end in an extension are also accepted.
            # These can later be downloaded by adding an extension.
            img_domain_regex = re.compile(r"(?:https:\/\/gfycat\.com\/|https:\/\/imgur\.com\/)[^\s\(\)\]\[,']*",
                                          re.IGNORECASE)

            self.dataset.update_status("Extracting image links from source file")

            img_links = list()

            for post in self.source_dataset.iterate_items(self):
                post_img_links = set()  # set to only count images once per post
                for field, value in post.items():
                    if value and (field == "body" or "url" in field.lower() or "image" in field.lower()):
                        post_img_links |= set(img_link_regex.findall(value))
                        post_img_links |= set(img_domain_regex.findall(value))

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
            self.dataset.update_status("Zero image URLs detected.")
            return

        # Also add the data to the original file, if indicated.
        if self.parameters.get("overwrite"):
            try:
                self.add_field_to_parent(field_name='img_url',
                                         new_data=[", ".join(link[1]) for link in all_links],
                                         which_parent=self.source_dataset)
            except ProcessorException as e:
                self.dataset.update_status("Error updating parent dataset: %s" % e)

        self.write_csv_items_and_finish(results)

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        """
        Get processor options

        The feature of this processor that overwrites the parent dataset can
        only work properly on csv datasets so check the extension before
        showing it.

        :param user:
        :param parent_dataset:  Dataset to get options for
        :return dict:
        """

        return {
            "overwrite": {
                "type": UserInput.OPTION_TOGGLE,
                "default": False,
                "help": "Add extracted image URLs to dataset file",
                "tooltip": "This will add a new column, \"img_url\", to the dataset's csv file."
            }
        }
