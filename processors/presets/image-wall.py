"""
Make image wall
"""
from backend.abstract.preset import ProcessorPreset

from common.lib.helpers import UserInput


class DownloadImagesAndMakeImageWall(ProcessorPreset):
    """
    Run processor pipeline to make an image wall
    """
    type = "preset-image-wall"  # job type ID
    category = "Presets"  # category. 'Presets' are always listed first in the UI.
    title = "Create image wall"  # title displayed in UI
    description = "Use a sample of the images (up to 125) linked to the most in the dataset and put them in a single " \
                  "image, side-by-side."
    extension = "png"

    options = {
        "sort-mode": {
            "type": UserInput.OPTION_CHOICE,
            "help": "Sort images by",
            "options": {
                "": "Do not sort",
                "dominant": "Dominant colour (decent, fast)",
                "kmeans-average": "Weighted K-means average (precise, slow)"
            },
            "default": "dominant"
        }
    }

    def get_processor_pipeline(self):
        """
        This queues a series of post-processors to make an image wall

        First, the required amount of images (125) referenced in the dataset is
        downloaded, in order of most-referenced; then, they are rendered into
        a single image, all cropped to the dimensions of the average image in
        the archive, and finally they are put into the image wall sorted by
        their representative colour.
        """
        sort_mode = self.parameters.get("sort-mode")

        pipeline = [
            # first, extract top images
            {
                "type": "top-images",
                "parameters": {
                    "overwrite": False
                }
            },
            # then, download the images we want to annotate
            {
                "type": "image-downloader",
                "parameters": {
                    "amount": 125,
                    "overwrite": False
                }
            },
            # then, create an image wall
            {
                "type": "image-wall",
                "parameters": {
                    "amount": 0,
                    "tile-size": "average",
                    "sort-mode": sort_mode
                }
            }
        ]

        return pipeline
