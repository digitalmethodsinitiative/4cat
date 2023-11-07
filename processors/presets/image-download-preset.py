from backend.lib.preset import ProcessorPreset
from processors.visualisation.download_images import ImageDownloader

class ImageDownloaderPreset(ProcessorPreset):
	"""
	Run processor pipeline to annotate images
	"""
	type = "preset-image-downloader"  # job type ID
	category = "Combined processors"  # category
	title = "Download images"  # title displayed in UI
	description = "Download images and store in a a zip file. May take a while to complete as images are retrieved " \
				  "externally. Note that not always all images can be saved. For imgur galleries, only the first " \
				  "image is saved. For animations (GIFs), only the first frame is saved if available. A JSON metadata file " \
				  "is included in the output archive. \n4chan datasets should include the image_md5 column."  # description displayed in UI
	extension = "html"  # extension of result file, used internally and in UI

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
		self.dataset.log("Downloading images with parameters: {}".format(params))

		pipeline = [
			# download images
			{
				"type": "image-downloader",
				"parameters": params
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