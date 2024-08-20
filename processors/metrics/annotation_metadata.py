"""
Retrieves metadata on annotations for this dataset.
"""

from backend.lib.processor import BasicProcessor

from datetime import datetime

class AnnotationMetadata(BasicProcessor):
	"""
	Download annotation metadata from this dataset
	"""
	type = "annotation-metadata"  # job type ID
	category = "Annotations"  # category
	title = "Annotation metadata"  # title displayed in UI
	description =	"Download all the metadata about annotations for this dataset. " \
					"Includes information like who made the annotation, when it was " \
					"last edited, etcetera." # description displayed in UI
	extension = 'csv'  # extension of result file, used internally and in UI

	def process(self):

		annotation_metadata = self.source_dataset.get_annotation_metadata()

		if not annotation_metadata:
			self.dataset.finish_with_error("No annotations made for this dataset")

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