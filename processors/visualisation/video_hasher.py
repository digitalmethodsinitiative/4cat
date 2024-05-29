"""
Hashes videos so they can be compared to others.

This processor also requires ffmpeg to be installed in 4CAT's backend
https://ffmpeg.org/
"""
import csv
import json
import shutil
import zipfile

import networkx as nx
import numpy as np
from videohash import VideoHash
from videohash.exceptions import FFmpegNotFound, FFmpegFailedToExtractFrames

from backend.lib.processor import BasicProcessor
from backend.lib.preset import ProcessorPreset
from common.lib.exceptions import ProcessorInterruptedException, ProcessorException
from common.lib.user_input import UserInput
from common.config_manager import config

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class VideoHasherPreset(ProcessorPreset):
    """
    Run processor pipeline to create video hashes
    """
    type = "preset-video-hashes"  # job type ID
    category = "Visual"  # category. 'Combined processors' are always listed first in the UI.
    title = "Create Video hashes to identify near duplicate videos"  # title displayed in UI
    description = "Creates video hashes (64 bits/identifiers) to identify near duplicate videos in a dataset based on hash similarity. Uses video only (no audio; see references). This process can take a long time depending on video length, amount, and frames per second."
    extension = "csv"

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        return {
			"frame_interval": {
				"type": UserInput.OPTION_TEXT,
				"help": "Number of frames extracted per second to extract from video",
				"tooltip": "The default value is 1 frame per second. For 1 frame per 5 seconds pass 0.2 (1/5). For 5 fps pass 5. For short videos, more frames per second lead to less collision when creating hashes (unsimilar videos being marked as similar), but require more time (2 fps is double the time of 1 fps).",
				"coerce_type": float,
				"default": 1,
				"min": 0,
				"max": 5,
			},
			"percent": {
				"type": UserInput.OPTION_TEXT,
				"help": "Percent similar for video hash network",
				"tooltip": "A network edge is created between two videos if the hashes representing the collage of frames are at least this percent similar.",
				"default": 95,
				"min": 0,
				"max": 100
			}
		}

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Determine compatibility

        Compatible with downloaded videos, and not really anything else!
        Additionally ffmpeg needs to be available.

        :param str module:  Module ID to determine compatibility with
        :return bool:
        """
        return module.type.startswith("video-downloader") and \
               config.get("video-downloader.ffmpeg_path", user=user) and \
               shutil.which(config.get("video-downloader.ffmpeg_path"))

    def get_processor_pipeline(self):
        """
        This queues a series of post-processors to visualise videos.
        """

        pipeline = [
            # first, create colleges (and hashes) with the default settings
            {
                "type": "video-hasher-1",
				"parameters": {
					"frame_interval": self.parameters.get("frame_interval", 1),
				}
            },
			# then create hash similarity network
			{
				"type": "video-hash-network",
				"parameters": {
					"percent": self.parameters.get("percent", 90),
				}
			},
        ]

        return pipeline


class VideoHasher(BasicProcessor):
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
	type = "video-hasher-1"  # job type ID
	category = "Visual"  # category
	title = "Create Video collages"  # title displayed in UI
	description = "Creates collages from video frames. Can be used to create video hashes to detect similar videos."  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI

	options = {
		"frame_interval": {
			"type": UserInput.OPTION_TEXT,
			"help": "Number of frames extracted per second to extract from video",
			"tooltip": "The default value is 1 frame per second. For 1 frame per 5 seconds pass 0.2 (1/5). For 5 fps pass 5. For short videos, more frames per second lead to less collision when creating hashes (unsimilar videos being marked as similar), but require more time (2 fps is double the time of 1 fps).",
			"coerce_type": float,
			"default": 1,
			"min": 0,
			"max": 5,
		},
	}

	@classmethod
	def is_compatible_with(cls, module=None, user=None):
		"""
		Allow on videos only
		"""
		return module.type.startswith("video-downloader")

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

		video_hashes = {}
		video_metadata = None
		total_possible_videos = self.source_dataset.num_rows - 1  # for the metadata file that is included in archives
		processed_videos = 0

		self.dataset.update_status("Creating video hashes")
		for path in self.iterate_archive_contents(self.source_file, staging_area):
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while creating video hashes")

			if path.name == '.metadata.json':
				# Keep it and move on
				with open(path) as file:
					video_metadata = json.load(file)
				continue
			elif path.name == "video_archive":
				# yt-dlp file
				continue

			try:
				videohash = VideoHash(path=str(path), storage_path=str(staging_area), frame_interval=frame_interval, do_not_copy=True)
			except FFmpegNotFound:
				self.log.error('ffmpeg must be installed for video_hash.py processor to be used.')
				self.dataset.update_status("FFmpeg software not found. Please contact 4CAT maintainers.", is_final=True)
				self.dataset.finish(0)
				return
			except FileNotFoundError as e:
				self.dataset.update_status(f"Unable to find file {str(path)}")
				continue
			except FFmpegFailedToExtractFrames as e:
				self.dataset.update_status(f"Unable to extract frame for {str(path)}: {e}")
				continue

			video_hashes[path.name] = {'videohash': videohash}

			shutil.copy(videohash.collage_path, staging_area.joinpath(path.stem + '.jpg'))
			video_hashes[path.name]['video_collage_filename'] = path.stem + '.jpg'

			processed_videos += 1
			self.dataset.update_status(
				"Created %i/%i video hashes" % (processed_videos, total_possible_videos))
			self.dataset.update_progress(processed_videos / total_possible_videos)
			videohash.delete_storage_path()

		# Write hash file
		# This file is held here and then copied as its own dataset via VideoHasherTwo
		num_posts = 0
		rows = []
		if video_metadata is None:
			# Not good, but let's store the video_hashes and note the error
			self.dataset.update_status("Error connecting video hashes to original dataset", is_final=True)

			for filename, data in video_hashes.items():
				video_hash = data.get('videohash')
				rows.append({
					'id': filename,  # best if all datasets have unique identifier
					'filename': filename,
					'video_hash': video_hash.hash,
					'video_duration': video_hash.video_duration,
					'video_collage_filename': data.get('video_collage_filename'),
				})
				num_posts += 1
		else:
			self.dataset.update_status("Saving video hash results")
			for url, data in video_metadata.items():
				if not data.get("success"):
					continue
				if "files" in data:
					files = data.get('files')
				elif "filename" in data:
					files = [{"filename": data.get("filename"), "success": True}]
				else:
					self.dataset.log(f"Metadata Error: {url} with {data}")
					continue

				for file in files:
					if not file.get("success"):
						continue
					if file.get('filename') not in video_hashes:
						self.dataset.log(f"Metadata Error: {file.get('filename')} with {url} - {data}")
						continue
					video_hash = video_hashes[file.get('filename')].get('videohash')
					rows.append({
						'id': file.get('filename'),  # best if all datasets have unique identifier
						'url': url,
						"from_dataset": data.get("from_dataset"),
						'video_hash': video_hash.hash,
						'video_duration': video_hash.video_duration,
						'video_count': len(data.get('post_ids', [])),
						"post_ids": ','.join([str(post_id) for post_id in data.get("post_ids", [])]),
						'video_collage_filename': video_hashes[file.get('filename')].get('video_collage_filename'),
					})
					num_posts += 1

		writer = None
		with staging_area.joinpath("video_hashes.csv").open("w", encoding="utf-8", newline="") as outfile:
			for row in rows:
				if not writer:
					writer = csv.DictWriter(outfile, fieldnames=row.keys())
					writer.writeheader()
				writer.writerow(row)
				num_posts += 1

		# Finish up
		self.dataset.update_status(f'Created {num_posts} video hashes and stored video collages')
		self.write_archive_and_finish(staging_area)

class VideoHashNetwork(BasicProcessor):
	"""
	Video Hasher Network

	This creates a network graph of the video hashes similarity
	"""
	type = "video-hash-network"  # job type ID
	category = "Visual"  # category
	title = "Create Video hashes network"  # title displayed in UI
	description = "Creates hashes network to identify duplicate or similar videos."  # description displayed in UI
	extension = "gexf"  # extension of result file, used internally and in UI

	references = [
		"[Video Hash](https://github.com/akamhy/videohash#readme)",
	]

	@classmethod
	def get_options(cls, parent_dataset=None, user=None):
		return {"percent": {
			"type": UserInput.OPTION_TEXT,
			"help": "Percent similar",
			"default": 90,
			"min": 0,
			"max": 100
		}}

	@classmethod
	def is_compatible_with(cls, module=None, user=None):
		"""
		Allow on video hasher
		"""
		return module.type in ["video-hasher-1"]

	def process(self):
		"""

		"""
		# Extract hash file from archive
		with zipfile.ZipFile(self.source_file, "r") as archive_file:
			archive_contents = sorted(archive_file.namelist())

			if "video_hashes.csv" not in archive_contents:
				self.dataset.update_status("Unable to obtain hashes from video colleges.", is_final=True)
				self.dataset.finish(0)
				return

			# Prepare staging area for videos and video tracking
			staging_area = self.dataset.get_staging_area()
			self.dataset.log('Staging directory location: %s' % staging_area)
			# Extract file
			archive_file.extract("video_hashes.csv", staging_area)

		percent_similar = self.parameters.get("percent", 90) / 100
		network = nx.Graph()

		# Calculate similarities
		self.dataset.update_status(f"Collecting video hashes for {percent_similar * 100}% similar network")
		hashes = []
		identifiers = []
		bit_length = None
		with open(staging_area.joinpath("video_hashes.csv"), "r", encoding="utf-8", newline="") as infile:
			reader = csv.DictReader(infile)
			for row in reader:
				video_hash = [int(bit) for bit in row.get('video_hash')[2:]]
				video_id = row.get('id')

				# Network
				network.add_node(video_id)

				hashes.append(np.array(video_hash))
				identifiers.append(video_id)

				if bit_length is None:
					bit_length = len(video_hash)

		self.dataset.update_status(f"Calculating video hash similarities {percent_similar * 100}% similar")
		hashes = np.array(hashes)
		comparisons = 0
		expected_comparisons = np.math.comb(len(hashes), 2)
		for i, current_hash in enumerate(hashes):
			# Remove this hash from hashes (as previous calculations have already occured and it is unnecessary to
			# compare a hash to itself)
			hashes = hashes[1:]

			# Compare current hash
			xor_result = np.bitwise_xor(current_hash, hashes)

			# Add comparisons to network
			for j, xor_comparison in enumerate(xor_result):
				id1 = identifiers[i]
				# Node 2 is this iteration plus comparison number PLUS one as the first hash of this set has been
				# removed (e.g., very first ID2 is 0+0+1)
				id2 = identifiers[i + j + 1]

				# Check if edge exists (it shouldn't!)
				edge = (id1, id2)
				if edge in network.edges():
					raise ProcessorException('Error in processing hash similarities')

				# Check if xor_comparison is less than requested similarity
				# xor compares each bit and returns 0 if a bit is the same and 1 if different
				edge_percent_similar = 1 - (xor_comparison.sum() / bit_length)
				if edge_percent_similar > percent_similar:
					network.add_edge(id1, id2, weight=edge_percent_similar)

				comparisons += 1
				if comparisons % 50000 == 0:
					self.dataset.update_status(
						"Calculated %i of %i hash similarities" % (comparisons, expected_comparisons))
					self.dataset.update_progress(comparisons / expected_comparisons)

		self.dataset.update_status("Writing network file")
		nx.write_gexf(network, self.dataset.get_results_path())
		self.dataset.finish(len(network.nodes))


class VideoHashSimilarities(BasicProcessor):
	"""
	Video Hasher Similarity calculator

	This creates a network graph of the video hashes similarity
	"""
	type = "video-hash-similarity-matrix"  # job type ID
	category = "Visual"  # category
	title = "Calculates hashes similarities"  # title displayed in UI
	description = "Creates hashes network to identify duplicate or similar videos."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	references = [
		"[Video Hash](https://github.com/akamhy/videohash#readme)",
	]

	@classmethod
	def get_options(cls, parent_dataset=None, user=None):
		return {"percent": {
			"type": UserInput.OPTION_TEXT,
			"help": "Percent similar",
			"default": 95,
			"min": 0,
			"max": 100
		}}

	@classmethod
	def is_compatible_with(cls, module=None, user=None):
		"""
		Allow on video hasher
		"""
		return module.type in ["video-hasher-1"]

	def process(self):
		"""

		"""
		percent_different = (100 - self.parameters.get("percent", 90)) / 100

		# Extract hash file from archive
		with zipfile.ZipFile(self.source_file, "r") as archive_file:
			archive_contents = sorted(archive_file.namelist())

			if "video_hashes.csv" not in archive_contents:
				self.dataset.update_status("Unable to obtain hashes from video colleges.", is_final=True)
				self.dataset.finish(0)
				return

			# Prepare staging area for videos and video tracking
			staging_area = self.dataset.get_staging_area()
			self.dataset.log('Staging directory location: %s' % staging_area)
			# Extract file
			archive_file.extract("video_hashes.csv", staging_area)

		# Read hash file
		self.dataset.update_status(f"Collecting video hashes for {self.parameters.get('percent', 90)}% similar network")
		hashes = []
		identifiers = {}
		bit_length = None
		with staging_area.joinpath("video_hashes.csv").open("r", encoding="utf-8", newline="") as infile:
			reader = csv.DictReader(infile)
			for i, row in enumerate(reader):
				video_hash = [int(bit) for bit in row.get('video_hash')[2:]]
				video_id = row.get('id')

				hashes.append(np.array(video_hash))
				identifiers[video_id] = i

				if bit_length is None:
					bit_length = len(video_hash)

		# Compare each video with rest
		self.dataset.update_status(f"Calculating video hash similarities {self.parameters.get('percent', 90)}% similar")
		all_video_hashes = np.array(hashes)
		similarity_matrix = []
		bits_threshhold = np.ceil(percent_different * bit_length)
		self.dataset.log(f"Bits threshold: {bits_threshhold}")
		for vid_hash in hashes:
			# Compare video hash to all other hashes and check if below threshold
			xor_result = np.bitwise_xor(vid_hash, hashes)
			similarity_matrix.append([xor_comparison.sum() <= bits_threshhold for xor_comparison in xor_result])

		self.dataset.update_status(f"Create groups video hash similarities above {self.parameters.get('percent', 90)}% similar")
		# These groups can merge and get rather large as similarities can "chain"
		# (e.g., A is similar to B, B is similar C, thus A & B & C are similar)
		groups = {"no_matches": []}
		video_group_key = {}
		group_index = 1
		for i, vid in enumerate(all_video_hashes):
			create_new_group = False
			if sum(similarity_matrix[i]) > 1:
				# matches found! identify group
				group = [i]
				for j in range(len(similarity_matrix[i])):
					if similarity_matrix[i][j] == True and j != i:
						group.append(j)

				# check if any of the matches are already in a group
				group_key_match = set(video_group_key.get(match) for match in group if video_group_key.get(match))
				if len(group_key_match) == 1:
					# One group found, add to that group
					group_name = group_key_match.pop()
					self.dataset.log(f"Adding to group {group_name}: {group}")
					groups[group_name] += group
				else:
					# Either no existing group or groups need to be merged into new group
					create_new_group = True
					if len(group_key_match) > 1:
						self.dataset.log(f"Merging groups to new group for: {group}") # this is not all yet
						# Multiple groups found, remove existing groups and add to the new group
						for match in group_key_match:
							# add to new group
							group += groups.pop(match)
						# remove duplicates from new group
						group = list(set(group))
					else:
						# no existing groups found, create new group
						self.dataset.log(f"Creating new group for: {group}")

			else:
				# no matches found, add to no_matches group
				group_name = "no_matches"
				group = [i]
				groups[group_name] += group
				self.dataset.log(f"No matches: {i}")

			if create_new_group:
				# Create new group
				group_name = "group_" + str(group_index)
				groups[group_name] = group
				group_index += 1

			# Update video group keys
			[video_group_key.update({video_index: group_name}) for video_index in group]

		# Write new hash file
		self.dataset.update_status("Writing new hash file")
		with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as outfile:
			with staging_area.joinpath("video_hashes.csv").open("r", encoding="utf-8", newline="") as infile:
				reader = csv.DictReader(infile)
				writer = csv.DictWriter(outfile, fieldnames=reader.fieldnames + ["group_id"])
				writer.writeheader()
				for row in reader:
					video_id = row.get('id')
					group_id = video_group_key.get(identifiers[video_id])
					row.update({"group_id": group_id})
					writer.writerow(row)

		self.dataset.finish(len(video_group_key))

