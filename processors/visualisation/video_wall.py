"""
Create a collage of videos playing side by side
"""
import random
import shutil
import math
import statistics

import oslex
import subprocess

from packaging import version

from common.lib.helpers import UserInput, get_ffmpeg_version
from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class VideoWallGenerator(BasicProcessor):
    """
    Image wall generator

    Create an image wall from the top images in the dataset
    """
    type = "video-wall"  # job type ID
    category = "Visual"  # category
    title = "Video wall"  # title displayed in UI
    description = "Put all videos in a single combined video, side by side. Videos can be sorted and resized."
    extension = "mp4"  # extension of result file, used internally and in UI

    options = {
        "amount": {
            "type": UserInput.OPTION_TEXT,
            "help": "No. of videos (max 500)",
            "default": 25,
            "min": 0,
            "max": 500,
            "tooltip": "'0' uses as many videos as available in the archive (up to 500)"
        },
        "backfill": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Add more videos if there is room",
            "default": True,
            "tooltip": "If there are more videos than the given number and "
                       "there is space left to add them to the wall, do so"
        },
        "tile-size": {
            "type": UserInput.OPTION_CHOICE,
            "options": {
                "square": "Square",
                "average": "Average video in set",
                "median": "Median video in set",
                "fit-height": "Fit height"
            },
            "default": "median",
            "help": "Video tile size",
            "tooltip": "'Fit height' retains width/height ratios but makes videos have the same height"
        },
        "sort-mode": {
            "type": UserInput.OPTION_CHOICE,
            "help": "Sort videos by",
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
            "tooltip": "Approximation. Final aspect ratio will depend on size of input videos."
        },
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
    TARGET_WIDTH = 2560
    TARGET_HEIGHT = 1440

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
        This takes a 4CAT results file as input, and outputs a new CSV file
        with one column with image hashes, one with the first file name used
        for the image, and one with the amount of times the image was used
        """
        sizing_mode = self.parameters.get("tile-size")
        sort_mode = self.parameters.get("sort-mode")
        amount = self.parameters.get("amount")
        amount = amount if amount else 500
        sound = self.parameters.get("audio")
        video_length = self.parameters.get("max-length")
        aspect_ratio = self.parameters.get("aspect-ratio")
        backfill = self.parameters.get("backfill")

        ffmpeg_path = shutil.which(self.config.get("video-downloader.ffmpeg_path"))
        ffprobe_path = shutil.which("ffprobe".join(ffmpeg_path.rsplit("ffmpeg", 1)))

        # unpack source videos to stack
        # a staging area to store the videos we're reading from
        video_dataset = self.source_dataset.nearest("video-downloader*")
        video_staging_area = video_dataset.get_staging_area()

        lengths = {}
        dimensions = {}
        videos = {}
        skipped = 0

        # unpack videos and determine length of the video (for sorting)
        self.dataset.update_status("Unpacking videos and reading metadata")
        for video in self.iterate_archive_contents(video_dataset.get_results_path(), staging_area=video_staging_area,
                                                   immediately_delete=False):
            if self.interrupted:
                shutil.rmtree(video_staging_area, ignore_errors=True)
                return ProcessorInterruptedException("Interrupted while unpacking videos")

            # skip JSON
            if video.name == '.metadata.json':
                continue

            self.dataset.update_status(f"Read {len(videos):,} of {self.source_dataset.num_rows:,} video(s)")
            video_path = oslex.quote(str(video))

            # determine length if needed
            probe_command = [ffprobe_path, "-v", "error", "-select_streams", "v:0", "-show_entries",
                             "stream=width,height,duration", "-of", "csv=p=0", video_path]
            probe = subprocess.run(probe_command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)

            probe_output = probe.stdout.decode("utf-8")
            probe_error = probe.stderr.decode("utf-8")
            if probe_error:
                self.dataset.log(f"Cannot determine dimensions of video {video.name}. Excluding from wall.")
                skipped += 1
                continue
            else:
                bits = probe_output.split(",")
                dimensions[video.name] = (int(bits[0]), int(bits[1]))
                lengths[video.name] = float(bits[-1])

            videos[video.name] = video

            # if not sorting, we don't need to probe everything and can stop
            # when we have as many as we need
            if not sort_mode and len(videos) == amount:
                break

        if sort_mode in ("longest", "shortest"):
            videos = {k: videos[k] for k in
                      sorted(videos, key=lambda k: lengths[k], reverse=(sort_mode == "longest"))}
        elif sort_mode == "random":
            videos = {k: videos[k] for k in sorted(videos, key=lambda k: random.random())}

        # limit amount *after* sorting
        included_videos = []
        excluded_videos = []
        for key, video in videos.items():
            if len(included_videos) < amount:
                included_videos.append(key)
            else:
                excluded_videos.append(key)

        avg = statistics.mean if sizing_mode == "average" else statistics.median
        included_dimensions = {k: dimensions[k] for k in included_videos}
        average_size = (avg([k[0] for k in included_dimensions.values()]), avg([k[1] for k in included_dimensions.values()]))

        # calculate 'tile sizes' (a tile is a video) and also the size of the
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
            item_widths = [int(dimensions[k][0] * (tile_h / dimensions[k][1])) for k in included_videos]
            tile_w = -1  # variable

        elif sizing_mode == "square":
            # assuming each image is square, find a canvas with the right
            # proportions that would fit all of them
            # assume the average dimensions
            tile_size = int(sum(average_size) / 2)
            tile_h = tile_size

            # this is how many pixels we need
            fitted_pixels = tile_size * tile_size * len(included_videos)

            # does that fit our canvas?
            if fitted_pixels > max_pixels:
                tile_size = math.floor(math.sqrt(max_pixels / len(included_videos)))
                fitted_pixels = tile_size * tile_size * len(included_videos)

            ideal_width = math.sqrt(fitted_pixels / aspect_ratio_inverse)
            item_widths = [tile_h for _ in included_videos]

        elif sizing_mode in ("median", "average"):
            tile_w = int(average_size[0])
            tile_h = int(average_size[1])

            fitted_pixels = tile_w * tile_h * len(included_videos)
            if fitted_pixels > max_pixels:
                area_ratio = max_pixels / fitted_pixels
                tile_w = int(tile_w * math.sqrt(area_ratio))
                tile_h = int(tile_h * math.sqrt(area_ratio))
                fitted_pixels = tile_w * tile_h * len(included_videos)

            ideal_width = math.sqrt(fitted_pixels / aspect_ratio_inverse)
            item_widths = [tile_w for _ in included_videos]

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
            for video_w in item_widths:
                if sum(row) + video_w > row_width:
                    rows.append(row)
                    row = []
                row.append(video_w)
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

        # if there is room left, add more videos until the canvas is as full as
        # possible
        last_row_width = last_row_widths[size_x]
        if backfill and last_row_width < size_x:
            while excluded_videos:
                video = excluded_videos.pop(0)
                video_w = dimensions[video][0] * (tile_h / dimensions[video][1])
                if last_row_width + video_w < size_x:
                    included_videos.append(video)
                    last_row_width += video_w

        # see which of the videos is the longest, after sorting
        # used to determine which audio stream to use
        max_length = 0
        longest_index = 0
        for i, video in enumerate(included_videos):
            if lengths[video] > max_length:
                longest_index = i
                max_length = lengths[video]

        # finalise dimensions
        size_y = round(size_x / row_ratios[size_x])
        tile_h = round(tile_h)
        tile_w = round(tile_w)
        self.dataset.log(f"Projected canvas size is {size_x}x{size_y} (aspect ratio {row_ratios[size_x]}; {aspect_ratio} preferred)")
        self.dataset.log(f"Aiming for {round(size_y / tile_h)} rows of videos")

        # longest video in set may be shorter than requested length
        if video_length:
            video_length = min(max([lengths[v] for v in included_videos]), video_length)

        # now we are ready to render the video wall
        command = [ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error"]
        if video_length:
            command.extend(["-t", str(video_length)]) # limit read length

        # construct an ffmpeg filter for this
        # basically, stack videos horizontally until the max width is reached
        # then stack those horizontal stacks vertically
        # resize the videos first
        index = 0
        resize = []  # resize filters to make tiles from videos
        padding = []  # padding filters to make all rows the same width

        row = []
        rows = []
        row_width = 0
        row_widths = []

        # todo: periodically check if we still need to support ffmpeg < 5.1
        have_old_ffmpeg_version = get_ffmpeg_version(ffmpeg_path) < version.parse("7.1")
        fps_command = "-fps_mode" if get_ffmpeg_version(ffmpeg_path) >= version.parse("5.1") else "-vsync"

        # go through each video and transform as needed
        # why not use the xstack filter that ffmpeg has for this purpose?
        # the xstack filter does not cope well with videos of different sizes,
        # which are often abundant in 4CAT datasets
        looping = True
        while True:
            try:
                video = included_videos.pop(0)
                path = videos[video]
            except IndexError:
                looping = False

            # determine expected width of video when added to row
            if tile_w < 0:
                # 'fit height' - width varies per video
                video_width = math.ceil(dimensions[video][0] * (tile_h / dimensions[video][1])) if looping else 0
            else:
                video_width = tile_w

            if row and (not looping or (row_width + video_width) >= size_x):
                # adding this video would make the row too wide
                # so add current row to buffer and start a new one
                if len(row) > 1:
                    # use hstack to tile the videos in the row horizontally
                    rows.append("".join(row) + f"hstack=inputs={len(row)}[stack{len(rows)}]")
                else:
                    # hstack needs more than one video as input, so for a
                    # single video just rename the stream
                    rows.append(row[0] + f"null[stack{len(rows)}]")
                row = []
                row_widths.append(row_width)
                row_width = 0

            if not looping:
                break

            # if we have a video, continue filling the grid
            # make into tile - with resizing (if proportional) or cropping (if not)
            row_width += video_width

            # prepare filter to transform video into wall tile
            cropscale = ""

            if sizing_mode == "fit-height":
                # the scale filter does not guarantee exact pixel dimensions
                # unfortunately this leads to us being off by one pixel on the
                # row width sometimes. So sacrifice one pixel by cropping,
                # which does guarantee exact sizes
                cropscale += f"scale={video_width+1}:{tile_h+1},crop={video_width}:{tile_h}:exact=1"

            elif sizing_mode == "square":
                if dimensions[video][0] > dimensions[video][1]:
                    cropscale += f"scale=-1:{tile_h},"
                else:
                    cropscale += f"scale={tile_w}:-1,"

                cropscale += f"crop={tile_w}:{tile_h}:exact=1"
                # exact=1 and format=rgba prevents shenanigans when merging

            elif sizing_mode in ("median", "average"):
                scale_w = dimensions[video][0] * (tile_h / dimensions[video][1])
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

        # then pad the horizontal rows of video tiles so they all have the
        # same width
        if padding:
            filter_chain += ";".join(padding) + ";"

        # finally stack horizontal rows, vertically
        if len(rows) > 1:
            filter_chain += "".join([f"[stack{i}]" for i in range(0, len(rows))]) + f"vstack=inputs={len(rows)}[final]"
        else:
            filter_chain += "[stack0]null[final]"

        # output video dimensions need to be divisible by 2 for x264 encoding
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
        # they could be using different fpss
        filter_chain += ";[final]fps=30[final]"

        # add filter to ffmpeg command, plus a parameter to control output FPS
        ffmpeg_filter = oslex.quote(filter_chain)[1:-1]

        command += [fps_command, "cfr", "-filter_complex", ffmpeg_filter]

        # ensure mixed audio: use no sound, or the longest audio stream
        if sound == "none":
            command += ["-an"]
        elif sound == "longest":
            command += ["-map", f"{longest_index}:a"]

        # use tiled video stream
        command += ["-map", "[final]"]

        # limit output video length
        if video_length:
            command.extend(["-t", str(video_length)])

        # set output file
        command.append(oslex.quote(str(self.dataset.get_results_path())))

        self.dataset.log(f"Using ffmpeg filter {ffmpeg_filter}")
        self.dataset.update_status("Merging video files with ffmpeg (this can take a while)")
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if self.interrupted:
            shutil.rmtree(video_staging_area, ignore_errors=True)
            return ProcessorInterruptedException("Interrupted while running ffmpeg")

        # Capture logs
        ffmpeg_output = result.stdout.decode("utf-8")
        ffmpeg_error = result.stderr.decode("utf-8")

        if ffmpeg_output:
            self.dataset.log("ffmpeg returned the following output:")
            for line in ffmpeg_output.split("\n"):
                self.dataset.log("  " + line)

        if ffmpeg_error:
            self.dataset.log("ffmpeg returned the following errors:")
            for line in ffmpeg_error.split("\n"):
                self.dataset.log("  " + line)

            if have_old_ffmpeg_version:
                self.dataset.log("You may be able to prevent this error by updating to a newer version of ffmpeg.")

        shutil.rmtree(video_staging_area, ignore_errors=True)

        if result.returncode != 0:
            return self.dataset.finish_with_error(
                f"Could not make video wall (error {result.returncode}); check the dataset log for details.")

        if skipped:
            self.dataset.update_status(f"Video wall rendering finished. {skipped} video(s) were skipped; see dataset log for details.", is_final=True)
        else:
            self.dataset.update_status("Video wall rendering finished.")
            
        self.dataset.finish(1)