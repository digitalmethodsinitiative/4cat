"""
Detect scenes in videos
"""
import shutil
import oslex
import json
import os
import re

from scenedetect import open_video, SceneManager, VideoOpenFailure, FrameTimecode

from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException, ProcessorException
from common.lib.user_input import UserInput

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"

class SceneDetectionException(ProcessorException):
	"""
	Exception raised when a video cannot be opened or analysed
	"""
	pass


class VideoSceneDetector(BasicProcessor):
	"""
	Video Scene Detector

	Uses the content detectors provided by PySceneDetect to detect scenes in videos and returns a csv listing their
	start and end times.
	"""
	type = "video-scene-detector"  # job type ID
	category = "Visual"  # category
	title = "Detect scenes in video"  # title displayed in UI
	description = "Detect distinct 'scenes' in videos based on various parameters (e.g. change in color and " \
				  "intensity or cuts and fades to black) and extract the scene metadata."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	followups = ["video-scene-frames", "video-timelines"]

	references = [
		"[PySceneDetect](https://github.com/Breakthrough/PySceneDetect)",
		"[Detection Algorithms](https://scenedetect.com/projects/Manual/en/latest/api/detectors.html)",
		"ffmpeg's scene/shot detection algorithm is based on [ShotDetect](https://github.com/johmathe/Shotdetect) (see [here](https://github.com/FFmpeg/FFmpeg/commit/7286814))"
	]

	@classmethod
	def get_options(cls, parent_dataset=None, config=None) -> dict:
		"""
		Get processor options

		:param parent_dataset DataSet:  An object representing the dataset that
			the processor would be or was run on. Can be used, in conjunction with
			config, to show some options only to privileged users.
		:param config ConfigManager|None config:  Configuration reader (context-aware)
		:return dict:   Options for this processor
		"""

		options = {
			"detector_type": {
				"help": "Type of detection algorithm",
				"type": UserInput.OPTION_CHOICE,
				"default": "ffmpeg_select",
				"tooltip": "See the processor's reference on Detection Algorithms.",
				"options": {
					"ffmpeg_select": "ffmpeg threshold filter",
					"content_detector": "PySceneDetect ContentDetector",
					"adaptive_detector": "PySceneDetect AdaptiveDetector",
					"threshold_detector": "PySceneDetect ThresholdDetector",
				},
			},
			"ffmpeg-info": {
				"type": UserInput.OPTION_INFO,
				"help": "A simple and fast algorithm that calculates a difference score between frames based on their "
						"colour difference. More pixels with different colours is a higher difference score. A score "
						"higher than 0.3 often has a reasonable chance of indicating a new shot/scene.",
				"requires": "detector_type==ffmpeg_select"
			},
			"cd-info": {
				"type": UserInput.OPTION_INFO,
				"help": "Frame by frame detection using color and intensity change; mainly detects fast cuts",
				"requires": "detector_type==content_detector"
			},
			"ad-info": {
				"type": UserInput.OPTION_INFO,
				"help": "ContentDetector with rolling average of frame changes to  mitigate fast camera motion falsely "
						"detected as scene changes",
				"requires": "detector_type==adaptive_detector"
			},
			"td-info": {
				"type": UserInput.OPTION_INFO,
				"help": "Compares multiple frame groups for both fast cuts and slow PySceneDetect fades, but only uses "
						"pixel intensity (i.e. only detects hard cut or fade to black)",
				"requires": "detector_type==threshold_detector"
			},
			"ffmpeg_scene_threshold": {
				"help": "Detection threshold",
				"type": UserInput.OPTION_TEXT,
				"default": 0.3,
				"coerce_type": float,
				"min": 0,
				"max": 1,
				"tooltip": "Scene detection threshold between 0 and 1. The higher this is, the more change is needed "
						   "to consider a new scene to have started. See the ffmpeg documentation (in processor "
						   "references) for more details.",
				"requires": "detector_type==ffmpeg_select"
			},
			"min_scene_len": {
				"help": "Minimum length of scene in frames",
				"type": UserInput.OPTION_TEXT,
				"tooltip": "Note: this can vary length of scene in time based on video framerate (24fps in many cases, "
						   "but not always)",
				"coerce_type": int,
				"default": 15,
				"min": 1
			},
			"luma_only": {
				"type": UserInput.OPTION_TOGGLE,
				"help": "Only consider changes in luminance/brightness of video",
				"default": False,
				"tooltip": "Applies to ContentDetector and AdaptiveDetector. If enabled, only considers changes in the "
						"luminance channel of the video. If disabled, also consider changes in hue and saturation.",
				"requires": ["detector_type!=ffmpeg_select", "detector_type!=threshold_detector"]
			},
			"cd_threshold": {
				"type": UserInput.OPTION_TEXT,
				"help": "Pixel intensity delta threshold",
				"tooltip": "Only applies when using the ContentDetector algorithm. Average change in pixel intensity that "
						"must be exceeded to be detected as a scene change.",
				"coerce_type": float,
				"default": 27.0,
				"min": 0,
				"max": 5,
				"requires": "detector_type==content_detector"
			},
			"ad_adaptive_threshold": {
				"type": UserInput.OPTION_TEXT,
				"help": "Change threshold",
				"tooltip": "Only applies when using the AdaptiveDetector algorithm. Value (float) that the calculated "
						"frame change must exceed to be detected as a scene change.",
				"coerce_type": float,
				"default": 3.0,
				"min": 0,
				"requires": "detector_type==adaptive_detector"
			},
			"ad_min_delta_hsv": {
				"type": UserInput.OPTION_TEXT,
				"help": "Colour change threshold",
				"tooltip": "Only applies when using the AdaptiveDetector algorithm. Value (float) that the frame colour "
						"difference (in HSV) must exceed to be detected as a scene change.",
				"coerce_type": float,
				"default": 15.0,
				"min": 0,
				"requires": "detector_type==adaptive_detector"
			},
			"ad_window_width": {
				"type": UserInput.OPTION_TEXT,
				"help": "Frame window size",
				"tooltip": "Only applies when using the AdaptiveDetector algorithm. Number of frames before and after each "
						"frame to average together in order to detect deviations from the mean.",
				"coerce_type": int,
				"default": 2,
				"min": 1,
				"requires": "detector_type==adaptive_detector"
			},
			"td_threshold": {
				"type": UserInput.OPTION_TEXT,
				"help": "Brightness threshold",
				"tooltip": "Only applies when using the ThresholdDetector algorithm. 8-bit intensity value that each pixel "
						"value (R, G, and B) must be <= to in order to be detected as a fade in/out",
				"coerce_type": float,
				"default": 12.0,
				"min": 0,
				"requires": "detector_type==threshold_detector"
			},
			"td_fade_bias": {
				"type": UserInput.OPTION_TEXT,
				"help": "Fade eagerness",
				"tooltip": "Only applies when using the ThresholdDetector algorithm. Float between -1.0 and +1.0 "
						"representing the percentage of timecode skew for the start of a scene. -1.0 causing a cut at "
						"the fade-to-black, 0.0 in the middle, and +1.0 causing the cut to be  right at the position "
						"where the threshold is passed",
				"coerce_type": float,
				"default": 0.0,
				"min": -1.0,
				"max": 1.0,
				"requires": "detector_type==threshold_detector"
			},
			"save_annotations": {
				"type": UserInput.OPTION_ANNOTATION,
				"label": "scene data",
				"hidden_in_explorer": True,
				"tooltip": "Add amount of scenes per video to top dataset",
				"default": False
			}
		}
		# only offer ffmpeg option if we actually have ffmpeg
		ffmpeg_path = shutil.which(config.get("video-downloader.ffmpeg_path"))
		if not ffmpeg_path or not os.path.exists(ffmpeg_path):
			del options["detector_type"]["options"]["ffmpeg_select"]
			options["detector_type"]["default"] = list(options["detector_type"]["options"].values())[0]

		return options

	@classmethod
	def is_compatible_with(cls, module=None, config=None):
		"""
		Allow on videos
		"""
		return module.get_media_type() == "video" or module.type.startswith("video-downloader")

	def process(self):
		"""
		This takes a zipped set of videos, uses https://github.com/Breakthrough/PySceneDetect to detect scene breaks in
		videos
		"""
		save_annotations = self.parameters.get("save_annotations", False)

		self.dataset.update_status("Detecting video scenes")
		skipped = 0
		processed_videos = 0
		video_metadata = None
		collected_scenes = {}
		for original_video in self.source_dataset.iterate_items(self, immediately_delete=False):
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while detecting video scenes")

			# Check for 4CAT's metadata JSON and copy it
			if original_video.file.name == ".metadata.json":
				# Keep it and move on
				with open(original_video.file) as file:
					video_metadata = json.load(file)
				continue
			elif original_video.file.name == "video_archive":
				# yt-dlp file
				continue

			detector = self.get_scenes_scenedetect if self.parameters.get("detector_type") != "ffmpeg_select" else self.get_scenes_ffmpeg

			self.dataset.update_progress(processed_videos / self.source_dataset.num_rows)
			self.dataset.update_status(f"Detecting scenes in video {processed_videos+1:,} of {self.source_dataset.num_rows:,}")
			try:
				scenes = detector(original_video)
			except (VideoOpenFailure, SceneDetectionException) as e:
				self.dataset.update_status(f'Skipping video; unable to open or parse {original_video.file.name}: {e}')
				skipped += 1
				continue

			collected_scenes[original_video.file.name] = scenes

			processed_videos += 1

		# Finish up
		self.dataset.update_status("Format data for output file")
		num_posts = 0
		rows = []
		annotations = []
		if video_metadata is None:
			# Not good, but let's store the scenes and note the error
			self.dataset.log("No metadata file found")

			for filename, video_scenes in collected_scenes.items():
				for i, scene in enumerate(video_scenes):
					rows.append({**{
						'id': filename + '_scene_' + str(i),  # best if all datasets have unique identifier
						'filename': filename,
					}, **scene})
					num_posts += 1
		else:
			self.dataset.update_status("Saving video scene results")
			for url, video_data in video_metadata.items():
				if video_data.get('success'):
					files = video_data.get('files') if 'files' in video_data else [{"filename": video_data.get("filename"), "success":True}]
					for file in files:
						if not file.get("success") or file.get("filename") not in collected_scenes:
							continue
							
						# List types are not super fun for CSV
						if 'post_ids' in video_data:
							video_data['post_ids'] = ','.join(video_data['post_ids'])


						for i, scene in enumerate(collected_scenes[file.get('filename')]):
							rows.append({
								'id': file.get('filename') + '_scene_' + str(i+1),  # best if all datasets have unique identifier
								'url': url,
								"from_dataset": video_data.get("from_dataset"),
								**scene,
								"post_ids": ','.join(video_data.get("post_ids", [])),
							})
							num_posts += 1

							# Write amount of scenes for first scene detected
							if save_annotations and i == 0:
								item_ids = video_data.get("post_ids", [])
								item_ids = [item_ids] if isinstance(item_ids, str) else item_ids
								for item_id in item_ids:
									annotation = {
										"label": "scene_amount",
										"value": scene.get("num_scenes_detected", ""),
										"item_id": item_id
									}
									annotations.append(annotation)

		if save_annotations and annotations:
			self.save_annotations(annotations)

		if rows:
			self.dataset.update_status(f"Detected {num_posts:,} scenes in {processed_videos:,} videos")
			warning = None if not skipped else f"{skipped:,} videos were skipped"
			self.write_csv_items_and_finish(rows, warning=warning)
		else:
			return self.dataset.finish_with_error("No distinct scenes could be detected in the videos. The videos may "
												  "be too short for scenes to be detected.")

	def get_scenes_ffmpeg(self, original_video):
		"""
		Detect scenes using ffmpeg

		A quick if less sophisticated solution

		:param original_video:  Video file
		:return:
		"""
		threshold = self.parameters.get("ffmpeg_scene_threshold")

		ffmpeg_path = shutil.which(self.config.get("video-downloader.ffmpeg_path"))
		ffprobe_path = shutil.which("ffprobe".join(ffmpeg_path.rsplit("ffmpeg", 1)))

		# first get some video metadata
		probe_command = [ffprobe_path, "-v", "error", "-select_streams", "v:0", "-show_entries",
		                 "stream=avg_frame_rate,duration,nb_frames", "-of", "csv=p=0",
						 oslex.quote(str(original_video.file))]

		probe = self.run_interruptable_process(probe_command)
		if probe.stderr.decode("utf-8"):
			raise SceneDetectionException("Could not read video metadata with ffprobe. The video may be unreadable.")

		probe_output = probe.stdout.decode("utf-8")
		fps, duration, total_frames = probe_output.split(",")
		fps = float(fps.split("/")[0]) / float(fps.split("/")[1])
		duration = float(duration)
		total_frames = int(total_frames)
		length_timecode = FrameTimecode(duration, fps).get_timecode()

		command = [ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error"]
		command.extend(["-i", oslex.quote(str(original_video.file))])
		# select all frames with a diff to the previous frame of > 0
		# make sure to always select at least first and last frames
		# frames are 0-indexed, so the last frame is total_frames-1
		command.extend(["-vf",
                fr"select=(gte(scene\,0)+eq(n\,0)+eq(n\,{total_frames-1})),metadata=print:file='pipe\:1'",
                "-an", "-f", "null", os.devnull
		])

		result = self.run_interruptable_process(command)
		if not result.stdout:
			raise SceneDetectionException("ffmpeg did not return any results. The video may be unreadable")

		# parse ffmpeg output into a nice list of frame info dicts
		# some borrowing from https://github.com/slhck/scenecut-extractor/
		frame = {}
		frames = []
		for line in result.stdout.splitlines():
			line = line.decode("utf-8")
			if line.startswith("frame:"):
				info = re.match(
						r"frame:(?P<frame>\d+)\s+pts:(?P<pts>[\d\.]+)\s+pts_time:(?P<pts_time>[\d\.]+)",
						line,
				)
				matches = info.groupdict()
				frame = {
					"frame": int(matches["frame"]),
					"pts": float(matches["pts"]),
					"pts_time": float(matches["pts_time"])
				}
			elif line.startswith("lavfi.scene_score"):
				frame.update({
					"score": float(line.split("=")[1].strip()),
				})
				frames.append(frame)
				frame = {}

		if not frames:
			raise SceneDetectionException("No frames were processed by ffmpeg. The video may be unreadable.")

		# always include the very first and very last frames as keyframes
		# this means even in a video with no transitions that meet the
		# threshold, a single scene will be detected (i.e. the whole video)
		key_frames = [f for i, f in enumerate(frames) if f["score"] >= threshold or i in (0, len(frames) - 1)]
		scenes = []
		previous = None

		# consider each interval between key frames a 'scene'
		for key_frame in key_frames:
			if not previous:
				previous = key_frame
				continue

			# ignore key frame if within minimum scene length
			diff = key_frame["frame"] - previous["frame"]
			if diff < self.parameters.get("min_scene_len"):
				continue

			scenes.append({
				"start_frame": previous["frame"],
				"start_time": FrameTimecode(previous["pts_time"], fps).get_timecode(),
				"end_frame": key_frame["frame"],
				"end_time": FrameTimecode(key_frame["pts_time"], fps).get_timecode(),
				"scene_num": len(scenes) + 1,
				"scene_frames": diff,
				"scene_duration": FrameTimecode(key_frame["pts_time"] - previous["pts_time"], fps).get_timecode(),
				"num_scenes_detected": len(key_frames),
				"total_video_frames": total_frames,
				"total_video_duration": length_timecode
			})

			previous = key_frame

		return scenes


	def get_scenes_scenedetect(self, original_video):
		"""
		Detect scenes using PySceneDetect

		Use one of three detectors as configured in the parameters

		:param original_video:  Video to detect scenes in
		:return:
		"""
		# Get new scene detector
		scene_manager = self.get_new_scene_manager()

		# Open video
		video = open_video(str(original_video.file))

		total_frames = video.duration.frame_num
		total_duration = video.duration.get_timecode()

		# Run detector
		scene_manager.detect_scenes(video)
		scene_list = scene_manager.get_scene_list()

		# Collect scene information for mapping to metadata
		scenes = []
		if len(scene_list) == 0:
			# No scenes detected; record as one scene
			# TODO: any reason to make this optional?
			scenes.append({
				'start_frame': video.base_timecode.frame_num,
				'start_time': video.base_timecode.get_timecode(),
				'end_frame': total_frames,
				'end_time': total_duration,
				'scene_num': 1,
				"scene_frames": total_frames,
				"scene_duration": total_duration,
				'num_scenes_detected': 1,
				'total_video_frames': total_frames,
				'total_video_duration': total_duration,
			})

		for i, scene in enumerate(scene_list):
			scenes.append({
				'start_frame': scene[0].frame_num,
				'start_time': scene[0].get_timecode(),
				'end_frame': scene[1].frame_num,
				'end_time': scene[1].get_timecode(),
				'scene_num': i + 1,
				"scene_frames": (scene[1].frame_num - scene[0].frame_num),
				"scene_duration": (scene[1] - scene[0]).get_timecode(),
				'num_scenes_detected': len(scene_list),
				'total_video_frames': total_frames,
				'total_video_duration': total_duration,
			})

		# pyscenedetect puts the end of the last scene (i.e. the end of the
		# video in this case) as last frame num + 1
		# however, this frame number is technically incorrect, since e.g. if a
		# video has 2808 frames, this number would be 2808 - which implies it
		# is 1-indexed, but otherwise frames are 0-indexed
		# anyway, ffmpeg won't want to select frame 2808 later in that case, so
		# correct the number to a valid 0-indexed number
		while scenes[-1]["end_frame"] >= total_frames:
			scenes[-1]["end_frame"] -= 1

		return scenes

	def get_new_scene_manager(self):
		"""
		Helper function to collect a new SceneManager object

		A new SceneManager is needed for every video. If multiple videos are
		to be combined, one SceneManager could be used.
		"""
		scene_manager = SceneManager()
		if self.parameters.get("detector_type") == 'content_detector':
			from scenedetect.detectors import ContentDetector
			scene_manager.add_detector(
				ContentDetector(threshold=self.parameters.get("cd_threshold"),
								min_scene_len=self.parameters.get("min_scene_len"),
								luma_only=self.parameters.get("luma_only")))
		elif self.parameters.get("detector_type") == 'adaptive_detector':
			from scenedetect.detectors import AdaptiveDetector
			scene_manager.add_detector(
				AdaptiveDetector(adaptive_threshold=self.parameters.get("ad_adaptive_threshold"),
								 min_scene_len=self.parameters.get("min_scene_len"),
								 luma_only=self.parameters.get("luma_only"),
								 min_content_val=self.parameters.get("ad_min_delta_hsv"),
								 window_width=self.parameters.get("ad_window_width"), ))
		elif self.parameters.get("detector_type") == 'threshold_detector':
			from scenedetect.detectors import ThresholdDetector
			scene_manager.add_detector(
				ThresholdDetector(threshold=self.parameters.get("td_threshold"),
								  min_scene_len=self.parameters.get("min_scene_len"),
								  fade_bias=self.parameters.get("td_fade_bias"), ))
		else:
			raise ProcessorException('Scene detector type not available.')

		return scene_manager
