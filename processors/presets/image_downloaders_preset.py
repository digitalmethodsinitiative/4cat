from backend.lib.preset import ProcessorPreset
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
		return ImageDownloader.is_compatible_with(module=module, user=user)

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
		return TelegramImageDownloader.is_compatible_with(module=module, user=user)

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
		return TikTokImageDownloader.is_compatible_with(module=module, user=user)

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