"""
Create timelines from collections of video frames
"""
import base64
import json
import io

from PIL import Image
from svgwrite.container import SVG, Hyperlink
from svgwrite.shapes import Rect
from svgwrite.text import Text
from svgwrite.image import Image as ImageElement

from ural import is_url

from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.user_input import UserInput
from common.lib.helpers import get_4cat_canvas
from common.lib.dataset import DataSet

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class VideoTimelines(BasicProcessor):
    """
    Video Frame Timeline renderer

    Takes a set of folders containing video frames and renders them as a horizontal collage per video
    """
    type = "video-timelines"  # job type ID
    category = "Visual"  # category
    title = "Create video timelines"  # title displayed in UI
    description = "For each video for which frames were extracted, create a video timeline (i.e. a horizontal " \
                  "collage of sequential frames). Timelines are then vertically stacked."  # description displayed in UI
    extension = "svg"  # extension of result file, used internally and in UI

    options = {
        "height": {
            "type": UserInput.OPTION_TEXT,
            "help": "Timeline height",
            "tooltip": "In pixels. Each timeline will be this height; frames are resized proportionally to fit it. "
                       "Must be between 25 and 200.",
            "coerce_type": int,
            "default": 100,
            "min": 25,
            "max": 200
        }
    }

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Determine compatibility

        Compatible with 'Extract video frames'. Can in principle run on
        anything that stores related images in separate folders in a zip
        archive. Each folder will be rendered as a separate timeline.

        :param str module:  Module ID to determine compatibility with
        :return bool:
        """
        return module.type in ["video-frames", "video-scene-frames"]

    def process(self):
        metadata = {}
        base_height = self.parameters.get("height", 100)
        fontsize = 12

        # initialise timeline loop
        previous_video = None
        offset_y = -base_height
        timeline = None
        iterator = self.iterate_archive_contents(self.source_file)
        looping = True
        timelines = []
        timeline_widths = {}

        # why not just loop through iterate_archive_contents?
        # in SVG the order of elements matters, so we want to do some things
        # _after_ adding the last frame of a timeline. If we do this within the
        # loop we need to do the same outside of the loop after it finishes the
        # last frame. But by looping in this way we can control when the loop
        # ends and can finish up within it for all timelines including the last
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

            labels = self.get_video_labels(metadata)

            # at the end of each timeline (or at the end of the archive) add a
            # footer to it and paint to the canvas
            if video != previous_video or not looping:
                if previous_video is not None or not looping:
                    # draw the video filename/label on top of the rendered
                    # frame thumbnails
                    video_label = labels.get(previous_video, previous_video)
                    footersize = (fontsize * (len(video_label) + 2) * 0.5925, fontsize * 2)
                    footer_shape = SVG(insert=(0, base_height - footersize[1]), size=footersize)
                    footer_shape.add(Rect(insert=(0, 0), size=("100%", "100%"), fill="#000"))
                    label_element = Text(insert=("50%", "50%"), text=video_label, dominant_baseline="middle",
                             text_anchor="middle", fill="#FFF", style="font-size:%ipx" % fontsize)

                    # if the label is a URL, make it clickable
                    if is_url(video_label):
                        link = Hyperlink(href=video_label, style="cursor:pointer;")
                        link.add(label_element)
                        footer_shape.add(link)
                    else:
                        footer_shape.add(label_element)

                    # sometimes the label is larger than the rendered frames!
                    timeline["width"] = max(timeline_widths[previous_video], footersize[0])

                    # add to canvas
                    timeline.add(footer_shape)
                    timelines.append(timeline)

                if looping:
                    # Only prep for new timeline if still looping
                    self.dataset.update_status(f"Rendering video timeline for collection {video} ({len(timeline_widths)}/{self.source_dataset.num_rows})")
                    self.dataset.update_progress(len(timeline_widths) / self.source_dataset.num_rows)
                    # reset and ready for the next timeline
                    offset_y += base_height
                    previous_video = video
                    timeline_widths[video] = 0
                    timeline = SVG(insert=(0, offset_y), size=(0, base_height))

            # if we have a new frame, add it to the currently active timeline
            if looping:
                frame = Image.open(file)
                frame_width = int(base_height * frame.width / frame.height)
                frame.thumbnail((frame_width, base_height))

                # add to SVG as data URI (so it is a self-contained file)
                frame_data = io.BytesIO()
                frame.save(frame_data, format="JPEG")  # JPEG probably optimal for video frames
                frame_data = "data:image/jpeg;base64," + base64.b64encode(frame_data.getvalue()).decode("utf-8")

                # add to timeline element
                frame_element = ImageElement(href=frame_data, insert=(timeline_widths[video], 0), size=(frame_width, base_height))
                timeline.add(frame_element)
                timeline_widths[video] += frame_width

        # now we know all dimensions we can instantiate the canvas too
        canvas_width = max(timeline_widths.values())
        fontsize = 12
        canvas = get_4cat_canvas(self.dataset.get_results_path(), canvas_width, base_height * len(timeline_widths),
                                 fontsize_small=fontsize)
        for timeline in timelines:
            canvas.add(timeline)

        # save as svg and finish up
        canvas.save(pretty=True)
        self.dataset.log("Saved to " + str(self.dataset.get_results_path()))
        return self.dataset.finish(len(timeline_widths))

    def get_video_labels(self, metadata):
        """
        Determine appropriate labels for each video

        Iterates through the parent dataset (from which the video came) to
        determine an appropriate label. There is a generalised heuristic and
        some data source-specific pathways.

        :param metadata:  Metadata as parsed from the 'Extract Frames' JSON
        :return dict:  Filename -> label mapping
        """
        mapping_dataset = {}
        mapping_ids = {}
        labels = {}

        if not metadata:
            return {}

        for url, data in metadata.items():
            if data.get('success'):
                for filename in [f["filename"] for f in data.get("files", [])]:
                    filename = ".".join(filename.split(".")[:-1])
                    mapping_ids[filename] = data["post_ids"]
                    if data.get("from_dataset", data.get("source_dataset")) not in mapping_dataset:
                        mapping_dataset[data.get("from_dataset", data.get("source_dataset"))] = []
                    mapping_dataset[data.get("from_dataset", data.get("source_dataset"))].append(filename)
                    labels[filename] = filename

        for dataset, urls in mapping_dataset.items():
            dataset = DataSet(key=dataset, db=self.db).nearest("*-search")

            # determine appropriate label
            # is this the right place? should it be in the datasource?
            if dataset.type == "tiktok-search":
                mapper = lambda item: item.get("tiktok_url")
            elif dataset.type == "upload-search" and dataset.parameters.get("board") == "youtube-video-list":
                mapper = lambda item: item.get("youtube_url")
            else:
                mapper = lambda item: item.get("id")

            for item in dataset.iterate_items(self):
                for filename in urls:
                    if item["id"] in mapping_ids[filename]:
                        labels[filename] = mapper(item)

        return labels
