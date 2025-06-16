"""
Extract neologisms
"""
from backend.lib.preset import ProcessorPreset
from processors.metrics.count_posts import CountPosts
import copy


class MonthlyHistogramCreator(ProcessorPreset):
	"""
	Run processor pipeline to extract neologisms
	"""
	type = "preset-histogram"  # job type ID
	category = "Combined processors"  # category. 'Combined processors' are always listed first in the UI.
	title = "Histogram"  # title displayed in UI
	description = "Visualize graphically the number of posts over time."  # description displayed in UI
	extension = "svg"

	@staticmethod
	def is_compatible_with(module=None, user=None):
		"""
        Determine compatibility

        This preset is compatible with any module that has countable items (via count-posts)

        :param Dataset module:  Module ID to determine compatibility with
        :return bool:
        """
		return module.is_top_dataset() and module.get_extension() in ("csv", "ndjson")
	
	@classmethod
	def get_options(cls, parent_dataset=None, user=None):
		count_options = copy.deepcopy(CountPosts.get_options(parent_dataset=parent_dataset, user=user))
		if "all" in count_options["timeframe"].get("options", {}):
			# Cannot graph overall counts (or rather it would be a single bar)
			count_options["timeframe"]["options"].pop("all")
		return count_options

	def get_processor_pipeline(self):
		"""
		This queues a series of post-processors to visualise over-time
		activity.
		"""
		query = self.parameters.copy()
		header = self.source_dataset.get_label() + f": Items per {query['timeframe']}"
		if len(header) > 40:
			header = "Items per month"

		pipeline = [
			# first, count activity per month
			{
				"type": "count-posts",
				"parameters": {
					**query
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