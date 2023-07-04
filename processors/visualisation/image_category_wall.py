"""
Create an image wall using categories from the OpenAI CLIP model (or possibly something else?).
"""
import io
import base64
from svgwrite.image import Image as ImageElement

from svgwrite.container import SVG
from svgwrite.shapes import Rect
from svgwrite.text import Text

from PIL import Image

from common.lib.helpers import UserInput, convert_to_int, get_4cat_canvas
from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException

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
	description = "Put images in a single combined image arranged by category"  # description displayed in UI
	extension = "svg"  # extension of result file, used internally and in UI

	options = {
		"amount": {
			"type": UserInput.OPTION_TEXT,
			"help": "No. of images (max 1000)",
			"default": 100,
			"min": 0,
			"max": 1000,
			"tooltip": "'0' uses as many images as available in the archive (up to 1000)"
		},
		"height": {
			"type": UserInput.OPTION_TEXT,
			"help": "Image height",
			"tooltip": "In pixels. Each image will be this height and are resized proportionally to fit it. "
					   "Must be between 25 and 200.",
			"coerce_type": int,
			"default": 100,
			"min": 25,
			"max": 200
		}
	}

	@classmethod
	def is_compatible_with(cls, module=None, user=None):
		"""
		Allow processor on CLIP dataset only
		TODO: allow on other categories! Could grab data from original dataset such as tags?

		:param module: Dataset or processor to determine compatibility with
		"""
		return module.type.startswith("image-to-categories")

	def process(self):
		"""
		Process the job
		"""
		image_dataset = self.source_dataset.get_parent()

		# is there anything to put on a wall?
		if image_dataset.num_rows == 0 or self.source_dataset == 0:
			self.dataset.update_status("No images/categories available to render to image wall.", is_final=True)
			self.dataset.finish(0)
			return

		# 0 = use as many images as in the archive, up to the max
		max_images = convert_to_int(self.parameters.get("amount"), 100)
		if max_images == 0:
			max_images = self.get_options()["amount"]["max"]

		# Collect categories and image filenames
		categories = {}
		for post in self.source_dataset.iterate_items(self):
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while collecting categories")
			top_cats = post.get("top_categories")
			top_cat = top_cats.split(",")[0].split(":")[0].strip()
			top_cat_score = float(top_cats.split(",")[0].split(":")[1].strip().replace("%", ""))
			post_result = {"id": post.get("id"), "top_cat_score": top_cat_score, "top_cats": top_cats}
			if top_cat not in categories:
				categories[top_cat] = [post_result]
			else:
				categories[top_cat].append(post_result)

		# Sort categories by score
		for cat in categories:
			categories[cat] = sorted(categories[cat], key=lambda x: x.get("top_cat_score"), reverse=True)

		images_per_category = max_images // len(categories)

		# Unpack the images into a staging_area
		self.dataset.update_status("Unzipping images")
		staging_area = self.unpack_archive_contents(image_dataset.get_results_path())
		filename_map = {filename.stem: filename for filename in staging_area.iterdir()}

		base_height = self.parameters.get("height", 100)
		fontsize = 12
		row_height = base_height + fontsize * 2

		offset_y = -row_height
		complete_categories = []
		category_widths = {}

		for category, images in categories.items():
			# reset and ready for the next timeline
			offset_y += row_height
			category_widths[category] = 0
			category_image = SVG(insert=(0, offset_y), size=(0, row_height))
			offset_w = 0

			for i, image in enumerate(images):
				if i >= images_per_category:
					break

				image_filename = filename_map.get(image.get("id"))
				if not image_filename:
					self.dataset.log(f"Image {image.get('id')} not found in image archive")
					continue
				frame = Image.open(str(image_filename))

				frame_width = int(base_height * frame.width / frame.height)
				frame.thumbnail((frame_width, base_height))

				# add to SVG as data URI (so it is a self-contained file)
				frame_data = io.BytesIO()
				frame.save(frame_data, format="JPEG")  # JPEG probably optimal for video frames
				frame_data = "data:image/jpeg;base64," + base64.b64encode(frame_data.getvalue()).decode("utf-8")
				# add to category element
				frame_element = ImageElement(href=frame_data, insert=(category_widths[category], 0),
											 size=(frame_width, base_height))
				category_image.add(frame_element)

				# add score label
				image_score = str(image.get("top_cat_score")) + "%"
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
		canvas = get_4cat_canvas(self.dataset.get_results_path(), canvas_width, row_height * len(category_widths),
								 fontsize_small=fontsize)

		for category_image in complete_categories:
			self.dataset.log(f"Adding {category_image}")
			canvas.add(category_image)

		# save as svg and finish up
		canvas.save(pretty=True)
		self.dataset.log("Saved to " + str(self.dataset.get_results_path()))
		return self.dataset.finish(len(category_widths))



