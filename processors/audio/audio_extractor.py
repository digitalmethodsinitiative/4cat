"""
Extract audio from video archive

This processor also requires ffmpeg to be installed in 4CAT's backend
https://ffmpeg.org/
"""
import shutil
import subprocess
import shlex

from common.config_manager import config

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
	description = "Extract audio from videos"  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI

	@classmethod
	def is_compatible_with(cls, module=None, user=None):
		"""
		Allow on tiktok-search only for dev
		"""
		return module.type.startswith("video-downloader") and \
			   config.get("video-downloader.ffmpeg_path", user=user) and \
			   shutil.which(config.get("video-downloader.ffmpeg_path"))

	@classmethod
	def get_options(cls, parent_dataset=None, user=None):
		"""
		Collect maximum number of audio files from configuration and update options accordingly
		"""
		options = {
			"amount": {
				"type": UserInput.OPTION_TEXT,
				"help": "Number of audio files to extract (0 will extract all)",
				"default": 10,
				"min": 0,
			}
		}

		return options

	def process(self):
		"""
		This takes a zipped set of videos and uses https://ffmpeg.org/ to collect audio into a zip archive
		"""
		# Check processor able to run
		if self.source_dataset.num_rows == 0:
			self.dataset.update_status("No videos from which to extract audio.", is_final=True)
			self.dataset.finish(0)
			return

		max_files = self.parameters.get("amount", 100)

		# Prepare staging areas for videos and video tracking
		staging_area = self.dataset.get_staging_area()
		output_dir = self.dataset.get_staging_area()

		total_possible_videos = max_files if max_files != 0 else self.source_dataset.num_rows - 1  # for the metadata file that is included in archives
		processed_videos = 0

		self.dataset.update_status("Extracting video audio")
		for path in self.iterate_archive_contents(self.source_file, staging_area):
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while determining image wall order")

			# Check for 4CAT's metadata JSON and copy it
			if path.name == '.metadata.json':
				shutil.copy(path, output_dir.joinpath(".video_metadata.json"))
				continue

			if max_files != 0 and processed_videos >= max_files:
				break

			vid_name = path.stem
			# ffmpeg -i video.mkv -map 0:a -acodec libmp3lame audio.mp4
			command = [
				shutil.which(config.get("video-downloader.ffmpeg_path")),
				"-i", shlex.quote(str(path)),
				"-ar", str(16000),
				shlex.quote(str(output_dir.joinpath(f"{vid_name}.wav")))
			]

			result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

			# Capture logs
			ffmpeg_output = result.stdout.decode("utf-8")
			ffmpeg_error = result.stderr.decode("utf-8")

			if ffmpeg_output:
				with open(str(output_dir.joinpath(f"{vid_name}_stdout.log")), 'w') as outfile:
					outfile.write(ffmpeg_output)

			if ffmpeg_error:
				# TODO: Currently, appears all output is here; perhaps subprocess.PIPE?
				with open(str(output_dir.joinpath(f"{vid_name}_stderr.log")), 'w') as outfile:
					outfile.write(ffmpeg_error)

			if result.returncode != 0:
				error = 'Error Return Code with video %s: %s' % (vid_name, str(result.returncode))
				self.dataset.log(error)

			processed_videos += 1
			self.dataset.update_status(
				"Extracted audio from %i of %i videos" % (processed_videos, total_possible_videos))
			self.dataset.update_progress(processed_videos / total_possible_videos)

		# Finish up
		self.write_archive_and_finish(output_dir, num_items=processed_videos)
