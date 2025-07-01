"""
Create an image wall of the most-used images
"""
from PIL import Image, ImageOps, UnidentifiedImageError
from sklearn.cluster import KMeans
from common.lib.helpers import UserInput
import colorsys
import copy

from processors.visualisation.video_wall import VideoWallGenerator
from common.lib.exceptions import MediaSignatureException

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class ImageWallGenerator(VideoWallGenerator):
    """
    Image wall generator

    We borrow code from the video wall generator because ffmpeg can handle
    images just as well as videos!
    """
    type = "image-wall"
    category = "Visual"
    title = "Image wall"
    description = "Put all images in a single combined image, side by side. Images can be sorted and resized."
    extension = "png"

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Allow processor on token sets

        :param module: Dataset or processor to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        """
        return module.get_media_type() in ("video", "image") \
               or module.type.startswith("image-downloader") \
               or module.type == "video-frames"

    @classmethod
    def get_options(cls, parent_dataset=None, config=None):
        options = copy.deepcopy(cls.options)
        max_number_images = int(config.get("image-visuals.max_images", 1000))
        options["amount"] = {
            "type": UserInput.OPTION_TEXT,
            "help": "No. of images" + (f" (max {max_number_images})" if max_number_images != 0 else ""),
            "default": 100 if max_number_images == 0 else min(max_number_images, 100),
            "min": 0 if max_number_images == 0 else 1,
            "max": max_number_images,
            "tooltip": "'0' uses as many images as available in the archive" + (
                f" (up to {max_number_images})" if max_number_images != 0 else "")
        }

        options["sort-mode"]["options"] = {
            "": "Do not sort",
            "random": "Random",
            "dominant": "Dominant colour (decent, faster)",
            "kmeans-dominant": "Dominant K-means (precise, slow)",
            "average-hsv": "Average colour (HSV; imprecise, fastest)",
        }

        del options["max-length"]
        del options["audio"]
        return options

    def sort_file(self, file_path, sort_mode, ffprobe_path):
        """
        Get file signature for sorting


        :param Path file_path:  Path to file to get signature of
        :param str sort_mode:  Sorting mode, defaults to (video) length
        :param str ffprobe_path:  Path to the ffprobe executable
        :return:  A value to sort the file by
        """
        sample_max = 75  # image size for colour sampling

        try:
            picture = Image.open(str(file_path))
        except UnidentifiedImageError as e:
            raise MediaSignatureException() from e

        if picture.height > sample_max or picture.width > sample_max:
            # if the image is large, get the dominant colour from a resized
            # version
            sample_width = int(sample_max * picture.width / max(picture.width, picture.height))
            sample_height = int(sample_max * picture.height / max(picture.width, picture.height))
            try:
                picture = ImageOps.fit(picture, (sample_width, sample_height))
            except ValueError:
                # Default of BICUBIC may fail
                picture = ImageOps.fit(picture, (sample_width, sample_height), method=Image.NEAREST)

        if sort_mode not in ("", "random"):
            # ensure we get RGB values for pixels
            picture = picture.convert("RGB")

        # determine a 'representative colour'
        if sort_mode in ("average-rgb", "average-hsv"):
            # average colour, as RGB or HSV
            pixels = picture.getdata()
            pixels = [colorsys.rgb_to_hsv(*pixel) for pixel in pixels]

            sum_colour = (sum([p[0] for p in pixels]), sum([p[1] for p in pixels]), sum([p[2] for p in pixels]))
            avg_colour = (sum_colour[0] / len(pixels), sum_colour[1] / len(pixels), sum_colour[2] / len(pixels))

            # this is a bit dumb since we convert back later, but since all the
            # other modes return rgb...
            value = colorsys.hsv_to_rgb(*avg_colour)

        elif sort_mode == "dominant":
            # most-occurring colour
            colours = picture.getcolors(picture.width * picture.height)
            colours = sorted(colours, key=lambda x: x[0], reverse=True)
            value = colours[0][1]

        elif sort_mode in ("kmeans-dominant"):
            # use k-means clusters to determine the representative colour
            # this is more computationally expensive but gives far better
            # results.

            # determine k-means clusters for this image, i.e. the n most
            # dominant "average" colours, in this case n=3 (make parameter?)
            pixels = picture.getdata()
            clusters = KMeans(n_clusters=3, random_state=0)  # 0 so it is deterministic
            predicted_centroids = clusters.fit_predict(pixels).tolist()

            # now we have two options - the colour of the single most dominant k-means centroid
            ranked_centroids = {}
            for index in range(0, len(clusters.cluster_centers_)):
                ranked_centroids[self.numpy_to_rgb(clusters.cluster_centers_[index])] = predicted_centroids.count(index)

            value = [int(v) for v in
                     sorted(ranked_centroids, key=lambda k: ranked_centroids[k], reverse=True)[0].split(",")]

        else:
            value = (0, 0, 0)

        # converted to HSV, because RGB does not sort nicely
        return colorsys.rgb_to_hsv(*value)

    @staticmethod
    def numpy_to_rgb(numpy_array):
        """
        Helper function to go from numpy array to list of RGB strings

        Used in the K-Means clustering part
        """
        return ",".join([str(int(value)) for value in numpy_array])