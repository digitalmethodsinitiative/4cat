"""
Write annotations to a dataset
"""

import csv
import json

from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput

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
	title = "Write annotations"  # title displayed in UI
	description = "Writes annotations from the Explorer to the dataset. Each input field will get a column. This creates a new dataset."  # description displayed in UI
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
		return module.is_top_dataset()

	def process(self):
		"""
		Gets the annotation fields from the dataset table and adds them as columns.
		Then loops through the annotations from the annotations table and adds the values, if given. 
		
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

		count = 0
		updated_posts = self.collect_annotation(annotations, annotation_labels, count)

		self.dataset.update_status("Writing annotations")
		# Get parent extension
		extension = self.source_dataset.get_extension()

		# Write the posts
		num_posts = 0
		if extension == "csv":
			with self.dataset.get_results_path().open("w", encoding="utf-8") as outfile:
				writer = None
				for post in updated_posts:
					if not writer:
						# get header row and add input fields to them, if not already present.
						fieldnames = post.keys()
						for label in annotation_labels:
							if label not in fieldnames:
								fieldnames.append(label)
						writer = csv.DictWriter(outfile, fieldnames=fieldnames)
						writer.writeheader()
					writer.writerow(post)
					num_posts += 1
		elif extension == "ndjson":
			with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as outfile:
				for post in updated_posts:
					outfile.write(json.dumps(post) + "\n")
					num_posts += 1
		else:
			self.dataset.update_status("Annotations cannot be added directly to datasource of type %s" % extension, is_final=True)
			return

		if num_posts == 0:
			self.dataset.update_status("No items matched your criteria", is_final=True)

		self.dataset.update_status("Created a new dataset with annotations for %s posts." % count)
		self.dataset.finish(num_posts)

	def collect_annotation(self, annotations, annotation_labels, count=0):
		"""
		Loop through posts, adds annotation fields, updates them if necessary, and returns updated posts

		This will overwrite existing fields! annotation_labels should be checked prior to ensure they do not
		correspond to original field names.
		"""
		# Collect item_mapper for use with filter
		item_mapper = None
		own_processor = self.source_dataset.get_own_processor()
		if hasattr(own_processor, "map_item"):
			item_mapper = own_processor.map_item

		to_lowercase = self.parameters.get("to-lowercase", False)
		annotated_posts = set(annotations.keys())
		post_count = 0
		# iterate through posts and check if they appear in the annotations
		for post in self.source_dataset.iterate_items(self, bypass_map_item=True):
			post_count += 1

			# Save original to yield
			original_post = post.copy()

			# Map item for filter
			if item_mapper:
				post = item_mapper(post)

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

						original_post[field] = val
					else:
						original_post[field] = ""

			# Write empty values if this post has not been annotated
			else:
				for field in annotation_labels:
					original_post[field] = ""

			yield original_post

	def after_process(self):
		super().after_process()

		# Request standalone
		self.create_standalone()
