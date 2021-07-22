"""
Extract semantic frames
"""
import requests
import json
import time
import csv
import re

from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException

__author__ = "Stijn Peeters"
__credits__ = ["Katrien Beuls", "Paul van Eecke"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

class SemanticFrameExtractor(BasicProcessor):
	"""
	Extract Semantic Frames

	Extracts semantic frames from the (combined) corpus. This calls the
	PENELOPE-compatible API at the VUB's EHAI group which can extract
	semantic frames from utterances containing causal phrasing.

	Right now causal frames are the only ones that may be retrieved using the
	API. If others become available, an option interface could be added to this
	post-processor to allow people to choose which kind of frame to extract.
	"""
	type = "penelope-semanticframe"  # job type ID
	category = "Text analysis"  # category
	title = "Semantic frames"  # title displayed in UI
	description = "Extract semantic frames from text. This connects to the VUB's PENELOPE API to extract causal frames from the text using the framework developed by the Evolutionary and Hybrid AI (EHAI) group."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor on sets of sentences

		:param module: Dataset or processor to determine compatibility with
		"""
		return module.type == "sentence-split"

	def process(self):
		"""
		Post the stringified dataset to the VUB API and process the results
		"""
		self.dataset.update_status("Sending post data to PENELOPE API endpoint")

		chunk_size = 50  # results may vary
		chunk = []
		processed = 0
		entities = 0

		# the API has some problems with fancy quote characters, etc, and they
		# presumably don't make a difference for the results, so strip
		# everything that's not plain text (or a few non-harmful characters)
		# would need updating if languages other than English are supported
		non_alpha = re.compile(r"[^a-zA-Z0-9%!?+*&@#)(/:;, -]")

		with self.dataset.get_results_path().open("w") as output:
			writer = csv.DictWriter(output, fieldnames=("sentence", "utterance", "frameEvokingElement", "cause", "effect"))
			writer.writeheader()
			reader = self.iterate_items(self.source_file)
			while True:
				# the API can't handle too many sentences at once, so send
				# them in chunks
				self.dataset.update_status("%i sentences processed via PENELOPE API..." % processed)
				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while interfacing with PENELOPE API")

				end_of_the_line = False
				try:
					post = reader.__next__()
					sentence = non_alpha.sub("", post["sentence"])
					processed += 1
					if not sentence:
						# could be that it's just symbols, no text
						continue

					chunk.append(sentence)
				except StopIteration:
					end_of_the_line = True

				if len(chunk) == chunk_size or end_of_the_line:
					payload = {"texts": chunk, "frames": ["Causation"]}
					response = requests.post("https://penelope.vub.be/semantic-frame-extractor/texts-extract-frames",
											 data=json.dumps(payload), headers={"Content-type": "application/json"})

					if response.status_code != 200:
						self.log.warning("PENELOPE Semantic Frame API crashed for chunk %s" % repr(chunk))
						self.dataset.update_status("PENELOPE API response could not be parsed.")
						entities = 0
						break

					# filter response to only include those sentences that
					# actually contained any semantic frames
					for frameset_list in response.json().get("frameSets", []):
						if not frameset_list:
							continue

						for frameset in frameset_list:
							if not frameset.get("entities", None):
								continue

							for entity in frameset.get("entities"):
								entities += 1
								writer.writerow({
									"sentence": frameset["utterance"],
									"utterance": entity.get("utterance", ""),
									"frameEvokingElement": entity.get("frameEvokingElement", ""),
									"cause": entity.get("cause", ""),
									"effect": entity.get("effect", "")
								})

					chunk = []

				if end_of_the_line:
					self.dataset.update_status("Finished")
					break
				else:
					# let 'em breathe
					time.sleep(1)

		self.dataset.finish(entities)