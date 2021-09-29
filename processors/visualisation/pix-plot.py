"""
Create an PixPlot of downloaded images
"""
import shutil
import requests
import time
import dateutil.parser
import csv
import os
import config

from common.lib.helpers import UserInput, convert_to_int
from backend.abstract.processor import BasicProcessor

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class PixPlotGenerator(BasicProcessor):
	"""
	PixPlot generator

	Create an PixPlot from the downloaded images in the dataset
	"""
	type = "pix-plot"  # job type ID
	category = "Visual"  # category
	title = "PixPlot"  # title displayed in UI
	description = "Put all images in an archive into a PixPlot, which allows you to explore and visualize them."
	extension = "html"  # extension of result file, used internally and in UI

	options = {
		"amount": {
			"type": UserInput.OPTION_TEXT,
			"help": "No. of images (max 1000)",
			"default": 100,
			"min": 0,
			"max": 1000,
			"tooltip": "'0' uses as many images as available in the source image archive (up to 1000)"
		},
	}

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor on token sets;
		Checks if PIXPLOT_SERVER set in config.py

		:param module: Dataset or processor to determine compatibility with
		"""
		return module.type == "image-downloader" and config.PIXPLOT_SERVER

	def process(self):
		"""
		This takes a 4CAT results file as input, copies the images to a temp
		folder,
		"""
		self.dataset.update_status("Reading source file")

		# Are there any available images?
		if self.source_dataset.num_rows == 0:
			self.dataset.update_status("No images available to render to PixPlot.", is_final=True)
			self.dataset.finish(0)
			return

		# 0 = use as many images as in the archive, up to the max
		max_images = convert_to_int(self.parameters.get("amount"), 100)
		if max_images == 0:
			max_images = self.get_options()["amount"]["max"]

		# Unpack the images into a staging_area
		self.dataset.update_status("Unzipping images")
		staging_area = self.unpack_archive_contents(self.source_file)
		self.log.info('PixPlot image staging area created: ' + str(staging_area))

		# Gather metadata
		self.dataset.update_status("Collecting metadata")
		metadata_file_path = self.format_metadata(staging_area)

		# First send photos to PixPlot
		# TODO: check if images have already been sent
		self.dataset.update_status("Uploading images to PixPlot")
		upload_url = config.PIXPLOT_SERVER.rstrip('/') + '/api/send_photos'
		# Prep metadata
		files = [('metadata', open(metadata_file_path, 'rb'))]
		# Prep images
		filenames = os.listdir(staging_area)
		for i, filename in enumerate(filenames):
			if i > max_images:
				break
			files.append(('images', open(os.path.join(staging_area, filename), 'rb')))
		# Name of folder for images
		data = {'folder_name': self.dataset.key}
		response = requests.post(upload_url, files=files, data=data)

		# Request PixPlot server create PixPlot
		self.dataset.update_status("Sending request to PixPlot")
		create_plot_url = response.json()['create_pixplot_post_info']['url']
		# All the options, which you can edit to add any additional options you want PixPlot to use during creation
		json_data = response.json()['create_pixplot_post_info']['json']
		# Send; receives response that process has started
		resp = requests.post(create_plot_url, json=json_data)
		if resp.status_code == 202:
			# new request
			new_request = True
		elif 'already exists' in resp.json()['error']:
			# repeat request
			new_request = False
		else:
			self.log.error('PixPlot create response: ' + str(resp.status_code) + ': ' + str(resp.text))
			if staging_area:
				shutil.rmtree(staging_area)
			raise RuntimeError("PixPlot unable to process request")

		# Wait for PixPlot to complete
		self.dataset.update_status("PixPlot generating results")
		while new_request:
			time.sleep(10)
			result = requests.get(resp.json()['result_url'])
			self.log.debug(str(result.json()))
			if 'status' in result.json().keys() and result.json()['status'] == 'running':
				# Still running
				continue
			elif 'report' in result.json().keys() and result.json()['report'][-6:-1] == 'Done!':
				# Complete without error
				self.dataset.update_status("PixPlot Completed!")
				self.log.info('PixPlot saved on : ' + config.PIXPLOT_SERVER)
				break
			else:
				# Something botched
				self.dataset.update_status("PixPlot Error")
				self.log.error("PixPlot Error: " + str(result.json()))
				break

		if staging_area:
			shutil.rmtree(staging_area)

		# Create HTML file
		plot_url = config.PIXPLOT_SERVER.rstrip('/') + '/plots/' + self.dataset.key + '/index.html'
		html_file = self.get_html_page(plot_url)

		# Write HTML file
		with self.dataset.get_results_path().open("w", encoding="utf-8") as output_file:
			output_file.write(html_file)

		# Finish
		self.dataset.update_status("Finished")
		self.dataset.finish(1)

	def format_metadata(self, temp_path):
		"""
		Returns metadata.csv file

		Columns for PixPlot metadata can be:
		filename |	the filename of the image
		category |	a categorical label for the image
		tags |	a pipe-delimited list of categorical tags for the image
		description |	a plaintext description of the image's contents
		permalink |	a link to the image hosted on another domain
		year |	a year timestamp for the image (should be an integer)
		label |	a categorical label used for supervised UMAP projection
		lat |	the latitudinal position of the image
		lng |	the longitudinal position of the image

		We have a folder with image filenames, a top_downloads csv with filenames and post ids, and a source file with
		the action information needed. Annoyingly the source file is by far the largest file so we do not want to hold
		it in memory. Instead we will loop through it and build the metadata file as we go.

		"""
		parents = self.dataset.get_genealogy()
		# Get the top_downloads file path which serves as the key to source file
		top_downloads_path = parents[-3].get_results_path()
		# Get source file path; should be the top parent
		source_path = self.dataset.top_parent().get_results_path()
		# Get path for metadata file
		metadata_file_path = temp_path.joinpath('metadata.csv')
		# Set fieldnames for metadata file
		fieldnames = ['filename', 'description', 'permalink', 'year', 'tags', 'number_of_posts']

		# Open metadata file and iterate through source file
		with metadata_file_path.open("w", encoding="utf-8", newline="") as output:
			# Our to-be metadata
			images = {}

			# Loop through top_downloads csv and build key
			post_id_image_dictionary = {}
			for post in self.iterate_items(top_downloads_path):

				# Check if image successfully downloaded for image
				if post["download_status"] == 'succeeded':
					ids = post['ids'].split(',')
					for post_id in ids:
						# Add to key
						if post_id in post_id_image_dictionary.keys():
							post_id_image_dictionary[post_id].append(post['img_name'])
						else:
							post_id_image_dictionary[post_id] = [post['img_name']]

					# Add to metadata
					images[post['img_name']] = {'filename': post['img_name'],
												'permalink': post['item'],
												'description': '<b>Num of Post(s) w/ Image:</b> ' + str(post['value']),
												'tags': '',
												'number_of_posts': 0,
												}
			# Loop through source file
			for post in self.iterate_items(source_path):
				# Check if post contains one of the downloaded images
				if post['id'] in post_id_image_dictionary.keys():
					for img_name in post_id_image_dictionary[post['id']]:
						image = images[img_name]

						# Update description
						image['number_of_posts'] += 1
						image['description'] += '<br/><br/><b>Post ' + str(image['number_of_posts']) + '</b>'
						for field in post.keys():
							image['description'] += '<br/><br/><b>' + field + ':</b> ' + str(post[field])
						# PixPlot has a field limit of 131072
						image['description'] = image['description'][:131072]

						# Add tags or hashtags
						if image['tags']:
							image['tags'] += '|'
						if 'tags' in post.keys():
							if type(post['tags']) == list:
								image['tags'] += '|'.join(post['tags'])
							else:
								image['tags'] += '|'.join(post['tags'].split(','))
						elif 'hashtags' in post.keys():
							if type(post['hashtags']) == list:
								image['tags'] += '|'.join(post['hashtags'])
							else:
								image['tags'] += '|'.join(post['hashtags'].split(','))

						# Category could perhaps be a user inputed column...

						# If images repeat this will overwrite prior value
						# I really dislike that the download images is not a one to one with posts...
						if 'timestamp' in post.keys():
							image['year'] = dateutil.parser.parse(post['timestamp']).year

			writer = csv.DictWriter(output, fieldnames=fieldnames)
			writer.writeheader()

			# Finally, write images to metadata.csv
			for image in images:
				writer.writerow(images[image])

		self.dataset.update_status("Metadata.csv created")
		return metadata_file_path

	def get_html_page(self, url):
		"""
		Returns a html string to redirect to PixPlot.
		"""
		return f"<head><meta http-equiv='refresh' content='0; URL={url}'></head>"
