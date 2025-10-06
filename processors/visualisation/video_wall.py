"""
Create a collage of items in a grid
"""
import statistics
import subprocess
import random
import shutil
import oslex
import math
import re

from packaging import version

from common.lib.helpers import UserInput, get_ffmpeg_version, convert_to_int
from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException, MediaSignatureException

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class VideoWallGenerator(BasicProcessor):
    """
    Video wall generator

    Make a collage of videos or images. This class is set up for videos, but
    can easily be subclassed to make a processor that makes an image collage
    or a collage of images and videos combined.
    """
    type = "video-wall"  # job type ID
    category = "Visual"  # category
    title = "Video wall"  # title displayed in UI
    description = "Put all videos in a single combined video, side by side. Videos can be sorted and resized."
    extension = "mp4"  # extension of result file, used internally and in UI

    options = {
        "amount": {
            "type": UserInput.OPTION_TEXT,
            "help": "No. of items (max 500)",
            "default": 25,
            "min": 0,
            "max": 500,
            "tooltip": "'0' uses as many files as available in the archive (up to 500)"
        },
        "backfill": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Add more items if there is room",
            "default": True,
            "tooltip": "If there are more items than the given number and "
                       "there is space left to add them to the wall, do so"
        },
        "tile-size": {
            "type": UserInput.OPTION_CHOICE,
            "options": {
                "square": "Square",
                "average": "Average item in set",
                "median": "Median item in set",
                "fit-height": "Fit height"
            },
            "default": "median",
            "help": "Tile size",
            "tooltip": "'Fit height' retains width/height ratios but makes all tiles have the same height"
        },
        "sort-mode": {
            "type": UserInput.OPTION_CHOICE,
            "help": "Sort by",
            "options": {
                "": "Do not sort",
                "random": "Random",
                "shortest": "Length (shortest first)",
                "longest": "Length (longest first)"
            },
            "default": "shortest"
        },
        "aspect-ratio": {
            "type": UserInput.OPTION_CHOICE,
            "help": "Wall aspect ratio",
            "options": {
                "4:3": "4:3 (Oldschool)",
                "16:9": "16:9 (Widescreen)",
                "16:10": "16:10 (Golden ratio)",
                "1:1": "1:1 (Square)"
            },
            "default": "16:10",
            "tooltip": "Approximation. Final aspect ratio will depend on the size of each item."
        },

        # the next two are video-specific (not applicable to images)
        "audio": {
            "type": UserInput.OPTION_CHOICE,
            "help": "Audio handling",
            "options": {
                "longest": "Use audio from longest video in video wall",
                "none": "Remove audio"
            },
            "default": "longest"
        },
        "max-length": {
            "type": UserInput.OPTION_TEXT,
            "help": "Cut video after",
            "default": 60,
            "tooltip": "In seconds. Set to 0 or leave empty to use full video length; otherwise, videos will be "
                       "limited to the given amount of seconds. Not setting a limit can lead to extremely long "
                       "processor run times and is not recommended.",
            "coerce_type": int,
            "min": 0
        }
    }

    # videos will be arranged and resized to fit these image wall dimensions
    # note that video aspect ratio may not allow for a precise fit
    TARGET_DIMENSIONS = {
        "1:1": (2220, 2220),
        "4:3": (2560, 1920),
        "16:9": (2560, 1440),
        "16:10": (2560, 1600)
    }

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Determine compatibility

        :param DataSet module:  Module ID to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        :return bool:
        """
        if not (module.get_media_type() == "video" or module.type.startswith("video-downloader")):
            return False
        else:
            # Only check these if we have a video dataset
            # also need ffprobe to determine video lengths
            # is usually installed in same place as ffmpeg
            ffmpeg_path = shutil.which(config.get("video-downloader.ffmpeg_path"))
            ffprobe_path = shutil.which("ffprobe".join(ffmpeg_path.rsplit("ffmpeg", 1))) if ffmpeg_path else None
            return ffmpeg_path and ffprobe_path

    def process(self):
        """
        Go through media files, determine dimensions, sort according to the
        preferred method, determine canvas dimensions, then use ffmpeg to
        render files to canvas

        This processor can work with both images and videos.
        """
        sizing_mode = self.parameters.get("tile-size")
        sort_mode = self.parameters.get("sort-mode")
        amount = self.parameters.get("amount")
        if amount == 0:
            # user requests max number of video/images
            max_number_images = self.get_options(config=self.config).get("amount").get("max")
            if max_number_images:
                # server defined max
                amount = max_number_images
            else:
                # no max, so use all available media
                amount = self.source_dataset.num_rows

        sound = self.parameters.get("audio", "longest")
        max_length = self.parameters.get("max-length", 60)
        aspect_ratio = self.parameters.get("aspect-ratio")
        backfill = self.parameters.get("backfill")

        ffmpeg_path = shutil.which(self.config.get("video-downloader.ffmpeg_path"))
        ffprobe_path = shutil.which("ffprobe".join(ffmpeg_path.rsplit("ffmpeg", 1)))

        # unpack source items to stack
        # a staging area to store the items we're reading from
        # we look for images first, because images may be made from videos, but
        # not the other way around (in 4CAT)
        try_types = ["image-downloader", "video-frames", "video-downloader"]
        base_dataset = None
        while try_types and not base_dataset:
            base_dataset = self.source_dataset.nearest(f"{try_types.pop(0)}*")

        if not base_dataset:
            # not one of the known types, but processor is compatible, so
            # assume it's just the parent dataset
            base_dataset = self.source_dataset

        collage_staging_area = base_dataset.get_staging_area()

        lengths = {}
        dimensions = {}
        sort_values = {}
        media = {}
        skipped = 0

        # unpack items and determine length of the item (for sorting)
        self.dataset.update_status("Unpacking files and reading metadata")
        for item in self.iterate_archive_contents(base_dataset.get_results_path(), staging_area=collage_staging_area,
                                                   immediately_delete=False):
            if self.interrupted:
                shutil.rmtree(collage_staging_area, ignore_errors=True)
                return ProcessorInterruptedException("Interrupted while unpacking files")

            # skip metadata and log files
            self.dataset.update_status(f"Determined dimensions of {len(media):,} of {self.source_dataset.num_rows:,} file(s)")
            if item.suffix.lower() in (".json", ".log"):
                continue

            try:
                dimensions[item.name], lengths[item.name], sort_values[item.name] = \
                    self.get_signature(item, sort_mode, ffprobe_path)
            except MediaSignatureException as e:
                self.dataset.log(f"Cannot read dimensions of file {item.name}, skipping ({e})")
                skipped += 1
                continue

            media[item.name] = item

            # if not sorting, we don't need to probe everything and can stop
            # when we have as many as we need
            if not sort_mode and len(media) == amount:
                break

        if sort_mode:
            media = {k: media[k] for k in sorted(media, key=lambda k: sort_values[k])}

        # limit amount *after* sorting
        media_keys = list(media.keys())
        included_media = media_keys[:amount]
        excluded_media = media_keys[amount:]

        # if a dimension is empty, the next step will fail, so intercept
        if not included_media:
            return self.dataset.finish_with_error("No media with parseable dimensions left for collage after applying "
                                                  "selection criteria. There may be non-image files or corrupted files "
                                                  "in your dataset.")

        # overall average dimensions will be useful for some of the sizing modes
        avg = statistics.mean if sizing_mode == "average" else statistics.median
        included_dimensions = {k: dimensions[k] for k in included_media}
        average_size = (avg([k[0] for k in included_dimensions.values()]), avg([k[1] for k in included_dimensions.values()]))

        # calculate 'tile sizes' (a tile is a file) and also the size of the
        # canvas we will need to fit them all.
        self.dataset.update_status("Determining canvas and tile sizes")
        resolution = self.TARGET_DIMENSIONS[aspect_ratio]
        aspect_ratio = resolution[0] / resolution[1]
        aspect_ratio_inverse = resolution[1] / resolution[0]
        max_pixels = resolution[0] * resolution[1]

        if sizing_mode == "fit-height":
            # assuming every image has the overall average height, how wide would
            # the canvas need to be (if everything is on a single row)?
            full_width = 0
            tile_h = average_size[1]
            for dimension in included_dimensions.values():
                optimal_ratio = average_size[1] / dimension[1]
                full_width += dimension[0] * optimal_ratio

            # now we can calculate the total amount of pixels needed
            fitted_pixels = full_width * tile_h
            if fitted_pixels > max_pixels:
                # try again with a lower height
                area_ratio = max_pixels / fitted_pixels
                tile_h = int(tile_h * math.sqrt(area_ratio))
                fitted_pixels = max_pixels

            ideal_width = math.sqrt(fitted_pixels / aspect_ratio_inverse)
            item_widths = [int(dimensions[k][0] * (tile_h / dimensions[k][1])) for k in included_media]
            tile_w = -1  # variable

        elif sizing_mode == "square":
            # assuming each image is square, find a canvas with the right
            # proportions that would fit all of them
            tile_size = int(sum(average_size) / 2)
            tile_h = tile_size
            tile_w = tile_h

            # this is how many pixels we need
            fitted_pixels = tile_size * tile_size * len(included_media)

            # does that fit our canvas?
            if fitted_pixels > max_pixels:
                tile_size = math.floor(math.sqrt(max_pixels / len(included_media)))
                tile_w = tile_h = tile_size
                fitted_pixels = tile_size * tile_size * len(included_media)

            ideal_width = math.sqrt(fitted_pixels / aspect_ratio_inverse)
            item_widths = [tile_h for _ in included_media]

        elif sizing_mode in ("median", "average"):
            # uniform size, so similar to square, just a little bit more
            # complicated
            tile_w = int(average_size[0])
            tile_h = int(average_size[1])

            fitted_pixels = tile_w * tile_h * len(included_media)
            if fitted_pixels > max_pixels:
                area_ratio = max_pixels / fitted_pixels
                tile_w = int(tile_w * math.sqrt(area_ratio))
                tile_h = int(tile_h * math.sqrt(area_ratio))
                fitted_pixels = tile_w * tile_h * len(included_media)

            ideal_width = math.sqrt(fitted_pixels / aspect_ratio_inverse)
            item_widths = [tile_w for _ in included_media]

        else:
            raise NotImplementedError("Sizing mode '%s' not implemented" % sizing_mode)

        # now we simulate all possible distributions of the items and pick the
        # one closest to our required aspect ratio - this is brute force, but
        # with the relatively low amount of items, it's fast enough
        # add 1 to the item width to account for rounding differences later
        self.dataset.update_status("Reticulating splines...")
        item_widths = [w + 1 for w in item_widths]
        row_ratios = {}
        last_row_widths = {}
        for row_width in range(0, int(ideal_width * 1.5), min(item_widths)):
            rows = []
            row = []
            for media_w in item_widths:
                if sum(row) + media_w > row_width:
                    rows.append(row)
                    row = []
                row.append(media_w)
            else:
                if row:
                    rows.append(row)

            actual_width = max([sum(row) for row in rows])
            row_ratios[actual_width] = actual_width / (len(rows) * tile_h)
            last_row_widths[actual_width] = sum(row)

        # now select the width closest to the optimal ratio...
        min_deviation = None
        for actual_width, ratio in row_ratios.items():
            deviation = abs(ratio - aspect_ratio)
            if not min_deviation or deviation < min_deviation:
                size_x = actual_width
                min_deviation = deviation

        # if there is room left, add more files until the canvas is as full as
        # possible
        last_row_width = last_row_widths[size_x]
        if backfill and last_row_width < size_x:
            while excluded_media:
                item = excluded_media.pop(0)
                media_w = dimensions[item][0] * (tile_h / dimensions[item][1])
                if last_row_width + media_w < size_x:
                    included_media.append(item)
                    last_row_width += media_w


        # if we have *only* images, we can simply output an image with no audio
        # when finished rendering
        # same if we're running as the image wall generator
        have_only_images = sum([lengths[m] for m in included_media]) == 0 or self.extension == "png"

        if not have_only_images:
            # see which of the files is the longest, after sorting
            # used to determine which audio stream to use (if relevant)
            longest_duration = 0
            longest_index = 0
            for i, key in enumerate(included_media):
                if lengths[key] > longest_duration:
                    longest_index = i
                    longest_duration = lengths[key]

            # longest item in set may be shorter than requested length
            if max_length:
                max_length = min(max([lengths[v] for v in included_media]), max_length)

        # finalise dimensions
        size_y = round(size_x / row_ratios[size_x])
        tile_h = round(tile_h)
        tile_w = round(tile_w)
        self.dataset.log(f"Projected canvas size is {size_x}x{size_y} (aspect ratio {row_ratios[size_x]}; closest to {aspect_ratio})")
        self.dataset.log(f"Aiming for {round(size_y / tile_h)} vertical rows")

        # now we are ready to render the collage
        command = [ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error"]
        if not have_only_images and max_length:
            command.extend(["-t", str(max_length)]) # limit read length

        # construct an ffmpeg filter for this
        # basically, stack items horizontally until the max width is reached
        # then stack those horizontal stacks vertically
        # resize the items first
        index = 0
        resize = []  # resize filters to make tiles from items
        padding = []  # padding filters to make all rows the same width

        row = []
        rows = []
        row_width = 0
        row_widths = []

        # todo: periodically check if we still need to support ffmpeg < 5.1...
        ffmpeg_version = get_ffmpeg_version(ffmpeg_path)
        have_old_ffmpeg_version = ffmpeg_version < version.parse("7.1")
        fps_command = "-fps_mode" if ffmpeg_version >= version.parse("5.1") else "-vsync"

        # go through each item and transform as needed
        # why not use the xstack filter that ffmpeg has for this purpose?
        # the xstack filter does not cope well with items of variable size,
        # which are often abundant in 4CAT datasets
        looping = True
        iter_index = 0
        while True:
            try:
                item = included_media[iter_index]
                path = media[item]
                iter_index += 1
            except IndexError:
                looping = False

            # determine expected width of item when added to row
            if tile_w < 0:
                # 'fit height' - width varies per item
                item_width = math.ceil(dimensions[item][0] * (tile_h / dimensions[item][1])) if looping else 0
            else:
                item_width = tile_w

            if row and (not looping or (row_width + item_width) >= size_x):
                # adding this item would make the row too wide
                # so add current row to buffer and start a new one
                if len(row) > 1:
                    # use hstack to tile the items in the row horizontally
                    rows.append("".join(row) + f"hstack=inputs={len(row)}[stack{len(rows)}]")
                else:
                    # hstack needs more than one item as input, so for a
                    # single item just rename the stream
                    rows.append(row[0] + f"null[stack{len(rows)}]")
                row = []
                row_widths.append(row_width)
                row_width = 0

            if not looping:
                break

            # if we have an item, continue filling the grid
            # make into tile - with resizing (if proportional) or cropping (if not)
            row_width += item_width

            # prepare filter to transform item into wall tile
            cropscale = "select=eq(n\\,0)," if have_only_images else ""

            if sizing_mode == "fit-height":
                # the scale filter does not guarantee exact pixel dimensions
                # unfortunately this leads to us being off by one pixel on the
                # row width sometimes. So sacrifice one pixel by cropping,
                # which does guarantee exact sizes
                cropscale += f"scale={item_width+1}:{tile_h+1},crop={item_width}:{tile_h}:exact=1"

            elif sizing_mode == "square":
                if dimensions[item][0] > dimensions[item][1]:
                    cropscale += f"scale=-1:{tile_h},"
                else:
                    cropscale += f"scale={tile_w}:-1,"

                cropscale += f"crop={tile_w}:{tile_h}:exact=1"
                # exact=1 and format=rgba prevents shenanigans when merging

            elif sizing_mode in ("median", "average"):
                scale_w = dimensions[item][0] * (tile_h / dimensions[item][1])
                if scale_w < tile_w:
                    cropscale += f"scale={tile_w}:-1,"
                else:
                    cropscale += f"scale=-1:{tile_h},"

                cropscale += f"crop={tile_w}:{tile_h}:exact=1"

            else:
                raise NotImplementedError(f"Unknown sizing mode {sizing_mode}")

            cropscale += f"[scaled{index}]"
            resize.append(cropscale)

            command += ["-i", str(path)]
            row.append(f"[scaled{index}]")
            index += 1

        for row, width in enumerate(row_widths):
            if width != max(row_widths):
                # pad so that each row is the same width
                # we cannot use the pad filter since that requires that we
                # increase the height as well, but we just want to increase
                # width - so overlay on a correctly sized black canvas
                padding.append(f"color=size={max(row_widths)}x{tile_h}:color=black[bg{row}];[bg{row}][stack{row}]overlay=0:0[stack{row}]")

        # now create the ffmpeg filter from this
        filter_chain = ""

        # start by resizing all input streams to the required tile dimensions
        if resize:
            filter_chain += ";".join(resize) + ";"
        filter_chain += ";".join(rows) + ";"

        # then pad the horizontal rows of item tiles so they all have the
        # same width
        if padding:
            filter_chain += ";".join(padding) + ";"

        # finally stack horizontal rows, vertically
        if len(rows) > 1:
            filter_chain += "".join([f"[stack{i}]" for i in range(0, len(rows))]) + f"vstack=inputs={len(rows)}[final]"
        else:
            filter_chain += "[stack0]null[final]"  # we need a stream named final, anyhow

        # output item dimensions need to be divisible by 2 for x264 encoding
        # choose the relevant filter based on which dimensions do not conform
        # pad is faster, but can only be used if both dimensions increase
        output_w = max(row_widths)
        output_h = tile_h * len(row_widths)
        if output_w % 2 != 0 and output_h % 2 != 0:
            filter_chain += f";[final]pad={output_w+1}:{output_h+1}[final]"
        elif output_w % 2 != 0:
            filter_chain += f";color=size={output_w+1}x{output_h}:color=black[bgfinal];[bgfinal][final]overlay=0:0[final]"
        elif output_h % 2 != 0:
            filter_chain += f";color=size={output_w}x{output_h+1}:color=black[bgfinal];[bgfinal][final]overlay=0:0[final]"

        # force 30 fps because we don't know what the source videos did and
        # they could be using different fps
        if not have_only_images:
            filter_chain += ";[final]fps=30[final]"

        # add filter to ffmpeg command, plus a parameter to control output FPS
        ffmpeg_filter = oslex.quote(filter_chain)[1:-1]

        command += [fps_command, "cfr", "-filter_complex", ffmpeg_filter]
        if have_only_images:
            command += ["-frames:v", "1", "-update", "true"] # we need only one output frame!

        # ensure mixed audio: use no sound, or the longest audio stream
        if have_only_images or sound == "none":
            command += ["-an"]
        elif sound == "longest":
            command += ["-map", f"{longest_index}:a"]

        # use final stream for output
        command += ["-map", "[final]"]

        # limit output video length
        if max_length and not have_only_images:
            command.extend(["-t", str(max_length)])

        # set output file
        output_file = self.dataset.get_results_path()
        command.append(oslex.quote(str(output_file)))

        self.dataset.log(f"Using ffmpeg filter {ffmpeg_filter}")
        self.dataset.update_status("Creating collage with ffmpeg (this may take a while)")
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if self.interrupted:
            shutil.rmtree(collage_staging_area, ignore_errors=True)
            return ProcessorInterruptedException("Interrupted while running ffmpeg")

        # Capture logs
        ffmpeg_error = result.stderr.decode("utf-8")

        if ffmpeg_error:
            self.dataset.log("ffmpeg returned the following errors:")
            for line in ffmpeg_error.split("\n"):
                self.dataset.log("  " + line)

            if have_old_ffmpeg_version:
                self.dataset.log("You may be able to prevent this error by updating to a newer version of ffmpeg.")

            # we get only stream numbers from ffmpeg, make this a bit easier
            # to interpret:
            if erroneous_stream := re.findall("input from stream ([0-9]+)", ffmpeg_error):
                erroneous_stream = convert_to_int(erroneous_stream[0], None)
                if erroneous_stream is not None and erroneous_stream < len(included_media):
                    # todo: could run again without this video... but that
                    # would require a bit of a refactor
                    self.dataset.log(f"The error message indicates the file {included_media[erroneous_stream]} cannot be read; it may be corrupt.")

        shutil.rmtree(collage_staging_area, ignore_errors=True)

        if result.returncode != 0:
            if ffmpeg_error:
                self.log.warning(f"ffmpeg error (dataset {self.dataset.key}): {ffmpeg_error}")
            return self.dataset.finish_with_error(
                f"Could not make collage (error {result.returncode}); check the dataset log for details.")

        if skipped:
             self.dataset.update_status(f"Rendering finished. {skipped} item(s) were skipped; see dataset log for details.", is_final=True)
        else:
             self.dataset.update_status("Rendering finished.")
             self.dataset.finish(1)

    def get_signature(self, file_path, sort_mode, ffprobe_path):
        """
        Get file signature

        Child classes can define a method `sort_file`, with the same signature
        as this method, that will be called if an otherwise unknown sort mode
        is used. The return value will be used as the third element of the
        tuple returned by this method.

        :param Path file_path:  Path to file to get signature of
        :param str sort_mode:  Sorting mode, defaults to (video) length
        :param str ffprobe_path:  Path to the ffprobe executable
        :return tuple:  A tuple with three values: (width, height), length,
        and a value to sort by (e.g. length or colour). For images, length is
        0.
        """
        probe_command = [ffprobe_path, "-v", "error", "-select_streams", "v:0", "-show_entries",
                         "stream=width,height,duration", "-of", "csv=p=0", oslex.quote(str(file_path))]
        probe = subprocess.run(probe_command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)

        probe_output = probe.stdout.decode("utf-8")
        probe_error = probe.stderr.decode("utf-8")

        if probe_error:
            raise MediaSignatureException()

        bits = probe_output.split(",")
        length = (float(bits[-1]) if bits[-1].strip() != "N/A" else 0)
        try:
            dimensions = (int(bits[0]), int(bits[1]))
        except ValueError:
            raise MediaSignatureException()

        if sort_mode == "random":
            sort_value = random.random()
        elif sort_mode in ("shortest", "longest"):
            sort_value = length
        elif hasattr(self, "sort_file"):
            sort_value = self.sort_file(file_path, sort_mode, ffprobe_path)
        else:
            sort_value = 0

        return dimensions, length, sort_value
