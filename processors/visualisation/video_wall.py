"""
Create a collage of videos playing side by side
"""
import random
import shutil
import math
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
            "help": "No. of videos (max 100)",
            "default": 25,
            "min": 0,
            "max": 100,
            "tooltip": "'0' uses as many videos as available in the archive (up to 100)"
        },
        "tile-size": {
            "type": UserInput.OPTION_CHOICE,
            "options": {
                "square": "Square",
                "average": "Average video in set",
                "fit-height": "Fit height"
            },
            "default": "square",
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
    TARGET_WIDTH = 2560
    TARGET_HEIGHT = 1440

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Determine compatibility

        :param str module:  Module ID to determine compatibility with
        :param ConfigWrapper config:  Configuration reader
        :return bool:
        """
        if module.is_dataset() and module.num_rows > 50:
            # this processor doesn't work well with large datasets
            return False

        # also need ffprobe to determine video lengths
        # is usually installed in same place as ffmpeg
        ffmpeg_path = shutil.which(config.get("video-downloader.ffmpeg_path"))
        ffprobe_path = shutil.which("ffprobe".join(ffmpeg_path.rsplit("ffmpeg", 1)))

        return module.type.startswith("video-downloader") and \
            ffmpeg_path and \
            ffprobe_path

    def process(self):
        """
        This takes a 4CAT results file as input, and outputs a new CSV file
        with one column with image hashes, one with the first file name used
        for the image, and one with the amount of times the image was used
        """
        sizing_mode = self.parameters.get("tile-size")
        sort_mode = self.parameters.get("sort-mode")
        amount = self.parameters.get("amount")
        sound = self.parameters.get("audio")
        video_length = self.parameters.get("max-length")

        ffmpeg_path = shutil.which(self.config.get("video-downloader.ffmpeg_path"))
        ffprobe_path = shutil.which("ffprobe".join(ffmpeg_path.rsplit("ffmpeg", 1)))

        # unpack source videos to stack
        # a staging area to store the videos we're reading from
        video_dataset = self.source_dataset.nearest("video-downloader*")
        video_staging_area = video_dataset.get_staging_area()

        lengths = {}
        dimensions = {}
        videos = {}

        # unpack videos and determine length of the video (for sorting)
        for video in self.iterate_archive_contents(video_dataset.get_results_path(), staging_area=video_staging_area,
                                                   immediately_delete=False):
            if self.interrupted:
                shutil.rmtree(video_staging_area, ignore_errors=True)
                return ProcessorInterruptedException("Interrupted while unpacking videos")

            # skip JSON
            if video.name == '.metadata.json':
                continue

            video_path = oslex.quote(str(video))

            # determine length if needed
            probe_command = [ffprobe_path, "-v", "error", "-select_streams", "v:0", "-show_entries",
                             "stream=width,height,duration", "-of", "csv=p=0", video_path]
            probe = subprocess.run(probe_command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)

            probe_output = probe.stdout.decode("utf-8")
            probe_error = probe.stderr.decode("utf-8")
            if probe_error:
                shutil.rmtree(video_staging_area, ignore_errors=True)
                return self.dataset.finish_with_error(f"Cannot determine dimensions of video {video.name}. Cannot tile "
                                                      "videos without knowing the video dimensions.")
                # ...or should we just skip it instead?
            else:
                bits = probe_output.split(",")
                dimensions[video.name] = (int(bits[0]), int(bits[1]))
                lengths[video.name] = float(bits[-1])

            videos[video.name] = video

            # if not sorting, we don't need to probe everything and can stop
            # when we have as many as we need
            if not sort_mode and amount and len(videos) == amount:
                break

        if sort_mode in ("longest", "shortest"):
            videos = {k: videos[k] for k in
                      sorted(videos, key=lambda k: lengths[k], reverse=(sort_mode == "longest"))}
        elif sort_mode == "random":
            videos = {k: videos[k] for k in sorted(videos, key=lambda k: random.random())}

        # limit amount *after* sorting
        if amount:
            sliced_videos = {}
            video_keys = list(videos.keys())
            for i in range(0, amount):
                sliced_videos[video_keys[i]] = videos[video_keys[i]]
            videos = sliced_videos
            lengths = {k: v for k, v in lengths.items() if k in [videos[p].name for p in videos]}

        # see which of the videos is the longest, after sorting
        # used to determine which audio stream to use
        max_length = max(lengths.values())
        longest_index = 0
        for video in videos:
            if lengths[video] == max_length:
                break

            longest_index += 1

        average_size = (
            sum([k[0] for k in dimensions.values()]) / len(dimensions),
            sum([k[1] for k in dimensions.values()]) / len(dimensions))

        self.dataset.update_status("Determining canvas and tile sizes")

        # why not use the xstack filter that ffmpeg has for this purpose?
        # the xstack filter does not cope well with videos of different sizes,
        # which are often abundant in 4CAT datasets

        # calculate 'tile sizes' (a tile is an image) and also the size of the
        # canvas we will need to fit them all. The canvas can never be larger than
        # this:
        max_pixels = self.TARGET_WIDTH * self.TARGET_HEIGHT

        if sizing_mode == "fit-height":
            # assuming every image has the overall average height, how wide would
            # the canvas need to be (if everything is on a single row)?
            full_width = 0
            tile_h = average_size[1]
            for dimension in dimensions.values():
                # ideally, we make everything the average height
                optimal_ratio = average_size[1] / dimension[1]
                full_width += dimension[0] * optimal_ratio

            # now we can calculate the total amount of pixels needed
            fitted_pixels = full_width * tile_h
            if fitted_pixels > max_pixels:
                # try again with a lower height
                area_ratio = max_pixels / fitted_pixels
                tile_h = int(tile_h * math.sqrt(area_ratio))
                fitted_pixels = max_pixels

            # find the canvas size that can fit this amount of pixels at the
            # required proportions, provided that y = multiple of avg height
            ideal_height = math.sqrt(fitted_pixels / (self.TARGET_WIDTH / self.TARGET_HEIGHT))
            size_y = math.ceil(ideal_height / tile_h) * tile_h
            size_x = fitted_pixels / size_y

            tile_w = -1  # varies

        elif sizing_mode == "square":
            # assuming each image is square, find a canvas with the right
            # proportions that would fit all of them
            # assume the average dimensions
            tile_size = int(sum(average_size) / 2)

            # this is how many pixels we need
            fitted_pixels = tile_size * tile_size * len(videos)

            # does that fit our canvas?
            if fitted_pixels > max_pixels:
                tile_size = math.floor(math.sqrt(max_pixels / len(videos)))
                fitted_pixels = tile_size * tile_size * len(videos)

            ideal_width = math.sqrt(fitted_pixels / (self.TARGET_HEIGHT / self.TARGET_WIDTH))
            size_x = math.ceil(ideal_width / tile_size) * tile_size
            size_y = math.ceil(fitted_pixels / size_x / tile_size) * tile_size

            tile_w = tile_h = tile_size

        elif sizing_mode == "average":
            tile_w = int(average_size[0])
            tile_h = int(average_size[1])

            fitted_pixels = tile_w * tile_h * len(videos)
            if fitted_pixels > max_pixels:
                area_ratio = max_pixels / fitted_pixels
                tile_w = int(tile_w * math.sqrt(area_ratio))
                tile_h = int(tile_h * math.sqrt(area_ratio))
                fitted_pixels = tile_w * tile_h * len(videos)

            ideal_width = math.sqrt(fitted_pixels / (self.TARGET_HEIGHT / self.TARGET_WIDTH))
            size_x = math.ceil(ideal_width / tile_w) * tile_w
            size_y = math.ceil(fitted_pixels / size_x / tile_h) * tile_h

        else:
            raise NotImplementedError("Sizing mode '%s' not implemented" % sizing_mode)

        # round to avoid annoying issues and because we don't need subpixels
        tile_h = round(tile_h)
        tile_w = round(tile_w)

        self.dataset.log("Canvas size is %ix%i" % (size_x, size_y))

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
        fps_command = "-fps_mode" if get_ffmpeg_version(ffmpeg_path) >= version.parse("5.1") else "-vsync"

        # go through each video and transform as needed
        looping = True
        video_queue = list(videos.items())
        while True:
            try:
                video, path = video_queue.pop(0)
            except IndexError:
                looping = False

            # determine expected width of video when added to row
            if tile_w < 0:
                video_width = round(dimensions[video][0] * (tile_h / dimensions[video][1])) if looping else 0
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
                cropscale += f"scale={video_width}:{tile_h}"

            elif sizing_mode == "square":
                if dimensions[video][0] > dimensions[video][1]:
                    cropscale += f"scale=-1:{tile_h},"
                else:
                    cropscale += f"scale={tile_w}:-1,"

                cropscale += f"crop={tile_w}:{tile_h}:exact=1,format=rgba"
                # exact=1 and format=rgba prevents shenanigans when merging

            elif sizing_mode == "average":
                scale_w = dimensions[video][0] * (tile_h / dimensions[video][1])
                if scale_w < tile_w:
                    cropscale += f"scale={tile_w}:-1,"
                else:
                    cropscale += f"scale=-1:{tile_h},"

                cropscale += f"crop={tile_w}:{tile_h}:exact=1,format=rgba"

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
            filter_chain += "".join([f"[stack{i}]" for i in range(0, len(rows))]) + f"vstack=inputs={len(rows)}[final];"
        else:
            filter_chain += "[stack0]null[final];"

        # output video dimensions need to be divisible by 2 for x264 encoding
        # choose the relevant filter based on which dimensions do not conform
        # pad is faster, but can only be used if both dimensions increase
        output_w = max(row_widths)
        output_h = tile_h * len(row_widths)
        if output_w % 2 != 0 and output_h % 2 != 0:
            filter_chain += f"[final]pad={output_w+1}:{output_h+1}[final]"
        elif output_w % 2 != 0:
            filter_chain += f"color=size={output_w+1}x{output_h}:color=black[bgfinal];[bgfinal][final]overlay=0:0[final]"
        elif output_h % 2 != 0:
            filter_chain += f"color=size={output_w}x{output_h+1}:color=black[bgfinal];[bgfinal][final]overlay=0:0[final]"

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

        shutil.rmtree(video_staging_area, ignore_errors=True)

        if result.returncode != 0:
            return self.dataset.finish_with_error(
                f"Could not make video wall (error {result.returncode}); check the dataset log for details.")

        self.dataset.finish(1)
