"""
Get YouTube metadata from video links posted
"""
import zipfile
import shutil
import pandas as pd
import math

import config

from pathlib import Path
from collections import Counter
from PIL import Image, ImageOps, ImageDraw, ImageFont

from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput, convert_to_int

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen", "Partha Das"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

class YouTubeImageWall(BasicProcessor):
	"""
	
	Takes YouTube thumbnails downloaded and makes an
	image wall out of it.

	"""

	type = "youtube-imagewall"  # job type ID
	category = "Visualisation" # category
	title = "YouTube thumbnails image wall"  # title displayed in UI
	description = "Make an image wall from YouTube video thumbnails."  # description displayed in UI
	extension = "png"  # extension of result file, used internally and in UI

	options = {
		"max_amount": {
			"type": UserInput.OPTION_TEXT,
			"default": 0,
			"help": "Only use n thumbnails (0 = all)"
		},
		"category_overlay": {
			"type": UserInput.OPTION_TOGGLE,
			"default": False,
			"help": "Overlay video categories"
		}
	}

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor on YouTube thumbnail sets

		:param module: Dataset or processor to determine compatibility with
		"""
		return module.type == "youtube-thumbnails"

	def process(self):
		"""
		Takes the thumbnails downloaded from YouTube metadata and
		turns it into an image wall. 

		"""
		results_path = self.dataset.get_results_path()
		dirname = Path(results_path.parent, results_path.name.replace(".", ""))

		# Get the required parameters
		# path to the YouTube csv data that was the source of the thumbnails
		root_csv = self.dataset.get_genealogy()[-3].get_results_path()
		max_amount = convert_to_int(self.parameters.get("max_amount", 0), 0)
		category_overlay = self.parameters.get("category_overlay")

		# Build that wall!
		self.make_imagewall(root_csv, max_amount=max_amount, category_overlay=category_overlay)

	def make_imagewall(self, path_to_yt_metadata, max_amount = 0, category_overlay = False):
		"""
		Makes a GIF wall from a bunch of image files
		:param path_to_yt_metadata string, path to the folder with relevant thumbnails
		:param max_amount int, only use the first n videos appearing in the csv 
		:param category_overlay bool, whether to overlay colours with YouTube video categories

		"""

		# Colours for category overlays
		categories = {
		"1": {"colour": (169,0,0), "category": "Film & Animation", "count":0},
		"2": {"colour": (82,224,119), "category": "Autos & Vehicles", "count":0},
		"10": {"colour": (56,84,174), "category": "Music", "count":0},
		"15": {"colour": (159,209,0), "category": "Pets & Animals", "count":0},
		"17": {"colour": (209,0,204), "category": "Sports", "count":0},
		"18": {"colour": (41,64,0), "category": "Short Movies", "count":0},
		"19": {"colour": (176,99,255), "category": "Travel & Events", "count":0},
		"20": {"colour": (220,199,59), "category": "Gaming", "count":0},
		"21": {"colour": (123,0,155), "category": "Videoblogging", "count":0},
		"22": {"colour": (0,190,149), "category": "People & Blogs", "count":0},
		"23": {"colour": (255,55,177), "category": "Comedy", "count":0},
		"24": {"colour": (111,219,52), "category": "Entertainment", "count":0},
		"25": {"colour": (255,75,97), "category": "News & Politics", "count":0},
		"26": {"colour": (95,212,249), "category": "Howto & Style", "count":0},
		"27": {"colour": (111,0,12), "category": "Education", "count":0},
		"28": {"colour": (102,147,255), "category": "Science & Technology", "count":0},
		"29": {"colour": (255,172,70), "category": "Nonprofits & Activism", "count":0},
		"30": {"colour": (3,28,107), "category": "Movies", "count":0},
		"31": {"colour": (90,60,0), "category": "Anime/Animation", "count":0},
		"32": {"colour": (223,156,255), "category": "Action/Adventure", "count":0},
		"33": {"colour": (63,33,0), "category": "Classics", "count":0},
		"34": {"colour": (255,146,218), "category": "Comedy", "count":0},
		"35": {"colour": (121,213,210), "category": "Documentary", "count":0},
		"36": {"colour": (168,0,120), "category": "Drama", "count":0},
		"37": {"colour": (0,119,144), "category": "Family", "count":0},
		"38": {"colour": (183,0,79), "category": "Foreign", "count":0},
		"39": {"colour": (0,59,134), "category": "Horror", "count":0},
		"40": {"colour": (255,140,128), "category": "Sci-Fi/Fantasy", "count":0},
		"41": {"colour": (71,5,76), "category": "Thriller", "count":0},
		"42": {"colour": (238,186,177), "category": "Shorts", "count":0},
		"43": {"colour": (60,51,81), "category": "Shows", "count":0},
		"44": {"colour": (202,192,237), "category": "Trailers", "count":0}
		}

		# Read the csv and get video ids
		df = pd.read_csv(path_to_yt_metadata)

		files = df["id"].tolist()

		# Cut the videos if there's a threshold given
		if max_amount != 0:
			files = files[:max_amount]

		amount = len(files)

		# Calculate image wall dimensions
		tiles_x = int(math.sqrt(amount))
		tiles_y = int(math.sqrt(amount))

		# Initialize our canvas
		tile_height = 180  # size of each tile, in pixels
		tile_width = 360

		wall_width = tiles_x * tile_width
		wall_height = tiles_y * tile_height

		wall = Image.new("RGBA", (wall_width, wall_height))
		counter = 0
		category_amount = 1
		categories_legend = []

		# Get a list of filenames of succesfully downloaded images
		with zipfile.ZipFile(str(self.source_file), "r") as image_archive:
			zipped_images = image_archive.namelist()

		# Save just the IDs for reference
		image_ids = [image[:-4] for image in zipped_images]

		# prepare staging area
		results_path = self.dataset.get_staging_area()

		# Loop through images and copy them onto the wall
		for file in files:
			counter += 1
			if counter % 50 == 0:
				self.dataset.update_status("Placing image " + str(counter) + "/" + str(len(files)))

			# Get the thumbnail if it exists
			# Else use a 'no video' template
			delete_after_use = False
			if file in image_ids:
				with zipfile.ZipFile(str(self.source_file), "r") as image_archive:
					temp_path = results_path.joinpath(file + ".jpg")
					image_archive.extract(file + ".jpg", results_path)
					delete_after_use = True
			else:
				temp_path = Path(config.PATH_ROOT, "common/assets/no-video.jpg")

			# Resize the image
			image = Image.open(temp_path)
			image = ImageOps.fit(image, (tile_width, tile_height), method=Image.BILINEAR)
			if delete_after_use:
				temp_path.unlink()

			# Turn image coloured if we want a category grid
			if category_overlay:

				category = df.loc[df["id"] == file, "video_category_id"].iloc[0]
				
				# If the video category is not null
				if not math.isnan(category) and file in image_ids:
					category = int(category)
					colour = categories[str(category)]["colour"]
					coloured_image = Image.new("RGBA", image.size, color=colour)
					image = coloured_image
					categories_legend.append(category)
					categories[str(category)]["count"] += 1

				else:
					# If there's no category, make the image transparent
					coloured_image = Image.new("RGBA", image.size, (0, 0, 0, 0))
					image = coloured_image

			# Put image on wall
			index = counter - 1
			x = index % tiles_x
			y = math.floor(index / tiles_x)
			wall.paste(image, (x * tile_width, y * tile_height))

		# delete temporary files and folder
		shutil.rmtree(results_path)

		# Make a legend with categories
		if category_overlay:

			wall_old = wall
			wall = Image.new("RGBA", (wall_width, wall_height + 500))
			wall.paste(wall_old, box=(0,0))
			# Draw the category on the side
			# Get a font
			font = ImageFont.truetype(config.PATH_ROOT + "/common/assets/Inconsolata-Bold.ttf", 50)
			# Get a drawing context
			draw = ImageDraw.Draw(wall)

			# Order known categories by frequency
			categories_legend = Counter(categories_legend).most_common()
			categories_legend = [tpl[0] for tpl in categories_legend]
			text_width = 100
			text_height = wall_height + 50

			for i, category in enumerate(categories_legend):
				# Get category colour
				colour = categories[str(category)]["colour"]
				# Draw the category text with counts
				string = categories[str(category)]["category"] + " (" + str(categories[str(category)]["count"]) + ")"
				
				# Draw a background rectangle
				draw.rectangle((text_width - 15, text_height, text_width + (len(string) * 27), text_height + 70), fill=colour)
				# Draw the text
				draw.text((text_width, text_height), string, font=font, fill=(255,255,255))

				# Place the next label according to the amount of characters in the category
				text_width = text_width + (len(string) * 30)
				if text_width > wall_width - 200:
					text_width = 100
					text_height = text_height + 75

		# Finish up
		self.dataset.update_status("Saving result")
		wall.save(str(self.dataset.get_results_path()), dpi=(150, 150))
		self.dataset.finish(1)