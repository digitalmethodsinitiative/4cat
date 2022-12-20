"""
Create stripes from collections of video frames
"""
import base64
import json
import io

from PIL import Image
from svgwrite.container import SVG
from svgwrite.shapes import Rect
from svgwrite.text import Text
from svgwrite.image import Image as ImageElement

from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.user_input import UserInput
from common.lib.helpers import get_4cat_canvas

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class VideoStripes(BasicProcessor):
    """
    Video Frame Stripe renderer

    Takes a set of folders containing video frames and renders them as a horizontal collage per video
    """
    type = "video-stripes"  # job type ID
    category = "Visual"  # category
    title = "Create video stripes"  # title displayed in UI
    description = "For each video for which frames were extracted, create a video stripe (i.e. a horizontal collage " \
                  "of sequential frames). Stripes are then vertically stacked."  # description displayed in UI
    extension = "svg"  # extension of result file, used internally and in UI

    options = {
        "height": {
            "type": UserInput.OPTION_TEXT,
            "help": "Stripe height",
            "tooltip": "In pixels. Each stripe will be this height; frames are resized proportionally to fit it. Must "
                       "be between 25 and 200.",
            "coerce_type": int,
            "default": 100,
            "min": 25,
            "max": 200
        }
    }

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Determine compatibility

        Compatible with 'Extract video frames'. Can in principle run on
        anything that stores related images in separate folders in a zip
        archive. Each folder will be rendered as a separate stripe.

        :param str module:  Module ID to determine compatibility with
        :return bool:
        """
        return module.type in ["video-frames"]

    def process(self):
        metadata = {}
        base_height = self.parameters.get("height", 100)
        fontsize = 12

        # initialise stripe loop
        previous_video = None
        offset_y = -base_height
        stripe = None
        iterator = self.iterate_archive_contents(self.source_file)
        looping = True
        stripes = []
        stripe_widths = {}

        # why not just loop through iterate_archive_contents?
        # in SVG the order of elements matters, so we want to do some things
        # _after_ adding the last frame of a stripe. If we do this within the
        # loop we need to do the same outside of the loop after it finishes the
        # last frame. But by looping in this way we can control when the loop
        # ends and can finish up within it for all stripes including the last
        while looping:
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while looping through video frames")

            # get next file in archive from iterator
            try:
                file = next(iterator)
            except StopIteration:
                # this means that at the end of the iterator we complete one
                # final iteration in which we finish things up (see below)
                looping = False

            # there is a metadata file, always read first, which we can use
            if file.name == ".metadata.json":
                with file.open() as infile:
                    metadata = json.load(infile)
                    continue

            # skip if file is a real file but not an image
            if looping and file.suffix not in (".jpeg", ".jpg", ".png", ".gif"):
                continue
            else:
                video = str(file.parent.name)

            # at the end of each stripe (or at the end of the archive) add a
            # footer to it and paint to the canvas
            if video != previous_video or not looping:
                self.dataset.update_status(f"Rendering video stripe for collection {video}")
                self.dataset.update_progress(len(stripe_widths) / self.source_dataset.num_rows)
                if previous_video is not None or not looping:
                    # draw the video filename/label on top of the rendered
                    # frame thumbnails
                    video_label = previous_video
                    footersize = (fontsize * (len(video_label) + 2) * 0.5925, fontsize * 2)
                    footer_shape = SVG(insert=(0, base_height - footersize[1]), size=footersize)
                    footer_shape.add(Rect(insert=(0, 0), size=("100%", "100%"), fill="#000"))
                    footer_shape.add(
                        Text(insert=("50%", "50%"), text=video_label, dominant_baseline="middle",
                             text_anchor="middle", fill="#FFF", style="font-size:%ipx" % fontsize))

                    # sometimes the label is larger than the rendered frames!
                    stripe["width"] = max(stripe_widths[previous_video], footersize[0])

                    # add to canvas
                    stripe.add(footer_shape)
                    stripes.append(stripe)

                # reset and ready for the next stripe
                offset_y += base_height
                previous_video = video
                stripe_widths[video] = 0
                stripe = SVG(insert=(0, offset_y), size=(0, base_height))

            # if we have a new frame, add it to the currently active stripe
            if looping:
                frame = Image.open(file)
                frame_width = int(base_height * frame.width / frame.height)
                frame.thumbnail((frame_width, base_height))

                # add to SVG as data URI (so it is a self-contained file)
                frame_data = io.BytesIO()
                frame.save(frame_data, format="JPEG")  # JPEG probably optimal for video frames
                frame_data = "data:image/jpeg;base64," + base64.b64encode(frame_data.getvalue()).decode("utf-8")

                # add to stripe element
                frame_element = ImageElement(href=frame_data, insert=(stripe_widths[video], 0), size=(frame_width, base_height))
                stripe.add(frame_element)
                stripe_widths[video] += frame_width

        # now we know all dimensions we can instantiate the canvas too
        canvas_width = max(stripe_widths.values())
        fontsize = 12
        canvas = get_4cat_canvas(self.dataset.get_results_path(), canvas_width, base_height * len(stripe_widths),
                                 fontsize_small=fontsize)
        for stripe in stripes:
            canvas.add(stripe)

        # save as svg and finish up
        canvas.save(pretty=True)
        self.dataset.log("Saved to " + str(self.dataset.get_results_path()))
        return self.dataset.finish(len(stripe_widths))
