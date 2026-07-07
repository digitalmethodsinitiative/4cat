"""
Retrieves metadata on annotations for this dataset.
"""

from backend.lib.processor import BasicProcessor, ProcessorDescription
from common.lib.compatibility import Compatibility
from common.lib.outputs import Table

from datetime import datetime

class AnnotationMetadata(BasicProcessor):
	"""
	Download annotation metadata from this dataset
	"""
	type = "annotation-metadata"  # job type ID
	description = ProcessorDescription(
		title="Export annotations",
		category="Conversion",
		tags=["convert format", "annotate"],
		description="Export the annotations made on this dataset along with their metadata, such as the annotation author, timestamp, and type.",
		info=[
			"Only datasets that have annotations can be processed.",
		],
		icon="circle-info",
	)
	extension = "csv"  # extension of result file, used internally and in UI
	# a derived table
	output = Table()

	# coarse map spec (accepts any dataset); is_compatible_with (below) is the runtime
	# truth -- it requires the dataset to actually have annotations (annotation_fields)
	compatibility = Compatibility()

	@classmethod
	def is_compatible_with(cls, module=None, config=None):
		"""
		Only compatible with datasets that have annotations.

		:param module: Module to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
		"""

		return module.is_dataset() and module.annotation_fields

	def process(self):

		annotation_metadata = self.source_dataset.get_annotation_metadata()

		if not annotation_metadata:
			self.dataset.finish_as_empty("No annotations made for this dataset")
			return

		for row in annotation_metadata:
			timestamp = row["timestamp"]
			timestamp_created = row["timestamp_created"]
			row["timestamp"] = self.to_date_str(timestamp)
			row["epoch_timestamp"] = timestamp
			row["timestamp_created"] = self.to_date_str(timestamp_created)
			row["epoch_timestamp_created"] = timestamp_created

		self.write_csv_items_and_finish(annotation_metadata)

	@staticmethod
	def to_date_str(epoch_timestamp) -> str:
		return datetime.strftime(datetime.utcfromtimestamp(int(epoch_timestamp)), "%Y-%m-%d %H:%M:%S")