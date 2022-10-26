"""
Create frames of videos

This processor also requires ffmpeg to be installed in 4CAT's backend
https://ffmpeg.org/
"""
import json
import os
import subprocess
import zipfile
from pathlib import Path
import shlex

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


	"""
	type = "video-frames"  # job type ID
	category = "Visual"  # category
	title = "Extract frames from videos"  # title displayed in UI
	description = "IN DEVELOPMENT: ffmpeg video frame test."  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI

	options = {
		"frame_interval": {
			"type": UserInput.OPTION_TEXT,
			"help": "Number of frames extracted per second to extract from video",
			"tooltip": "The default value is 1 frame per second. For 1 frame per 5 seconds pass 0.2 (1/5). For 5 fps pass 5. For short videos, more frames per second lead to less collision (unsimilar videos being marked as similar), but require more time (2 fps is double the time of 1 fps).",
			"coerce_type": float,
			"default": 1,
			"min": 0,
			"max": 5,
		},
	}

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow on tiktok-search only for dev
		"""
		return module.type == "video-downloader"

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

		# Prepare staging area for videos and video tracking
		staging_area = self.dataset.get_staging_area()
		self.dataset.log('Staging directory location: %s' % staging_area)

		self.dataset.update_status("Extract all videos")
		with zipfile.ZipFile(self.source_file, 'r') as zipped_file:
			zipped_file.extractall(staging_area)
		video_filenames = os.listdir(staging_area)

		# Output folder
		output_directory = staging_area.joinpath('frames')
		output_directory.mkdir(exist_ok=True)

		total_possible_videos = self.source_dataset.num_rows - 1  # for the metadata file that is included in archives
		self.dataset.log(
			'Number of videos: %i\nFirst five:\n%s' % (total_possible_videos, ',\n'.join(video_filenames[:5])))
		processed_videos = 0

		self.dataset.update_status("Extracting video frames")
		for video in video_filenames:
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while determining image wall order")

			path = staging_area.joinpath(video)

			# Check for metadata JSON
			if video == '.metadata.json':
				# Keep it and move on
				with open(path) as file:
					video_metadata = json.load(file)
				continue

			vid_name = path.stem
			video_dir = output_directory.joinpath(vid_name)
			video_dir.mkdir(exist_ok=True)

			command = f"ffmpeg -i {path} -s 144x144 -r {frame_interval} {video_dir}/video_frame_%07d.jpeg"

			result = subprocess.run(shlex.split(command), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

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
		from shutil import make_archive
		make_archive(self.dataset.get_results_path().with_suffix(''), "zip", output_directory)

		self.dataset.finish(processed_videos)
