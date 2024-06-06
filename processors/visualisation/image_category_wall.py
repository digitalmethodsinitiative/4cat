"""
Create an image wall using categories.
"""
import io
import base64
import json
import math

from svgwrite.image import Image as ImageElement

from svgwrite.container import SVG
from svgwrite.shapes import Rect
from svgwrite.text import Text

from PIL import Image

from common.lib.helpers import UserInput, convert_to_int, get_4cat_canvas
from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException, ProcessorException
from common.config_manager import config

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl", "Stijn Peeters"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"

class ImageWallGenerator(BasicProcessor):
	"""
	Image wall generator

	Create an image wall from the top images in the dataset
	"""
	type = "image-category-wall"  # job type ID
	category = "Visual"  # category
	title = "Visualise images by category"  # title displayed in UI
	description = "Combine images into a single image arranged by category"  # description displayed in UI
	extension = "svg"  # extension of result file, used internally and in UI

	number_of_ranges = 10  # number of ranges to use for numeric categories

	image_datasets = ["image-downloader", "video-hasher-1"]

	config = {
		"image-visuals.max_per_cat": {
			"type": UserInput.OPTION_TEXT,
			"coerce_type": int,
			"default": 1000,
			"help": "Max images per category when visualising",
			"tooltip": "0 will allow visualization of any number of images."
		},
		"image-visuals.max_pixels_per_image": {
			"type": UserInput.OPTION_TEXT,
			"coerce_type": int,
			"default": 300,
			"min": 25,
			"help": "Max pixels for each images when visualising",
		}
	}

	@classmethod
	def is_compatible_with(cls, module=None, user=None):
		"""
		Allow processor on CLIP dataset only
		
		:param module: Dataset or processor to determine compatibility with
		"""
		return module.type.startswith("image-to-categories") or \
			module.type.startswith("image-downloader") or \
			module.type.startswith("video-hasher-1") or \
			module.type.startswith("video-hash-similarity-matrix")

	@classmethod
	def get_options(cls, parent_dataset=None, user=None):
		"""
		Collect maximum number of audio files from configuration and update options accordingly
		"""
		max_number_images = int(config.get("image-visuals.max_per_cat", 1000, user=user))
		max_pixels = int(config.get("image-visuals.max_pixels_per_image", 300, user=user))
		options = {
			"category": {
				"type": UserInput.OPTION_TEXT,
				"help": "Category column"
			},
			"width_amount": {
				"type": UserInput.OPTION_TEXT,
				"help": "Max images per category" + (f" (max {max_number_images:,})" if max_number_images != 0 else ""),
				"default": 10 if max_number_images == 0 else min(max_number_images, 10),
				"min": 0 if max_number_images == 0 else 1,
				"max": max_number_images,
				"tooltip": "This controls the width of the image wall"
			},
			"height": {
				"type": UserInput.OPTION_TEXT,
				"help": "Image height in pixels",
				"tooltip": f"In pixels. Each image will be this height and are resized proportionally to fit it. Must be between 25 and {max_pixels}.",
				"coerce_type": int,
				"default": min(max_pixels, 100),
				"min": 25,
				"max": max_pixels
			},
			"images_per_item": {
				"type": UserInput.OPTION_CHOICE,
				"options": {
					"all": "All images",
					"first": "Only first image",
				},
				"default": "first",
				"help": "Images per item",
				"tooltip": "If an item has multiple images, should all images be used or if the first one representative?",
			}
		}
		if max_number_images == 0:
			options['width_amount']['tooltip'] = options['width_amount']['tooltip'] + ";'0' will use all available images"
			options['width_amount'].pop('max')

		if parent_dataset is None:
			return options
		else:
			image_dataset, category_dataset = cls.identity_dataset_types(parent_dataset)
			if category_dataset is None:
				return options

		parent_columns = category_dataset.get_columns()
		if parent_columns:
			parent_columns = {c: c for c in sorted(parent_columns)}

			options["category"] = {
				"type": UserInput.OPTION_CHOICE,
				"options": parent_columns,
				"help": "Category column",
				"tooltip": "Each image must belong to only one category; numeric categories will be grouped into ranges",
			}
			default_options = [default for default in ["top_categories", "impression_count", "category", "type"] if default in parent_columns]
			if default_options:
				options["category"]["default"] = default_options.pop(0)

		return options

	@staticmethod
	def identity_dataset_types(source_dataset):
		"""
		Identify dataset types that are compatible with this processor
		"""
		if any([source_dataset.type.startswith(dataset_prefix) for dataset_prefix in ImageWallGenerator.image_datasets]):
			image_dataset = source_dataset
			category_dataset = source_dataset.top_parent()
		elif any([source_dataset.get_parent().type.startswith(dataset_prefix) for dataset_prefix in ImageWallGenerator.image_datasets]):
			image_dataset = source_dataset.get_parent()
			category_dataset = source_dataset
		else:
			return None, None

		return image_dataset, category_dataset

	def process(self):
		"""
		Process the job
		"""
		image_dataset, category_dataset = self.identity_dataset_types(self.source_dataset)
		if image_dataset is None or category_dataset is None:
			self.dataset.finish_with_error("Unable to indentify image and category datasets")
			return

		# is there anything to put on a wall?
		if image_dataset.num_rows == 0 or category_dataset == 0:
			self.dataset.finish_with_error("No images/categories available to render to image wall.")
			return
		self.dataset.log(f"Found {image_dataset.type} w/ {image_dataset.num_rows} images and {category_dataset.type} w/ {category_dataset.num_rows} items")

		category_column = self.parameters.get("category")
		if category_column is None:
			self.dataset.finish_with_error("No category provided.")
			return

		# 0 = use as many images as in the archive, up to the max
		images_per_category = convert_to_int(self.parameters.get("width_amount"), 100)
		images_per_item = self.parameters.get("images_per_item", "first")

		# Some processors may have a special category type to extract categories
		special_case = category_dataset.type == "image-to-categories"

		# First collect images; maybe posts will not have associated images
		# Unpack the images into a staging_area
		self.dataset.update_status("Unzipping images")
		staging_area = self.unpack_archive_contents(image_dataset.get_results_path())

		# Map post IDs to filenames
		if image_dataset.type == "video-hasher-1":
			# We know the post ID is the filename.stem as this dataset is derived from the image dataset
			filename_map = {filename.stem + ".mp4": filename for filename in staging_area.iterdir()}
		elif special_case:
			# We know the post ID is the filename.stem as this dataset is derived from the image dataset
			filename_map = {filename.stem: filename for filename in staging_area.iterdir()}
		else:
			# Use image metadata to map post IDs to filenames
			with open(staging_area.joinpath('.metadata.json')) as file:
				image_data = json.load(file)
			filename_map = {}
			# Images can belong to multiple posts; posts can have multiple images
			for image in image_data.values():
				if image.get("success"):
					for post_id in image.get("post_ids"):
						if post_id not in filename_map:
							filename_map[post_id] = [staging_area.joinpath(image.get("filename"))]
						else:
							filename_map[post_id].append(staging_area.joinpath(image.get("filename")))

		# Organize posts into categories
		category_type = None
		categories = {}
		post_values = []  # used for numeric categories
		self.dataset.update_status("Collecting categories")
		for i, post in enumerate(category_dataset.iterate_items(self)):
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while collecting categories")

			if post.get("id") not in filename_map:
				# No image for this post
				continue

			# Identify category type and collect post_category
			if special_case and category_column == "top_categories":
				if category_type is None:
					category_type = float
				# Special case
				top_cats = post.get("top_categories")
				top_cat = top_cats.split(",")[0].split(":")[0].strip()
				top_cat_score = float(top_cats.split(",")[0].split(":")[1].strip().replace("%", ""))
				post_result = {"id": post.get("id"), "value": top_cat_score, "top_cats": top_cats}
				if top_cat not in categories:
					categories[top_cat] = [post_result]
				else:
					categories[top_cat].append(post_result)
			else:
				if category_type is None:
					try:
						if post.get(category_column) is None:
							category_type = str
						else:
							float(post.get(category_column))
							category_type = float
					except ValueError:
						category_type = str

				if category_type == str:
					post_category = post.get(category_column)
					if post_category == "" or post_category is None:
						post_category = "None"
					if post_category not in categories:
						categories[post_category] = [{"id": post.get("id")}]
					else:
						categories[post_category].append({"id": post.get("id")})
				elif category_type == float:
					if post.get(category_column) is None:
						self.dataset.log(f"Post {post.get('id')} has no data; skipping")
						continue
					try:
						post_category = float(post.get(category_column))
						post_values.append((post_category, post.get("id")))
					except ValueError:
						# Unsure exactly how to handle; possibly the first post was convertible to a float
						raise ProcessorException(
							f"Mixed category types detected; unable to render image wall (item {i} {post_category})")

		if len(categories) == 0 and len(post_values) == 0:
			self.dataset.finish_with_error("No categories found")
			return

		# Sort collected category results as needed
		self.dataset.update_status("Sorting categories")
		if special_case and category_column == "top_categories":
			# Sort categories by score
			for cat in categories:
				categories[cat] = sorted(categories[cat], key=lambda x: x.get("value"), reverse=True)
		elif category_type == float:
			if all([x[0].is_integer() for x in post_values]):
				self.dataset.log("Detected integer categories")
				post_values = [(int(x[0]), x[1]) for x in post_values]
				category_type = int

			# Identify ranges
			all_values = [x[0] for x in post_values]
			max_value = max(all_values)
			min_value = min(all_values)
			range_size = (max_value - min_value) / self.number_of_ranges
			if category_type == int:
				ranges = [(math.floor(min_value + range_size * i), math.ceil(min_value + range_size * (i + 1))) for i in range(self.number_of_ranges)]
			else:
				ranges = [(min_value + range_size * i, min_value + range_size * (i + 1)) for i in range(self.number_of_ranges)]
			ranges.reverse()

			# Sort posts into ranges
			if category_type == int:
				categories = {f"{x[0]} - {x[1]}": [] for x in ranges}
			else:
				categories = {f"{x[0]:.2f} - {x[1]:.2f}": [] for x in ranges}
			for value, post_id in post_values:
				for min_value, max_value in ranges:
					if min_value <= value <= max_value:  # inclusive as an image is the exact min and exact max; we break so images are stored in only first matching range
						if category_type == int:
							categories[f"{min_value} - {max_value}"].append({"id": post_id, "value": value})
						else:
							categories[f"{min_value:.2f} - {max_value:.2f}"].append({"id": post_id, "value": value})
						break

			# And sort the posts within each range
			for cat in categories:
				categories[cat] = sorted(categories[cat], key=lambda x: x.get("value"), reverse=True)

		else:
			# Sort categories by number of images
			categories = {cat[0]: cat[1] for cat in sorted(categories.items(), key=lambda x: len(x), reverse=True)}

		# Drop categories with no images (ranges may have no images)
		categories = {cat: images for cat, images in categories.items() if images}
		self.dataset.log(f"Found {len(categories)} categories")

		# Create SVG with categories and images
		base_height = self.parameters.get("height", 100)
		fontsize = 12
		row_height = base_height + fontsize * 2

		offset_y = - row_height
		complete_categories = []
		category_widths = {}
		self.dataset.update_status("Creating Image wall")
		for category, images in categories.items():
			if not complete_categories:
				offset_y += fontsize * 2  # add some space at the top for header
			# reset and ready for the next timeline
			offset_y += row_height
			category_widths[category] = 0
			category_image = SVG(insert=(0, offset_y), size=(0, row_height))
			offset_w = 0

			for i, image in enumerate(images):
				if images_per_category != 0 and i >= images_per_category:
					# Category full; add a label to indicate there are more images in category
					remaining = f"+ {len(images) - images_per_category} more images"
					footersize = (fontsize * (len(remaining) + 2) * 0.5925, fontsize * 2)
					footer_shape = SVG(insert=(offset_w, base_height/2 - footersize[1]), size=footersize)
					footer_shape.add(Rect(insert=(0, 0), size=("100%", "100%"), fill="#000"))
					label_element = Text(insert=("50%", "50%"), text=remaining, dominant_baseline="middle",
										 text_anchor="middle", fill="#FFF", style="font-size:%ipx" % fontsize)
					footer_shape.add(label_element)
					category_image.add(footer_shape)
					offset_w += footersize[0]

					category_widths[category] += footersize[0]
					break

				# Get image or images for this item
				image_filenames = filename_map.get(image.get("id")) if images_per_item == "all" else [filename_map.get(image.get("id"), [None])[0]]
				if not image_filenames:
					self.dataset.log(f"Image {image.get('id')} not found in image archive")
					continue
				for image_filename in image_filenames:
					frame = Image.open(str(image_filename))

					frame_width = int(base_height * frame.width / frame.height)
					frame.thumbnail((frame_width, base_height))

					# add to SVG as data URI (so it is a self-contained file)
					frame_data = io.BytesIO()
					try:
						frame.save(frame_data, format="JPEG")  # JPEG probably optimal for video frames
					except OSError:
						# Try removing alpha channel
						frame = frame.convert('RGB')
						frame.save(frame_data, format="JPEG")
					frame_data = "data:image/jpeg;base64," + base64.b64encode(frame_data.getvalue()).decode("utf-8")
					# add to category element
					frame_element = ImageElement(href=frame_data, insert=(category_widths[category], 0),
												 size=(frame_width, base_height))
					category_image.add(frame_element)

					# add score label
					if category_type in [float, int]:
						if category_type == int:
							image_score = str(image.get("value"))
						else:
							image_score = f"{image.get('value'):.2f}" + ("%" if special_case and (category_column == "top_categories") else "")
						footersize = (fontsize * (len(image_score) + 2) * 0.5925, fontsize * 2)
						footer_shape = SVG(insert=(offset_w, base_height - footersize[1]), size=footersize)
						footer_shape.add(Rect(insert=(0, 0), size=("100%", "100%"), fill="#000"))
						label_element = Text(insert=("50%", "50%"), text=image_score, dominant_baseline="middle",
											 text_anchor="middle", fill="#FFF", style="font-size:%ipx" % fontsize)
						footer_shape.add(label_element)
						category_image.add(footer_shape)
					offset_w += frame_width

					category_widths[category] += frame_width
					self.dataset.log(f"Added image {image.get('id')} to category {category}; width {category_widths[category]} height {offset_y}")

			# Add Category label
			footersize = (fontsize * (len(category) + 2) * 0.5925, fontsize * 2)
			footer_shape = SVG(insert=(0, row_height - footersize[1]), size=footersize)
			footer_shape.add(Rect(insert=(0, 0), size=("100%", "100%"), fill="#000"))
			label_element = Text(insert=("50%", "50%"), text=category, dominant_baseline="middle",
								 text_anchor="middle", fill="#FFF", style="font-size:%ipx" % fontsize)
			footer_shape.add(label_element)
			self.dataset.log(f"{category_image}")
			category_image["width"] = max(category_widths[category], footersize[0])

			# add to canvas
			category_image.add(footer_shape)
			complete_categories.append(category_image)

		# now we know all dimensions we can instantiate the canvas too
		canvas_width = max(category_widths.values())
		canvas = get_4cat_canvas(self.dataset.get_results_path(), canvas_width, row_height * len(category_widths) + fontsize * 4, header=f"Images sorted by {category_column}",
								 fontsize_small=fontsize, fontsize_large=fontsize)

		for category_image in complete_categories:
			self.dataset.log(f"Adding {category_image}")
			canvas.add(category_image)

		# save as svg and finish up
		canvas.save(pretty=True)
		self.dataset.log("Saved to " + str(self.dataset.get_results_path()))
		return self.dataset.finish(len(category_widths))



