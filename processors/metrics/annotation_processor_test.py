"""
Collapse post bodies into one long string
"""

from common.lib.helpers import UserInput
from backend.lib.processor import BasicProcessor


class AnnotatePosts(BasicProcessor):
	"""
	Merge post body into one long string
	"""
	type = "annotate-posts"  # job type ID
	category = "Metrics"  # category
	title = "Annotation test"  # title displayed in UI
	description = "Ya know"  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	options = {
		"overwrite": {
			"type": UserInput.OPTION_TOGGLE,
			"default": False,
			"help": "Overwrite existing annotations by this processor?"
		},
		"field_label": {
			"type": UserInput.OPTION_TEXT,
			"default": ""
		}
	}

	def process(self):
		import random
		annotations = []
		with self.dataset.get_results_path().open("w") as results:

			for post in self.source_dataset.iterate_items(self):

				annotation = {"item_id": post["id"],
							  "label": self.parameters.get("field_label", ""),
							  "value": random.randrange(1, 1000000)}

				annotations.append(annotation)

		self.write_annotations(annotations, overwrite=self.parameters.get("overwrite", False))
		self.dataset.finish(1)