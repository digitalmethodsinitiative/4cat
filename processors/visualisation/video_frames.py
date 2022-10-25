"""
Create frames of videos

This processor also requires ffmpeg to be installed in 4CAT's backend
https://ffmpeg.org/
"""
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
import shlex
from subprocess import Popen, PIPE

from videohash import VideoHash
from videohash.exceptions import FFmpegNotFound

from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.user_input import UserInput

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class VideoFrames(BasicProcessor):
	"""
	Video Hasher

	Converts videos into 64 bit hashes which can be used to identify near duplicate videos. The accuracy of these hashes
	can very greatly depending on the number of frames per second collected from each video.

	After creating an image collage from the collected video frames, the videohash library relies on two main aspects:
	Discrete Wavelet Transformation of the image (https://en.wikipedia.org/wiki/Discrete_wavelet_transform) and the
	dominant color. The collage being divided into 64 "images" or "pixels" and ultimately defined by those two aspects
	(one "image"/"pixel" per bit).

	Increasing the frames per second has proven necessary for short videos (if there are ultimately less than 64 frames,
	there will essentially be black frames that will be shared with every other video with less than 64 frames). It also
	seems necessary to collect the same frames per second for comparison between videos as variation in this will cause
	different frames to be collected per video (more testing needs to be done here). Additionally, short videos often
	do not have much differentiating information particularly if there is little difference between frames (i.e. no
	"scene" changes) and have lead to unwanted collision in tests.
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
			self.dataset.update_status("No videos to compare.", is_final=True)
			self.dataset.finish(0)
			return

		# Collect parameters
		frame_interval = self.parameters.get("frame_interval", 1)
		self.dataset.log('Frames per seconds: %f' % frame_interval)

		# Prepare staging area for videos and video tracking
		staging_area = self.dataset.get_staging_area()
		self.dataset.log('Staging directory location: %s' % staging_area)

		self.dataset.update_status("Extract all videos")
		# with zipfile.ZipFile(self.source_file, 'r') as zipped_file:
		# 	zipped_file.extractall(staging_area)
		directory = '/usr/src/app/test/'
		video_filenames = os.listdir(directory)
		self.dataset.log('Number of videos: %i\nFirst five:\n%s' % (len(video_filenames), ',\n'.join(video_filenames[:5])))

		total_possible_videos = self.source_dataset.num_rows - 1  # for the metadata file that is included in archives
		processed_videos = 0

		self.dataset.update_status("Creating video frames")
		for path in video_filenames:
			path = Path(directory).joinpath(path)
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while determining image wall order")

			if path.name == '.metadata.json':
				# Keep it and move on
				with open(path) as file:
					video_metadata = json.load(file)
				continue

			video_dir = staging_area.joinpath(path.stem)
			os.mkdir(video_dir)
			command = [
				'ffmpeg',
				"-i",
				str(path),
				"-s",
				"144x144",
				"-r",
				str(frame_interval),
				str(video_dir) + "/video_frame_%07d.jpeg",
			]

			command = f"ffmpeg -i {path} -s 144x144 -r {frame_interval} {video_dir}/video_frame_%07d.jpeg"
			try:
				result = subprocess.run(shlex.split(command), stdout=PIPE, stderr=PIPE)
				# process = Popen(command, stdout=PIPE, stderr=PIPE)
			except UnicodeDecodeError as e:
				# This seems to occur randomly and can be resolved by retrying
				error = 'Error with video %s (%s): Retrying...' % (str(path), str(e))
				self.dataset.log(error)
				try:
					result = subprocess.run(shlex.split(command), stdout=PIPE, stderr=PIPE)
					# process = Popen(command, stdout=PIPE, stderr=PIPE)
				except UnicodeDecodeError as e:
					error = 'Error repeated with video %s: %s' % (str(path), str(e))
					self.dataset.log(error)
					continue

			try:
				ffmpeg_output = result.stdout.decode("utf-8")
				ffmpeg_error = result.stderr.decode("utf-8")
			except UnicodeDecodeError as e:
				error = 'Error decoding results for video %s: %s' % (str(path), str(e))
				self.dataset.log(error)

			if result.returncode != 0:
				self.dataset.log("Ran command: %s" % ' '.join(shlex.split(command)))
				error = 'Error Return Code with video %s: %s' % (str(path), str(result.returncode))
				self.dataset.log(error)

			# output, error = process.communicate()

			# try:
			# 	ffmpeg_output = output.decode()
			# 	ffmpeg_error = error.decode()
			# except UnicodeDecodeError as e:
			# 	error = 'Error with video %s (%s): Retrying...' % (str(path), str(e))
			# 	self.dataset.log(error)

			# Save the output report
			if ffmpeg_output:
				with open(video_dir.joinpath('ffmpeg_output.log'), 'w') as outfile:
					outfile.write(ffmpeg_output)

			if ffmpeg_error:
				with open(video_dir.joinpath('ffmpeg_error.log'), 'w') as outfile:
					outfile.write(ffmpeg_error)

			processed_videos += 1
			self.dataset.update_status(
				"Created frames for %i of %i videos" % (processed_videos, total_possible_videos))
			self.dataset.update_progress(processed_videos / total_possible_videos)

		# Finish up
		from shutil import make_archive
		make_archive(self.dataset.get_results_path().with_suffix(''), "zip", staging_area)

		self.dataset.finish(processed_videos)
