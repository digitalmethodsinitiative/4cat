from backend.lib.preset import ProcessorPreset
from common.lib.dataset import DataSet
from processors.visualisation.download_images import ImageDownloader
from processors.visualisation.download_telegram_images import TelegramImageDownloader
from processors.visualisation.download_tiktok import TikTokImageDownloader


class ImageDownloaderPreset(ProcessorPreset):
	"""
	Run processor pipeline to annotate images
	"""
	type = "preset-image-downloader"  # job type ID
	category = "Visual"  # category
	title = "Download images"  # title displayed in UI
	description = "Download images and store in a a zip file. May take a while to complete as images are retrieved " \
				  "externally. Note that not always all images can be saved. For imgur galleries, only the first " \
				  "image is saved. For animations (GIFs), only the first frame is saved if available. A JSON metadata file " \
				  "is included in the output archive. \n4chan datasets should include the image_md5 column."  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI

	@classmethod
	def is_compatible_with(cls, module=None, user=None):
		"""
        Allow processor on top image rankings

        :param module: Dataset or processor to determine compatibility with
        """
		return (module.type == "top-images" or module.is_from_collector()) \
			and module.type not in ["tiktok-search", "tiktok-urls-search", "telegram-search"]

	@classmethod
	def get_options(cls, parent_dataset=None, user=None):
		return ImageDownloader.get_options(parent_dataset=parent_dataset, user=user)

	def get_processor_pipeline(self):
		params = self.parameters

		pipeline = [
			# download images
			{
				"type": "image-downloader",
				"parameters": {"attach_to":self.dataset.key, **params}
			},
			# then create plot
			{
				"type": "custom-image-plot",
				"parameters": {
					"amount": 0
				}
			},

		]

		return pipeline

class TelegramImageDownloaderPreset(ProcessorPreset):
	"""
	Run processor pipeline to annotate images
	"""
	type = "preset-image-downloader-telegram"  # job type ID
	category = "Visual"  # category
	title = "Download Telegram images"  # title displayed in UI
	description = "Download images and store in a zip file. Downloads through the Telegram API might take a while. " \
				  "Note that not always all images can be retrieved. A JSON metadata file is included in the output " \
				  "archive."  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI

	@classmethod
	def is_compatible_with(cls, module=None, user=None):
		"""
        Allow processor on Telegram datasets with required info

        :param module: Dataset or processor to determine compatibility with
        """
		if type(module) is DataSet:
			# we need these to actually instantiate a telegram client and
			# download the images
			return module.type == "telegram-search" and \
				"api_phone" in module.parameters and \
				"api_id" in module.parameters and \
				"api_hash" in module.parameters
		else:
			return module.type == "telegram-search"

	@classmethod
	def get_options(cls, parent_dataset=None, user=None):
		return TelegramImageDownloader.get_options(parent_dataset=parent_dataset, user=user)

	def get_processor_pipeline(self):
		params = self.parameters

		pipeline = [
			# download images
			{
				"type": "image-downloader-telegram",
				"parameters": {"attach_to":self.dataset.key, **params}
			},
			# then create plot
			{
				"type": "custom-image-plot",
				"parameters": {
					"amount": 0
				}
			},

		]

		return pipeline

class TikTokImageDownloaderPreset(ProcessorPreset):
	"""
	Run processor pipeline to annotate images
	"""
	type = "preset-image-downloader-tiktok"  # job type ID
	category = "Visual"  # category
	title = "Download TikTok Images"  # title displayed in UI
	description = "Downloads video/music thumbnails for TikTok; refreshes TikTok data if URLs have expired"
	extension = "zip"  # extension of result file, used internally and in UI

	@classmethod
	def is_compatible_with(cls, module=None, user=None):
		"""
        Allow processor on Telegram datasets with required info

        :param module: Dataset or processor to determine compatibility with
        """
		return module.type in ["tiktok-search", "tiktok-urls-search"]

	@classmethod
	def get_options(cls, parent_dataset=None, user=None):
		return TikTokImageDownloader.get_options(parent_dataset=parent_dataset, user=user)

	def get_processor_pipeline(self):
		params = self.parameters

		pipeline = [
			# download images
			{
				"type": "image-downloader-tiktok",
				"parameters": {"attach_to":self.dataset.key, **params}
			},
			# then create plot
			{
				"type": "custom-image-plot",
				"parameters": {
					"amount": 0
				}
			},

		]

		return pipeline