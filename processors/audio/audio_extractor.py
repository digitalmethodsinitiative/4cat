"""
Extract audio from video archive

This processor also requires ffmpeg to be installed in 4CAT's backend
https://ffmpeg.org/
"""
import shutil
import zipfile
from pathlib import Path
import oslex

from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException, MetadataException

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
    media_type = "audio"

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

        # Estimate how many actual video files we will attempt, excluding archive metadata.
        total_possible_videos = self.source_dataset.num_rows
        source_archive = self.source_dataset.get_results_path()
        if source_archive.exists() and source_archive.suffix.lower() == ".zip":
            with zipfile.ZipFile(source_archive, "r") as archive_file:
                total_possible_videos = sum(
                    1
                    for archived_file in archive_file.infolist()
                    if not archived_file.is_dir() and Path(archived_file.filename).name != ".metadata.json"
                )

        if max_files != 0:
            total_possible_videos = min(total_possible_videos, max_files)

        # Read the source video archive's metadata so each extracted audio
        # file can carry its video's provenance (source posts, URL).
        try:
            source_metadata = self.source_dataset.read_media_metadata()
        except (FileNotFoundError, MetadataException):
            source_metadata = None

        # Build our own metadata describing the audio files we produce,
        # rather than passing the (video-keyed) source metadata through.
        metadata = self.dataset.new_media_metadata(
            processor_type=self.type,
            from_dataset=(source_metadata.from_dataset if source_metadata else self.source_dataset.key),
        )

        processed_videos = 0
        written = 0

        self.dataset.update_status("Extracting video audio")
        for item in self.source_dataset.iterate_items(processor=self, get_annotations=False):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while determining image wall order")

            # the source archive's metadata describes videos; we write our
            # own (audio-keyed) metadata below, so skip the original
            if item.file.name == '.metadata.json':
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

            # Count attempted conversions separately from successful outputs.
            processed_videos += 1

            # Capture logs
            ffmpeg_output = result.stdout.decode("utf-8")
            ffmpeg_error = result.stderr.decode("utf-8")

            audio_filename = f"{vid_name}.wav"
            audio_file = output_dir.joinpath(audio_filename)

            # carry the source video's provenance onto the extracted audio
            video_item = source_metadata.get_entry(item.file.name) if source_metadata else None
            post_ids = video_item.get("post_ids", []) if video_item else []
            source_url = video_item.get("url") if video_item else None
            extra = dict(video_item.get("extra") or {}) if video_item else {}

            if audio_file.exists():
                written += 1
                metadata.add_item(audio_filename, post_ids=post_ids, url=source_url,
                                  extra=extra, replace=True)
            else:
                metadata.add_failure(post_ids=post_ids, reason="extraction_failed",
                                     reason_description=f"ffmpeg exited with code {result.returncode}",
                                     url=source_url)

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

            self.dataset.update_status(f"Extracted audio from {written} of {processed_videos} attempted videos")
            self.dataset.update_progress(min(1, processed_videos / max(total_possible_videos, 1)))

        # Write our own metadata describing the extracted audio files (and
        # any extraction failures), keyed by audio filename.
        metadata.write(output_dir)

        # Finish up
        warning = f"Extracted {written}/{processed_videos} audio files, check the logs for errors." \
            if written < processed_videos else None
        self.write_archive_and_finish(output_dir, num_items=written, warning=warning)
