"""
Create an PixPlot of downloaded images
"""
import shutil
import requests
import time
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
		Allow processor on token sets

		:param module: Dataset or processor to determine compatibility with
		"""
		return module.type == "image-downloader"

	def process(self):
		"""
		This takes a 4CAT results file as input, copies the images to a temp
		folder,
		"""
		self.dataset.update_status("Reading source file")

		# is there anything to put on a wall?
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
		self.log.info('staging area: ' + str(staging_area))

		# Prep arguments for pixplot
		# TODO:will need to add metadata somehow
		output_directory = '/usr/src/app/data/plots/' + self.dataset.key
		data = {"args": ['--images', str(staging_area)+"/*.jpg", '--out_dir', output_directory]}
		# need to make adaptable port
		pixplot_api = "https" if config.FlaskConfig.SERVER_HTTPS else "http"
		pixplot_api += '://4cat_pixplot' + ":" + "4000" + "/api/"

		# Send request
		self.dataset.update_status("Sending request and data to pixplot")
		resp = requests.post(pixplot_api+"pixplot", json=data)
		self.log.info('PixPlot request status: ' + str(resp.status_code))

		# Wait for pixplot to complete
		# We just return the HTML, but something needs to clean up the staging_area
		self.dataset.update_status("PixPlot generating results")
		while True:
			time.sleep(10)
			result = requests.get(resp.json()['result_url'])
			if 'status' in result.json().keys() and result.json()['status'] == 'running':
				# Still running
				continue
			elif 'report' in result.json().keys() and result.json()['report'][-6:-1] == 'Done!':
				# Complete without error
				self.dataset.update_status("PixPlot Completed!")
				self.log.info('PixPlot saved to: ' + output_directory)
				break
			else:
				# Something botched
				self.dataset.update_status("PixPlot Error")
				self.log.info("PixPlot Error" + result.json()['report'].split('Error')[-1])
				break

		if staging_area:
			shutil.rmtree(staging_area)

		# Create HTML file
		url = "https" if config.FlaskConfig.SERVER_HTTPS else "http"
		url += '://' + config.FlaskConfig.SERVER_NAME.split(':')[0] + ':' + '4000'
		url += '/plots/' + self.dataset.key + '/index.html'
		html_file = self.get_html_page(url)

		# Write HTML file
		with self.dataset.get_results_path().open("w", encoding="utf-8") as output_file:
			output_file.write(html_file)

		# Finish
		self.dataset.update_status("Finished")
		self.dataset.finish(1)


	def get_html_page(self, url):
		"""
		Returns a html string to redirect to PixPlot.
		"""
		return f"<head><meta http-equiv='refresh' content='0; URL={url}'></head>"
