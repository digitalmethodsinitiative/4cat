"""
Extract neologisms
"""
from backend.lib.preset import ProcessorPreset


class MonthlyHistogramCreator(ProcessorPreset):
	"""
	Run processor pipeline to extract neologisms
	"""
	type = "preset-histogram"  # job type ID
	category = "Combined processors"  # category. 'Combined processors' are always listed first in the UI.
	title = "Monthly histogram"  # title displayed in UI
	description = "Generates a histogram with the number of items per month."  # description displayed in UI
	extension = "svg"

	@staticmethod
	def is_compatible_with(module=None, config=None):
		"""
        Determine compatibility

        This preset is compatible with any module that has countable items (via count-posts)

        :param Dataset module:  Module ID to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        :return bool:
        """
		return module.is_top_dataset() and module.get_extension() in ("csv", "ndjson")

	def get_processor_pipeline(self):
		"""
		This queues a series of post-processors to visualise over-time
		activity.
		"""

		header = "'" + self.source_dataset.data["query"] + "': Items per month"
		if len(header) > 40:
			header = "Items per month"

		pipeline = [
			# first, count activity per month
			{
				"type": "count-posts",
				"parameters": {
					"timeframe": "month"
				}
			},
			# then, render it
			{
				"type": "histogram",
				"parameters": {
					"header": header
				}
			}
		]

		return pipeline