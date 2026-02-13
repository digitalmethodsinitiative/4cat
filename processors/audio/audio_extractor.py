"""
Extract audio from video archive

This processor also requires ffmpeg to be installed in 4CAT's backend
https://ffmpeg.org/
"""
import shutil
import oslex

from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"

from common.lib.user_input import UserInput


class AudioExtractor(BasicProcessor):
    """
    Audio from video Extractor

    Uses ffmpeg to extract audio from videos and saves them in an archive.
    """
    type = "audio-extractor"  # job type ID
    category = "Audio"  # category
    title = "Extract audio from videos"  # title displayed in UI
    description = "Create audio files per video"  # description displayed in UI
    extension = "zip"  # extension of result file, used internally and in UI

    followups = ["audio-to-text"]

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Allow on videos only

        :param ConfigManager|None config:  Configuration reader (context-aware)
        """
        return (module.get_media_type() == "video" or module.type.startswith("video-downloader")) and \
            config.get("video-downloader.ffmpeg_path") and \
            shutil.which(config.get("video-downloader.ffmpeg_path"))

    @classmethod
    def get_options(cls, parent_dataset=None, config=None):
        """
        Collect maximum number of audio files from configuration and update options accordingly
        :param config:
        """
        return {
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "help": "Number of audio files to extract (0 will extract all)",
                "default": 10,
                "min": 0,
            }
        }

    def process(self):
        """
        This takes a zipped set of videos and uses https://ffmpeg.org/ to collect audio into a zip archive
        """
        # Check processor able to run
        if self.source_dataset.num_rows == 0:
            self.dataset.finish_as_empty("No videos from which to extract audio.")
            return

        max_files = self.parameters.get("amount", 100)

        # Prepare staging areas for videos and video tracking
        output_dir = self.dataset.get_staging_area()

        total_possible_videos = max_files if max_files != 0 and max_files < self.source_dataset.num_rows - 1 \
            else self.source_dataset.num_rows

        processed_videos = 0
        written = 0

        self.dataset.update_status("Extracting video audio")
        for item in self.source_dataset.iterate_items():
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while determining image wall order")

            # Check for 4CAT's metadata JSON and copy it
            if item.file.name == '.metadata.json':
                shutil.copy(item.file, output_dir.joinpath(".video_metadata.json"))
                continue

            if max_files != 0 and processed_videos >= max_files:
                break

            vid_name = item.file.stem
            # ffmpeg -i video.mkv -map 0:a -acodec libmp3lame audio.mp4
            command = [
                shutil.which(self.config.get("video-downloader.ffmpeg_path")),
                "-i", oslex.quote(str(item.file)),
                "-ar", str(16000),
                oslex.quote(str(output_dir.joinpath(f"{vid_name}.wav")))
            ]

            result = self.run_interruptable_process(command, cleanup_paths=(output_dir,))

            # Capture logs
            ffmpeg_output = result.stdout.decode("utf-8")
            ffmpeg_error = result.stderr.decode("utf-8")

            audio_file = output_dir.joinpath(f"{vid_name}.wav")
            if audio_file.exists():
                written += 1

            if ffmpeg_output:
                with open(str(output_dir.joinpath(f"{vid_name}_stdout.log")), 'w', encoding="utf-8") as outfile:
                    outfile.write(ffmpeg_output)

            if ffmpeg_error:
                # TODO: Currently, appears all output is here; perhaps subprocess.PIPE?
                with open(str(output_dir.joinpath(f"{vid_name}_stderr.log")), 'w', encoding="utf-8") as outfile:
                    outfile.write(ffmpeg_error)

            if result.returncode != 0:
                error = 'Error Return Code with video %s: %s' % (vid_name, str(result.returncode))
                self.dataset.log(error)

            processed_videos += 1
            self.dataset.update_status(f"Extracted audio from {processed_videos} of {total_possible_videos} videos")
            self.dataset.update_progress(processed_videos / total_possible_videos)

        # Finish up
        warning = f"Extracted {written}/{total_possible_videos} audio files, check the logs for errors." \
            if written < total_possible_videos else None
        self.write_archive_and_finish(output_dir, num_items=processed_videos, warning=warning)
