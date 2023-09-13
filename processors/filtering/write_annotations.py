"""
Write annotations to a dataset
"""
from processors.filtering.base_filter import BasicProcessor
from common.lib.helpers import UserInput

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"


class WriteAnnotations(BasicProcessor):
	"""
	Write annotated data from the Explorer to a dataset.
	"""
	type = "write-annotations"  # job type ID
	category = "Filtering"  # category
	title = "Write annotations"  # title displayed in UI
	description = "Writes annotations from the Explorer to the dataset. Each input field will get a column. This creates a new dataset."  # description displayed in UI

	options = {
		"to-lowercase": {
			"type": UserInput.OPTION_TOGGLE,
			"default": False,
			"help": "Convert annotations to lowercase"
		}
	}

	@classmethod
	def is_compatible_with(cls, module=None, user=None):
		"""
		Allow processor on CSV files

		:param module: Module to determine compatibility with
		"""
		return module.is_top_dataset()

	def process(self):
		"""
		Create a generator to iterate through items that can be passed to create either a csv or ndjson. Use
		`for original_item, mapped_item in self.source_dataset.iterate_mapped_items(self)` to iterate through items
		and yield `original_item`.

		:return generator:
		"""
		# Load annotation fields and annotations
		annotations = self.dataset.get_annotations()
		annotation_fields = self.dataset.get_annotation_fields()
		
		# If there are no fields or annotations saved, we're done here
		if not annotation_fields:
			self.dataset.update_status("This dataset has no annotation fields saved.")
			self.dataset.finish(0)
			return 
		if not annotations:
			self.dataset.update_status("This dataset has no annotations saved.")
			self.dataset.finish(0)
			return

		annotation_labels = [v["label"] for v in annotation_fields.values()]

		to_lowercase = self.parameters.get("to-lowercase", False)
		annotated_posts = set(annotations.keys())
		post_count = 0
		
		# We first need to get a list of post IDs to create a list of new data.
		# This is somewhat redundant since we'll have to loop through the dataset
		# multiple times.

		# Create dictionary with annotation labels as keys and lists of data as values
		new_data = {annotation_label: [] for annotation_label in annotation_labels}

		for item in self.source_dataset.iterate_items(self):
			post_count += 1

			# Do some loops so we have empty data for all annotation fields
			if str(item["id"]) in annotations:

				for label in annotation_labels:
					if label in annotations[item["id"]]:
						annotation = annotations[item["id"]][label]

						# We join lists (checkboxes)
						if isinstance(annotation, list):
							annotation = ", ".join(annotation)
						# Convert to lowercase if indicated
						if to_lowercase:
							annotation = annotation.lower()

						new_data[label].append(annotation)
					else:
						new_data[label].append("")
			else:
				for label in annotation_labels:
					new_data[label].append("")

			if post_count % 2500 == 0:
				self.dataset.update_status("Processed %i posts" % post_count)
				self.dataset.update_progress(post_count / self.source_dataset.num_rows)

		# Write to top dataset
		for label, values in new_data.items():
			self.add_field_to_parent("annotation_" + label, values, which_parent=self.source_dataset, update_existing=True)
		
		self.dataset.update_status("Annotations written to parent dataset.")
		self.dataset.finish(self.source_dataset.num_rows)