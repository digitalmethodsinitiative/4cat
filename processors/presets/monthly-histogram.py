"""
Extract neologisms
"""
from backend.abstract.preset import ProcessorPreset


class MonthlyHistogramCreator(ProcessorPreset):
	"""
	Run processor pipeline to extract neologisms
	"""
	type = "preset-histogram"  # job type ID
	category = "Presets"  # category. 'Presets' are always listed first in the UI.
	title = "Monthly histogram"  # title displayed in UI
	description = "Generates a histogram (bar graph) that aggregates the number of posts per unit of time to provide an impression of over-time activity in the data set"  # description displayed in UI
	extension = "svg"

	def get_processor_pipeline(self):
		"""
		This queues a series of post-processors to visualise over-time
		activity.
		"""

		header = "'" + self.source_dataset.data["query"] + "': Posts per month"
		if len(header) > 40:
			header = "Posts per month"

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