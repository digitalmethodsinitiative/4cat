"""
4Chan image downloader
"""
import requests
import random
import time

from backend.lib.worker import BasicWorker


class ImageDownloader(BasicWorker):
	"""
	Image downloader

	This downloads the images from 4chan posts that were scraped and saves them to disk.

	todo: shrink images or keep archive at a manageable size otherwise
	"""
	type = "image"
	pause = 1
	max_workers = 3

	def work(self):
		"""
		Get image downloader job, and download given image

		If no images need to be downloaded, wait a while and try again.

		:return:
		"""
		job = self.queue.get_job("image")
		if not job:
			self.log.debug("Image downloader has no jobs, sleeping for 10 seconds")
			time.sleep(10)
			return

		try:
			url = "http://i.4cdn.org/%s/%s%s" % (job["details"]["board"], job["details"]["tim"], job["details"]["ext"])
			image = requests.get(url)
		except requests.HTTPError:
			# something wrong with our internet connection? or blocked by 4chan?
			# try again in a minute
			self.queue.release_job(job, delay=random.choice(range(15,45)))
			return

		if image.status_code == 404:
			# image deleted - mark in database? either way, can't complete job
			self.queue.finish_job(job)
			return

		if image.status_code != 200:
			# try again in 30 seconds
			if job["attempts"] > 2:
				self.log.warning("Could not download image %s after x retries (last response code %s), aborting",
								 (url, image.status_code))
				self.queue.finish_job(job)
			else:
				self.log.info(
					"Got response code %s while trying to download image %s, retrying later" % (image.status_code, url))
				self.queue.release_job(job, delay=random.choice(range(5, 35)))

			return

		# write image to disk
		image_location = job["details"]["destination"]
		with open(image_location, 'wb') as file:
			for chunk in image.iter_content(1024):
				file.write(chunk)

		# done!
		self.queue.finish_job(job)
