"""
Extract neologisms
"""
from backend.lib.preset import ProcessorPreset
from common.lib.compatibility import Compatibility
from processors.metrics.count_posts import CountPosts


class MonthlyHistogramCreator(ProcessorPreset):
	"""
	Run processor pipeline to extract neologisms
	"""
	type = "preset-histogram"  # job type ID
	category = "Combined processors"  # category. 'Combined processors' are always listed first in the UI.
	title = "Histogram"  # title displayed in UI
	description = "Create a histogram that shows the number of items over time."  # description displayed in UI
	extension = "svg"

	# Allow on top-level CSV/NDJSON datasets
	compatibility = Compatibility(top_dataset_only=True, extensions={"csv", "ndjson"})

	@classmethod
	def get_options(cls, parent_dataset=None, config=None):
		count_options = CountPosts.get_options(parent_dataset=parent_dataset, config=config)
		# Cannot graph overall counts (or rather it would be a single bar)
		if "all" in count_options["timeframe"]["options"]:
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
			header = f"Items per {query['timeframe']}"

		pipeline = [
			# first, count activity per timeframe
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