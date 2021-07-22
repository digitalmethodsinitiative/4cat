"""
Create an image wall of the most-used images
"""
import colorsys
import random
import shutil
import math

from PIL import Image, ImageFile, ImageOps, ImageDraw, UnidentifiedImageError
from sklearn.cluster import KMeans

from common.lib.helpers import UserInput, convert_to_int
from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

class ImageWallGenerator(BasicProcessor):
	"""
	Image wall generator

	Create an image wall from the top images in the dataset
	"""
	type = "image-wall"  # job type ID
	category = "Visual"  # category
	title = "Image wall"  # title displayed in UI
	description = "Put all images in an archive into a single combined image, optionally sorting and resizing them"
	extension = "png"  # extension of result file, used internally and in UI

	options = {
		"amount": {
			"type": UserInput.OPTION_TEXT,
			"help": "No. of images (max 1000)",
			"default": 100,
			"min": 0,
			"max": 1000,
			"tooltip": "'0' uses as many images as available in the source image archive (up to 1000)"
		},
		"tile-size": {
			"type": UserInput.OPTION_CHOICE,
			"options": {
				"square": "Square",
				"average": "Average image in set",
				"fit-height": "Fit height"
			},
			"default": "square",
			"help": "Image tile size",
			"tooltip": "'Fit height' retains image ratios but resizes them all to be the same height"
		},
		"sort-mode": {
			"type": UserInput.OPTION_CHOICE,
			"help": "Sort images by",
			"options": {
				"": "Do not sort",
				"random": "Random",
				"dominant": "Dominant colour (decent, faster)",
				"kmeans-dominant": "Dominant K-means (precise, slow)",
				"kmeans-average": "Weighted K-means average (precise, slow)",
				"average-rgb": "Average colour (RGB; imprecise, fastest)",
				"average-hsv": "Average colour (HSV; imprecise, fastest)",
			},
			"tooltip": "If you're unsure what sorting method to use, dominant colour usually gives decent results",
			"default": ""
		}
	}

	# images will be arranged and resized to fit these image wall dimensions
	# note that image aspect ratio may not allow for a precise fit
	TARGET_WIDTH = 2560
	TARGET_HEIGHT = 1440


	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor on token sets

		:param module: Dataset or processor to determine compatibility with
		"""
		return module.type == "image-downloader"

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column with image hashes, one with the first file name used
		for the image, and one with the amount of times the image was used
		"""
		self.dataset.update_status("Reading source file")

		# prepare
		ImageFile.LOAD_TRUNCATED_IMAGES = True
		sample_max = 75  # image size for colour sampling

		def numpy_to_rgb(numpy_array):
			"""
			Helper function to go from numpy array to list of RGB strings

			Used in the K-Means clustering part
			"""
			return ",".join([str(int(value)) for value in numpy_array])

		max_images = convert_to_int(self.parameters.get("amount"), 100)
		sizing_mode = self.parameters.get("tile-size")
		sort_mode = self.parameters.get("sort-mode")

		# is there anything to put on a wall?
		if self.source_dataset.num_rows == 0:
			self.dataset.update_status("No images available to render to image wall.", is_final=True)
			self.dataset.finish(0)
			return

		# 0 = use as many images as in the archive, up to the max
		if max_images == 0:
			max_images = self.get_options()["amount"]["max"]

		# we loop through the images twice - once to reduce them to a value
		# that can be sorted, and another time to actually copy them to the
		# canvas for the image wall

		# we create a staging area manually here, so it is not automatically
		# deleted after one loop, since we need two
		staging_area = self.dataset.get_staging_area()

		# first, extract and reduce, and store the sortable value in a
		# dictionary with the image file name as key
		image_colours = {}
		dimensions = {}  # used to calculate optimal tile size later
		index = 0
		random_values = list(range(0, self.source_dataset.num_rows))
		random.shuffle(random_values)

		for path in self.iterate_archive_contents(self.source_file, staging_area):
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while determining image wall order")

			try:
				picture = Image.open(str(path))
			except UnidentifiedImageError:
				self.dataset.update_status("Image %s could not be parsed. Skipping." % path)
				continue

			self.dataset.update_status("Analysing %s (%i/%i)" % (path.name, len(dimensions), self.source_dataset.num_rows))

			# these calculations can take ages for huge images, so resize if it is
			# larger than the threshold
			dimensions[path.name] = (picture.width, picture.height)
			if sort_mode not in ("", "random") and (picture.height > sample_max or picture.width > sample_max):
				sample_width = int(sample_max * picture.width / max(picture.width, picture.height))
				sample_height = int(sample_max * picture.height / max(picture.width, picture.height))
				picture = ImageOps.fit(picture, (sample_width, sample_height))

			if sort_mode not in ("", "random"):
				# ensure we get RGB values for pixels
				picture = picture.convert("RGB")

			# determine a 'representative colour'
			if sort_mode == "random":
				# just randomly sort it, don't even look at the colours
				value = random_values.pop()

			elif sort_mode in ("average-rgb", "average-hsv"):
				# average colour, as RGB or HSV
				pixels = picture.getdata()
				if sort_mode == "average-hsv":
					pixels = [colorsys.rgb_to_hsv(*pixel) for pixel in pixels]

				sum_colour = (sum([p[0] for p in pixels]), sum([p[1] for p in pixels]), sum([p[2] for p in pixels]))
				avg_colour = (sum_colour[0] / len(pixels), sum_colour[1] / len(pixels), sum_colour[2] / len(pixels))

				# this is a bit dumb, but since all the other modes return rgb...
				if sort_mode == "average-hsv":
					avg_colour = colorsys.hsv_to_rgb(*avg_colour)

				value = avg_colour

			elif sort_mode == "dominant":
				# most-occurring colour
				colours = picture.getcolors(picture.width * picture.height)
				colours = sorted(colours, key=lambda x: x[0], reverse=True)
				value = colours[0][1]

			elif sort_mode in ("kmeans-dominant", "kmeans-average"):
				# use k-means clusters to determine the representative colour
				# this is more computationally expensive but gives far better
				# results.

				# determine k-means clusters for this image, i.e. the n most
				# dominant "average" colours, in this case n=3 (make parameter?)
				pixels = picture.getdata()
				clusters = KMeans(n_clusters=3, random_state=0)  # 0 so it is deterministic
				predicted_centroids = clusters.fit_predict(pixels).tolist()

				# now we have two options -
				if sort_mode == "kmeans-dominant":
					# the colour of the single most dominant k-means centroid
					ranked_centroids = {}
					for index in range(0, len(clusters.cluster_centers_)):
						ranked_centroids[numpy_to_rgb(clusters.cluster_centers_[index])] = predicted_centroids.count(
							index)

					value = [int(v) for v in
							 sorted(ranked_centroids, key=lambda k: ranked_centroids[k], reverse=True)[0].split(",")]

				elif sort_mode == "kmeans-average":
					# average colour of all k-means centroids, weighted by the
					# dominance of each centroid
					value = [0, 0, 0]
					for index in clusters.labels_:
						value[0] += clusters.cluster_centers_[index][0]
						value[1] += clusters.cluster_centers_[index][1]
						value[2] += clusters.cluster_centers_[index][2]

					value[0] /= len(clusters.labels_)
					value[1] /= len(clusters.labels_)
					value[2] /= len(clusters.labels_)

			else:
				value = (0, 0, 0)

			# converted to HSV, because RGB does not sort nicely
			image_colours[path.name] = colorsys.rgb_to_hsv(*value)
			index += 1

		# only retain the top n of the sorted list of images - this gives us
		# our final image set
		sorted_image_files = [path for path in sorted(image_colours, key=lambda k: image_colours[k])[:max_images]]
		dimensions = {path: dimensions[path] for path in sorted_image_files}
		average_size = (
			sum([k[0] for k in dimensions.values()]) / len(dimensions),
			sum([k[1] for k in dimensions.values()]) / len(dimensions))

		self.dataset.update_status("Determining canvas and image sizes")

		# calculate 'tile sizes' (a tile is an image) and also the size of the
		# canvas we will need to fit them all. The canvas can never be larger than
		# this:
		max_pixels = self.TARGET_WIDTH * self.TARGET_HEIGHT

		if sizing_mode == "fit-height":
			# assuming every image has the overall average height, how wide would
			# the canvas need to be (if everything is on a single row)?
			full_width = 0
			tile_y = average_size[1]
			for dimension in dimensions.values():
				# ideally, we make everything the average height
				optimal_ratio = average_size[1] / dimension[1]
				full_width += dimension[0] * optimal_ratio

			# now we can calculate the total amount of pixels needed
			fitted_pixels = full_width * tile_y
			if fitted_pixels > max_pixels:
				# try again with a lower height
				area_ratio = max_pixels / fitted_pixels
				tile_y = int(tile_y * math.sqrt(area_ratio))
				fitted_pixels = max_pixels

			# find the canvas size that can fit this amount of pixels at the
			# required proportions, provided that y = multiple of avg height
			ideal_height = math.sqrt(fitted_pixels / (self.TARGET_WIDTH / self.TARGET_HEIGHT))
			size_y = math.ceil(ideal_height / tile_y) * tile_y
			size_x = fitted_pixels / size_y

			tile_x = -1  # varies

		elif sizing_mode == "square":
			# assuming each image is square, find a canvas with the right
			# proportions that would fit all of them
			# assume the average dimensions
			tile_size = int(sum(average_size) / 2)

			# this is how many pixels we need
			fitted_pixels = tile_size * tile_size * len(sorted_image_files)

			# does that fit our canvas?
			if fitted_pixels > max_pixels:
				tile_size = math.floor(math.sqrt(max_pixels / len(sorted_image_files)))
				fitted_pixels = tile_size * tile_size * len(sorted_image_files)

			ideal_width = math.sqrt(fitted_pixels / (self.TARGET_HEIGHT / self.TARGET_WIDTH))
			size_x = math.ceil(ideal_width / tile_size) * tile_size
			size_y = math.ceil(fitted_pixels / size_x / tile_size) * tile_size

			tile_x = tile_y = tile_size

		elif sizing_mode == "average":
			tile_x = int(average_size[0])
			tile_y = int(average_size[1])

			fitted_pixels = tile_x * tile_y * len(sorted_image_files)
			if fitted_pixels > max_pixels:
				area_ratio = max_pixels / fitted_pixels
				tile_x = int(tile_x * math.sqrt(area_ratio))
				tile_y = int(tile_y * math.sqrt(area_ratio))
				fitted_pixels = tile_x * tile_y * len(sorted_image_files)

			ideal_width = math.sqrt(fitted_pixels / (self.TARGET_HEIGHT / self.TARGET_WIDTH))
			size_x = math.ceil(ideal_width / tile_x) * tile_x
			size_y = math.ceil(fitted_pixels / size_x / tile_y) * tile_y

		else:
			raise NotImplementedError("Sizing mode '%s' not implemented" % sizing_mode)

		self.dataset.log("Canvas size is %ix%i" % (size_x, size_y))
		wall = Image.new("RGBA", (int(size_x), int(size_y)))
		ImageDraw.floodfill(wall, (0, 0), (255, 255, 255, 0))  # transparent background
		counter = 0
		offset_x = 0
		offset_y = 0

		tile_x = int(tile_x)
		tile_y = int(tile_y)

		# now actually putting the images on a wall is relatively trivial
		for path in sorted_image_files:
			counter += 1
			self.dataset.update_status("Rendering %s (%i/%i) to image wall" % (path, counter, len(sorted_image_files)))
			picture = Image.open(str(staging_area.joinpath(path)))

			if tile_x == -1:
				picture_x = max(1, int(picture.width * (tile_y / picture.height)))
				picture = ImageOps.fit(picture, (picture_x, tile_y), method=Image.BILINEAR)
			else:
				picture = ImageOps.fit(picture, (tile_x, tile_y), method=Image.BILINEAR)

			# simply put them side by side until the right edge is reached,
			# then move to a new row
			if offset_x + picture.width > wall.width:
				offset_x = 0
				offset_y += picture.height

			# this can happen in some edge cases: there is an extra row of
			# images we hadn't accounted for. In that case, simply enlarge the
			# canvas.
			if offset_y + picture.height > wall.height:
				new_wall = Image.new("RGBA", (wall.width, offset_y + picture.height))
				ImageDraw.floodfill(new_wall, (0, 0), (255, 255, 255, 0))  # transparent background
				new_wall.paste(wall, (0, 0))
				wall = new_wall

			wall.paste(picture, (offset_x, offset_y))
			offset_x += picture.width

		# finish up
		self.dataset.update_status("Saving result")
		wall.save(str(self.dataset.get_results_path()))
		shutil.rmtree(staging_area)

		self.dataset.update_status("Finished")
		self.dataset.finish(counter)