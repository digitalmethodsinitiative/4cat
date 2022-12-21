"""
Create frames of videos

This processor also requires ffmpeg to be installed in 4CAT's backend
https://ffmpeg.org/
"""
import shutil
import subprocess
import shlex

import common.config_manager as config

from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.user_input import UserInput

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class VideoFrames(BasicProcessor):
	"""
	Video Frame Extracter

	Uses ffmpeg to extract a certain number of frames per second at different sizes and saves them in an archive.
	"""
	type = "video-frames"  # job type ID
	category = "Visual"  # category
	title = "Extract frames from videos"  # title displayed in UI
	description = "Extract frames from videos"  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI

	options = {
		"frame_interval": {
			"type": UserInput.OPTION_TEXT,
			"help": "Number of frames extracted per second to extract from video",
			"tooltip": "The default value is 1 frame per second. For 1 frame per 5 seconds pass 0.2 (1/5). For 5 fps "
					   "pass 5, and so on.",
			"coerce_type": float,
			"default": 1,
			"min": 0,
			"max": 5,
		},
		"frame_size": {
			"type": UserInput.OPTION_CHOICE,
			"default": "medium",
			"options": {
				"no_modify": "Do not modify",
				"144x144": "Tiny (144x144)",
				"432x432": "Medium (432x432)",
				"1026x1026": "Large (1026x1026)",
			},
			"help": "Size of extracted frames"
		},
	}

	followups = ["video-timelines"]

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow on tiktok-search only for dev
		"""
		return module.type in ["video-downloader", "video-downloader-plus"] and \
			   config.get("video_downloader.ffmpeg-path") and \
			   shutil.which(config.get("video_downloader.ffmpeg-path"))

	def process(self):
		"""
		This takes a zipped set of videos, uses https://pypi.org/project/videohash/ and https://ffmpeg.org/ to collect
		frames from the videos at intervals and create image collages to hashes for comparison of videos.
		"""
		# Check processor able to run
		if self.source_dataset.num_rows == 0:
			self.dataset.update_status("No videos from which to extract frames.", is_final=True)
			self.dataset.finish(0)
			return

		# Collect parameters
		frame_interval = self.parameters.get("frame_interval", 1.0)
		frame_size = self.parameters.get("frame_size", "no_modify")

		# Prepare staging area for videos and video tracking
		staging_area = self.dataset.get_staging_area()
		self.dataset.log('Staging directory location: %s' % staging_area)

		# Output folder
		output_directory = staging_area.joinpath('frames')
		output_directory.mkdir(exist_ok=True)

		total_possible_videos = self.source_dataset.num_rows - 1  # for the metadata file that is included in archives
		processed_videos = 0

		self.dataset.update_status("Extracting video frames")
		for path in self.iterate_archive_contents(self.source_file, staging_area):
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while determining image wall order")

			# Check for 4CAT's metadata JSON and copy it
			if path.name == '.metadata.json':
				shutil.copy(path, output_directory)
				continue

			vid_name = path.stem
			video_dir = output_directory.joinpath(vid_name)
			video_dir.mkdir(exist_ok=True)

			command = [
				shutil.which(config.get("video_downloader.ffmpeg-path")),
				"-i", shlex.quote(str(path)),
				"-r", str(frame_interval),
			]
			if frame_size != 'no_modify':
				command += ['-s', shlex.quote(frame_size)]
			command += [shlex.quote(str(video_dir) + "/video_frame_%07d.jpeg")]

			result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

			# Capture logs
			ffmpeg_output = result.stdout.decode("utf-8")
			ffmpeg_error = result.stderr.decode("utf-8")

			if ffmpeg_output:
				with open(video_dir.joinpath('ffmpeg_output.log'), 'w') as outfile:
					outfile.write(ffmpeg_output)

			if ffmpeg_error:
				with open(video_dir.joinpath('ffmpeg_error.log'), 'w') as outfile:
					outfile.write(ffmpeg_error)

			if result.returncode != 0:
				error = 'Error Return Code with video %s: %s' % (vid_name, str(result.returncode))
				self.dataset.log(error)

			processed_videos += 1
			self.dataset.update_status(
				"Created frames for %i of %i videos" % (processed_videos, total_possible_videos))
			self.dataset.update_progress(processed_videos / total_possible_videos)

		# Finish up
		# We've created a directory and folder structure here as opposed to a single folder with single files as
		# expected by self.write_archive_and_finish() so we use make_archive instead
		from shutil import make_archive
		make_archive(self.dataset.get_results_path().with_suffix(''), "zip", output_directory)

		# Remove staging area
		shutil.rmtree(staging_area)

		self.dataset.finish(processed_videos)
