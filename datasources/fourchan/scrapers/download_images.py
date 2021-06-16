"""
4Chan image downloader
"""
import requests
import random

from backend.abstract.worker import BasicWorker

import config


class ImageDownloader(BasicWorker):
	"""
	Image downloader

	This downloads the images from 4chan posts that were scraped and saves them to disk.

	todo: shrink images or keep archive at a manageable size otherwise
	"""
	type = "4chan-image"
	pause = 1
	max_workers = 10

	def work(self):
		"""
		Get image downloader job, and download given image

		If no images need to be downloaded, wait a while and try again.

		:return:
		"""
		try:
			url = "http://i.4cdn.org/%s/%s%s" % (self.job.details["board"], self.job.details["tim"], self.job.details["ext"])
			image = requests.get(url, timeout=config.SCRAPE_TIMEOUT * 3)
		except (requests.exceptions.RequestException, ConnectionRefusedError) as e:
			# something wrong with our internet connection? or blocked by 4chan?
			# try again in a minute
			if self.job.data["attempts"] > 2:
				self.log.error("Could not download image %s after 2 retries (%s), aborting" % (self.job.details["tim"], e))
				self.job.finish()
			else:
				self.log.info("HTTP Error %s while downloading image, retrying later" % e)
				self.job.release(delay=random.choice(range(15,45)))
			return

		if image.status_code == 404:
			# image deleted - mark in database? either way, can't complete job
			self.job.finish()
			return

		if image.status_code != 200:
			# try again in 30 seconds
			if self.job.data["attempts"] > 2:
				self.log.error("Could not download image %s after 2 retries (last response code %i), aborting" %
								 (url, image.status_code))
				self.job.finish()
			else:
				self.log.info(
					"Got response code %i while trying to download image %s, retrying later" % (image.status_code, url))
				self.job.release(delay=random.choice(range(5, 35)))

			return

		# write image to disk
		image_location = self.job.details["destination"]
		with open(image_location, 'wb') as file:
			for chunk in image.iter_content(1024):
				file.write(chunk)

		# done!
		self.job.finish()
