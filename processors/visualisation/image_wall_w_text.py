"""
Create an image wall with text captions
"""
import io
import base64
import json
import math
import textwrap

from svgwrite.image import Image as ImageElement

from svgwrite.container import SVG
from svgwrite.shapes import Rect
from svgwrite.text import Text, TextArea

from PIL import Image, ImageOps

from common.lib.helpers import UserInput, convert_to_int, get_4cat_canvas
from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException, ProcessorException
from common.config_manager import config

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl", "Stijn Peeters"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class ImageTextWallGenerator(BasicProcessor):
    """
    Image wall with text generator
    """
    type = "image-text-wall"  # job type ID
    category = "Visual"  # category
    title = "Visualise images with captions"  # title displayed in UI
    description = "Combine images into a single image including text"  # description displayed in UI
    extension = "svg"  # extension of result file, used internally and in UI

    image_datasets = ["image-downloader", "video-hasher-1"]
    caption_datasets = ["image-captions", "text-from-images"]
    combined_dataset = ["image-downloader-stable-diffusion"]

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Allow processor on CLIP dataset only

        :param module: Dataset or processor to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        """
        image_dataset, text_dataset = cls.identity_dataset_types(module)
        return image_dataset is not None and text_dataset is not None

    @classmethod
    def get_options(cls, parent_dataset=None, config=None):

        """
        Collect maximum number of audio files from configuration and update options accordingly
        :param config:
        """
        max_number_images = int(config.get("image-visuals.max_per_cat", 1000))
        max_pixels = int(config.get("image-visuals.max_pixels_per_image", 500))
        options = {
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "help": "Max images" + (f" (max {max_number_images:,})" if max_number_images != 0 else ""),
                "default": 10 if max_number_images == 0 else min(max_number_images, 100),
                "min": 0 if max_number_images == 0 else 1,
                "max": max_number_images,
            },
            "size": {
                "type": UserInput.OPTION_TEXT,
                "help": "Image size",
                "tooltip": f"In pixels. Each image will be this max width and are resized proportionally to fit it. Must be between 100 and {max_pixels}.",
                "coerce_type": int,
                "default": min(max_pixels, 100),
                "min": 100,
                "max": max_pixels
            },
            "tile-size": {
                "type": UserInput.OPTION_CHOICE,
                "options": {
                    "square": "Square",
                    "fill-square": "Fill square",
                    "fit-height": "Fit height"
                },
                "default": "fill-square",
                "help": "Image tile size",
                "tooltip": "'Fit height' retains image ratios but makes them have the same height"
            },
        }
        if max_number_images == 0:
            options['amount']['tooltip'] = "'0' will use all available images"
            options['amount'].pop('max')

        return options

    @staticmethod
    def identity_dataset_types(source_dataset):
        """
        Identify dataset types that are compatible with this processor
        """
        # TODO: use `media_type` method to identify image datasets after merge
        # TODO: do we have additional text datasets we would like to support?
        if source_dataset.type in ImageTextWallGenerator.combined_dataset:
            # This dataset has both images and captions
            return source_dataset, source_dataset
        elif any([source_dataset.type.startswith(dataset_prefix) for dataset_prefix in
                  ImageTextWallGenerator.caption_datasets]):
            text_dataset = source_dataset
            image_dataset = source_dataset.get_parent()
            if not any([image_dataset.type.startswith(dataset_prefix) for dataset_prefix in
                        ImageTextWallGenerator.image_datasets] + [image_dataset.get_media_type() == "image"]):
                # Not a compatible dataset
                return None, None
        else:
            return None, None

        return image_dataset, text_dataset

    def process(self):
        """
        Process the job
        """
        # Check for compatibility
        image_dataset, text_dataset = self.identity_dataset_types(self.source_dataset)
        if image_dataset is None or text_dataset is None:
            self.dataset.finish_with_error("Unable to indentify image and category datasets")
            return
        # is there anything to put on a wall?
        if image_dataset.num_rows == 0 or text_dataset.num_rows == 0:
            self.dataset.finish_with_error("No images/captions available to render to image wall.")
            return
        self.dataset.log(
            f"Found {image_dataset.type} w/ {image_dataset.num_rows} images and {text_dataset.type} w/ {text_dataset.num_rows} items")

        # 0 = use as many images as in the archive, up to the max
        max_images = convert_to_int(self.parameters.get("amount"), 100)
        if max_images == 0:
            max_images = image_dataset.num_rows
        # Calculate sides of the square
        side_length = math.ceil(math.sqrt(max_images))
        tile_type = self.parameters.get("tile-size", "square")

        # Create text mapping
        max_text_len = 0
        filename_to_text_mapping = {}
        if text_dataset.type in ImageTextWallGenerator.combined_dataset:
            # For datasets with both images and text, use .metadata.json
            metadata_file = self.extract_archived_file_by_name(".metadata.json", self.source_file)
            if metadata_file is None:
                self.dataset.finish_with_error("No metadata file found")
                return
            with metadata_file.open() as f:
                metadata = json.load(f)
            for item in metadata.values():
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while collecting text")
                if "filename" in item:
                    # "image-downloader-stable-diffusion" datasets
                    image_text = item.get("prompt", "")
                    max_text_len = max(max_text_len, len(image_text))
                    filename_to_text_mapping[item["filename"]] = image_text
        else:
            # For datasets with separate images and text
            for item in text_dataset.iterate_items(self):
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while collecting text")

                if item.get("image_filename", item.get("filename")) is not None:
                    # For image-caption datasets
                    image_text = item.get("text") if item.get("text") is not None else ""
                    max_text_len = max(max_text_len, len(image_text))
                    filename_to_text_mapping[item.get("image_filename", item.get("filename"))] = image_text

        # Create SVG with categories and images
        # Base sizes for each image
        base_height = self.parameters.get("size", 100)
        fontsize = 12
        # Note: SVG files are "documents" and so this is actually not direct to pixels but instead the fontsize is HTML/CSS style dependent
        fontsize_to_pixels_multiplier = 0.56  # this is a rough multiplier and somehow ought to be variable based on width
        characters_per_line = math.ceil(base_height / (
                fontsize * fontsize_to_pixels_multiplier))  # this is a rough estimate as width can be longer than height (works for square formats)
        rows_of_text = min(math.ceil(max_text_len / characters_per_line), 6)  # max of 6 rows of text
        row_height = base_height + (rows_of_text * fontsize + 4)  # 4 is for padding
        offset_y = - row_height
        # Object collectors and tracking
        total_images_collected = 0
        current_row = 0
        images_in_row = 0
        row_widths = {}
        complete_categories = []
        self.dataset.update_status("Creating Image wall")
        self.dataset.log(f"Creating image wall with {max_images} images, size {base_height} and tile type {tile_type}")
        for image_path in self.iterate_archive_contents(image_dataset.get_results_path()):
            if image_path.name in [".metadata.json"]:
                if convert_to_int(self.parameters.get("amount"), 100) == 0:
                    max_images = max_images - 1
                continue

            if total_images_collected == 0:
                offset_y += fontsize * 2  # add some space at the top for header

            if images_in_row % side_length == 0:
                # reset and ready for the next row
                offset_y += row_height
                current_row += 1
                images_in_row = 0
                row_widths[current_row] = 0
                category_image = SVG(insert=(0, offset_y), size=(0, row_height))
                offset_w = 0

            frame = Image.open(str(image_path))
            if tile_type == "square":
                # resize to square
                frame_width = base_height
                frame.thumbnail((frame_width, base_height))
            elif tile_type == "fill-square":
                # fill square
                frame_width = base_height
                frame = ImageOps.fit(frame, (frame_width, base_height), method=Image.BILINEAR)
            else:
                # resize to height
                frame_width = int(base_height * frame.width / frame.height)
                frame.thumbnail((frame_width, base_height))

            # add to SVG as data URI (so it is a self-contained file)
            frame_data = io.BytesIO()
            try:
                frame.save(frame_data, format="JPEG")  # JPEG probably optimal for video frames
            except OSError:
                # Try removing alpha channel
                frame = frame.convert('RGB')
                frame.save(frame_data, format="JPEG")
            frame_data = "data:image/jpeg;base64," + base64.b64encode(frame_data.getvalue()).decode("utf-8")
            # add to category element
            frame_element = ImageElement(href=frame_data, insert=(row_widths[current_row], 0),
                                         size=(frame_width, base_height))
            category_image.add(frame_element)

            # Add text label
            filename = image_path.name
            if filename in filename_to_text_mapping:
                image_text = textwrap.wrap(filename_to_text_mapping[filename],
                                           int(frame_width / (fontsize * fontsize_to_pixels_multiplier)))
                footersize = (frame_width, rows_of_text * fontsize * 2)
                footer_shape = SVG(insert=(offset_w, base_height), size=footersize)
                footer_shape.add(
                    Rect(insert=(0, 0), size=("100%", "100%"), fill="#000", style="stroke-width:1;stroke:white"))
                for i, line in enumerate(image_text, start=1):
                    label_element = Text(insert=(0, fontsize * i), text=line, fill="#FFF",
                                         style="font-size:%ipx" % fontsize)
                    footer_shape.add(label_element)
                category_image.add(footer_shape)
            offset_w += frame_width
            images_in_row += 1
            row_widths[current_row] += frame_width

            self.dataset.log(f"Added image {filename}")
            total_images_collected += 1

            if images_in_row % side_length == 0:
                # Add completed row
                category_image["width"] = row_widths[current_row]
                complete_categories.append(category_image)

            if total_images_collected == max_images:
                break

        # Check if last row was added
        if len(complete_categories) < len(row_widths):
            # Add last row
            category_image["width"] = row_widths[current_row]
            complete_categories.append(category_image)

        # now we know all dimensions we can instantiate the canvas too
        canvas = get_4cat_canvas(self.dataset.get_results_path(), max(row_widths.values()),
                                 row_height * len(row_widths) + fontsize * 4, header=f"Images with captions",
                                 fontsize_small=fontsize, fontsize_large=fontsize)

        for category_image in complete_categories:
            self.dataset.log(f"Adding {category_image}")
            canvas.add(category_image)

        # save as svg and finish up
        canvas.save(pretty=True)
        self.dataset.log("Saved to " + str(self.dataset.get_results_path()))
        return self.dataset.finish(total_images_collected)
