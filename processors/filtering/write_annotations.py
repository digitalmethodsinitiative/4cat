"""
Write annotations to a dataset
"""

import csv
from pathlib import Path

from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput

import config

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)


class WriteAnnotations(BasicProcessor):
	"""
	Write annotated data from the Explorer to a dataset.
	"""
	type = "write-annotations"  # job type ID
	category = "Filtering"  # category
	title = "Write annotations to dataset"  # title displayed in UI
	description = "Writes annotated fields to the dataset, with each input field as a column."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI
	
	options = {
		"to-lowercase": {
			"type": UserInput.OPTION_TOGGLE,
			"default": False,
			"help": "Convert annotations to lowercase"
		}
	}

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor on CSV files

		:param module: Dataset or processor to determine compatibility with
		"""
		return module.is_top_dataset() and module.get_extension() == "csv"

	def process(self):
		"""
		Gets the annotation fields from the dataset table and adds them as columns.
		Then loops through the annotations from the annotations table and adds the values, if given. 
		
		"""
		
		# Load annotation fields and annotations
		annotations = self.dataset.get_annotations()
		annotation_fields = self.dataset.get_annotation_fields()
		annotation_labels = [v["label"] for v in annotation_fields.values()]

		to_lowercase = self.parameters.get("to-lowercase", False)
		
		# If there are no fields or annotations saved, we're done here
		if not annotation_fields:
			self.dataset.update_status("This dataset has no annotation fields saved.")
			self.dataset.finish(0)
			return 
		if not annotations:
			self.dataset.update_status("This dataset has no annotations saved.")
			self.dataset.finish(0)
			return

		self.dataset.update_status("Writing annotations")
		with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as output:
			
			# get header row and add input fields to them, if not already present.
			fieldnames = self.get_item_keys(self.source_file)
			for label in annotation_labels:
				if label not in fieldnames:
					fieldnames.append(label)

			# Start the output file
			writer = csv.DictWriter(output, fieldnames=fieldnames)
			writer.writeheader()

			annotated_posts = set(annotations.keys())
			count = 0
			post_count = 0

			# iterate through posts and check if they appear in the annotations
			for post in self.iterate_items(self.source_file):
				
				post_count += 1

				# Write the annotations to this row if they're present
				if post["id"] in annotated_posts:
					
					count += 1
					post_annotations = annotations[post["id"]]

					# We're adding (empty) values for every field
					for field in annotation_labels:

						if field in post_annotations:

							val = post_annotations[field]

							# We join lists (checkboxes)
							if isinstance(val, list):
								val = ", ".join(val)
							# Convert to lowercase if indicated
							if to_lowercase:
								val = val.lower()

							post[field] = val
						else:
							post[field] = ""

				# Write empty values if this post has not been annotated
				else:
					for field in annotation_labels:
						post[field] = ""

				writer.writerow(post)

		self.dataset.update_status("Created dataset with annotations for %s posts." % count)
		self.dataset.finish(post_count)

	def after_process(self):
		super().after_process()

		# Request standalone
		self.create_standalone()
