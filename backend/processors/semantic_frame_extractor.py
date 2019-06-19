"""
Extract semantic frames
"""
import requests

from backend.abstract.processor import BasicProcessor


class SemanticFrameExtractor(): #BasicProcessor):
	"""
	Extract Semantic Frames

	Extracts semantic frames from the (combined) corpus. This calls the
	PENELOPE-compatible API at the VUB's EHAI group which can extract
	semantic frames from utterances containing causal phrasing. The
	post-processor runs only on a previously 'stringified' dataset as
	there is comparatively little value in doing this on a per-post basis,
	but significant costs would be involved with doing that (such as needing to
	make one API call per post due to the way it is set up, which can get
	costly).

	Right now causal frames are the only ones that may be retrieved using the
	API. If others become available, an option interface could be added to this
	post-processor to allow people to choose which kind of frame to extract.
	"""
	type = "penelope-semanticframe"  # job type ID
	category = "Text analysis"  # category
	title = "Semantic frames"  # title displayed in UI
	description = "Extract semantic frames from text. This connects to the VUB's PENELOPE API to extract causal frames from the text using the framework developed by the Evolutionary and Hybrid AI (EHAI) group."  # description displayed in UI
	extension = "json"  # extension of result file, used internally and in UI
	accepts = ["stringify-posts"]  # types of result this post-processor can run on

	def process(self):
		"""
		Post the stringified dataset to the VUB API and process the results
		"""
		self.dataset.update_status("Sending post data to PENELOPE API endpoint")

		try:
			# write the result in chunks as it can be pretty large
			with requests.post("https://penelope.vub.be/semantic-frame-extractor/texts-extract-frames",
							   data=self.chunked_dataset(), stream=True,
							   headers={"Content-type": "application/json"}) as stream:
				with self.dataset.get_results_path().open("wb") as output:
					for chunk in stream.iter_content(chunk_size=1024):
						if chunk:
							output.write(chunk)

		except requests.RequestException:
			self.dataset.update_status("Trouble reaching PENELOPE endpoint; analysis halted.")
			self.dataset.finish()

		with self.dataset.get_results_path().open("a") as init:
			init.write("]")

		self.dataset.update_status("Finished")
		self.dataset.finish(self.parent.num_rows)

	def chunked_dataset(self):
		"""
		Read dataset in chunks

		Datasets can get quite large so instead of loading them into memory all
		at once, read them in chunks. This is complicated by the fact that
		we're required to send a JSON object to the API; this method takes care
		of that by including a first and last chunk that wrap the rest of the
		data in such an object.

		:return bytes:  Chunks of data
		"""
		input_file = self.source_file.open("rb")
		# wrap the input file in a JSON object
		chunk = bytes('{"texts": [""', encoding="utf-8")

		while chunk:
			yield chunk
			chunk = input_file.read(1024).replace(b"\"", b"\\\"")

		yield bytes('"], "frames": ["Causation"]}', encoding="utf-8")
		input_file.close()
