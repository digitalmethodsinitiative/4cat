"""
Detect scenes in videos
"""
import json
from scenedetect import open_video, SceneManager, VideoOpenFailure

from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException, ProcessorException
from common.lib.user_input import UserInput

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


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

	references = [
		"[PySceneDetect](https://github.com/Breakthrough/PySceneDetect)",
		"[Detection Algorithms](https://scenedetect.com/projects/Manual/en/latest/api/detectors.html)"
	]

	options = {
		"detector_type": {
			"help": "Type of detection algorithm",
			"type": UserInput.OPTION_CHOICE,
			"default": "adaptive_detector",
			"tooltip": "See the processor's reference on Detection Algorithms.",
			"options": {
				"content_detector": "ContentDetector: frame by frame detection using color and intensity change; "
									"mainly detects fast cuts",
				"adaptive_detector": "AdaptiveDetector: ContentDetector with rolling average of frame changes to "
									 "mitigate fast camera motion falsely detected as scene changes",
				"threshold_detector": "ThresholdDetector: compares multiple frame groups for both fast cuts and slow "
									  "fades, but only uses pixel intensity (i.e. only detects hard cut or fade to "
									  "black)",
			},
		},
		"min_scene_len": {
			"help": "Minimum length of scene in frames",
			"type": UserInput.OPTION_TEXT,
			"tooltip": "Note: this can vary length of scene in time based on video framerate (24fps in many cases, but "
					   "not always)",
			"coerce_type": int,
			"default": 15,
			"min": 1,
		},
		"luma_only": {
			"type": UserInput.OPTION_TOGGLE,
			"help": "Only consider changes in luminance/brightness of video",
			"default": False,
			"tooltip": "Applies to ContentDetector and AdaptiveDetector. If enabled, only considers changes in the "
					   "luminance channel of the video. If disabled, also consider changes in hue and saturation."
		},
		"cd_info": {
			"type": UserInput.OPTION_INFO,
			"help": "*Content Detector settings*"
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
		},
		"ad_info": {
			"type": UserInput.OPTION_INFO,
			"help": "*Adaptive Detector settings*"
		},
		"ad_adaptive_threshold": {
			"type": UserInput.OPTION_TEXT,
			"help": "Change threshold",
			"tooltip": "Only applies when using the AdaptiveDetector algorithm. Value (float) that the calculated "
					   "frame change must exceed to be detected as a scene change.",
			"coerce_type": float,
			"default": 3.0,
			"min": 0,
		},
		"ad_min_delta_hsv": {
			"type": UserInput.OPTION_TEXT,
			"help": "Colour change threshold",
			"tooltip": "Only applies when using the AdaptiveDetector algorithm. Value (float) that the frame colour "
					   "difference (in HSV) must exceed to be detected as a scene change.",
			"coerce_type": float,
			"default": 15.0,
			"min": 0,
		},
		"ad_window_width": {
			"type": UserInput.OPTION_TEXT,
			"help": "Frame window size",
			"tooltip": "Only applies when using the AdaptiveDetector algorithm. Number of frames before and after each "
					   "frame to average together in order to detect deviations from the mean.",
			"coerce_type": int,
			"default": 2,
			"min": 1,
		},
		"td_info": {
			"type": UserInput.OPTION_INFO,
			"help": "*Threshold Detector settings*"
		},
		"td_threshold": {
			"type": UserInput.OPTION_TEXT,
			"help": "Brightness threshold",
			"tooltip": "Only applies when using the ThresholdDetector algorithm. 8-bit intensity value that each pixel "
					   "value (R, G, and B) must be <= to in order to be detected as a fade in/out",
			"coerce_type": float,
			"default": 12.0,
			"min": 0,
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
		},
	}

	followups = ["video-scene-frames", "video-timelines"]

	@classmethod
	def is_compatible_with(cls, module=None, user=None):
		"""
		Allow on videos
		"""
		return module.type.startswith("video-downloader")

	def process(self):
		"""
		This takes a zipped set of videos, uses https://github.com/Breakthrough/PySceneDetect to detect scene breaks in
		videos
		"""
		# Check processor able to run
		if self.source_dataset.num_rows <= 1:
			# 1 because there is always a metadata file
			self.dataset.update_status("No videos from which to extract scenes.", is_final=True)
			self.dataset.finish(0)
			return

		self.dataset.update_status("Detecting video scenes")
		total_possible_videos = self.source_dataset.num_rows - 1  # for the metadata file that is included in archives
		processed_videos = 0
		video_metadata = None
		collected_scenes = {}
		for path in self.iterate_archive_contents(self.source_file):
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while detecting video scenes")

			# Check for 4CAT's metadata JSON and copy it
			if path.name == ".metadata.json":
				# Keep it and move on
				with open(path) as file:
					video_metadata = json.load(file)
				continue
			elif path.name == "video_archive":
				# yt-dlp file
				continue

			# Get new scene detector
			scene_manager = self.get_new_scene_manager()

			# Open video
			try:
				video = open_video(str(path))
			except VideoOpenFailure as e:
				self.dataset.update_status(f'Skipping video; Unable to open {str(path.name)}: {str(e)}')
				continue
			total_frames = video.duration.get_frames()
			total_duration = video.duration.get_timecode()

			# Run detector
			scene_manager.detect_scenes(video)
			scene_list = scene_manager.get_scene_list()
			num_scenes_detected = len(scene_list)

			# Collect scene information for mapping to metadata
			collected_scenes[path.name] = []
			if num_scenes_detected == 0:
				# No scenes detected; record as one scene
				# TODO: any reason to make this optional?
				collected_scenes[path.name].append({
					'start_frame': video.base_timecode.get_frames(),
					'start_time': video.base_timecode.get_timecode(),
					'start_fps': video.base_timecode.get_framerate(),
					'end_frame': total_frames,
					'end_time': total_duration,
					'end_fps': video.duration.get_framerate(),
					'scene_num': 1,
					'num_scenes_detected': 1,
					'total_video_frames': total_frames,
					'total_video_duration': total_duration,
				})

			for i, scene in enumerate(scene_list):
				collected_scenes[path.name].append({
					'start_frame': scene[0].get_frames(),
					'start_time': scene[0].get_timecode(),
					'start_fps': scene[0].get_framerate(),
					'end_frame': scene[1].get_frames(),
					'end_time': scene[1].get_timecode(),
					'end_fps': scene[1].get_framerate(),
					'scene_num': i+1,
					'num_scenes_detected': num_scenes_detected,
					'total_video_frames': total_frames,
					'total_video_duration': total_duration,
				})

			processed_videos += 1
			self.dataset.update_status(
				"Detected scenes for %i of %i videos" % (processed_videos, total_possible_videos))
			self.dataset.update_progress(processed_videos / total_possible_videos)

		# Finish up
		self.dataset.update_status("Format data for output file")
		num_posts = 0
		rows = []
		if video_metadata is None:
			# Not good, but let's store the scenes and note the error
			self.dataset.update_status("Error connecting video scenes to original dataset", is_final=True)

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
						if not file.get("success"):
							continue
						# List types are not super fun for CSV
						if 'post_ids' in video_data:
							video_data['post_ids'] = ','.join([str(i) for i in video_data['post_ids']])

						for i, scene in enumerate(collected_scenes[file.get('filename')]):
							rows.append({
								'id': file.get('filename') + '_scene_' + str(i+1),  # best if all datasets have unique identifier
								'url': url,
								"from_dataset": video_data.get("from_dataset"),
								**scene,
								"post_ids": ','.join(video_data.get("post_ids", [])),
							})
							num_posts += 1

		if rows:
			self.dataset.update_status(
				'Detected %i scenes in %i videos' % (num_posts, processed_videos))
			self.write_csv_items_and_finish(rows)
		else:
			return self.dataset.finish_with_error("No distinct scenes could be detected in the videos. The videos may "
												  "be too short for scenes to be detected.")

	def get_new_scene_manager(self):
		"""
		Helper function to collect a new SceneManager object based on provided parameters. A new SceneManager is needed
		for every video. If multiple videos are to be combined, one SceneManager could be used.
		"""
		scene_manager = SceneManager()
		if self.parameters.get("detector_type") == 'contenct_detector':
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
								 min_delta_hsv=self.parameters.get("ad_min_delta_hsv"),
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
