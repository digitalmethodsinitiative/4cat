"""
Transform tokeniser output into vectors
"""
import json
import pickle
import itertools

from backend.lib.processor import BasicProcessor, ProcessorDescription
from common.lib.compatibility import Compatibility
from common.lib.outputs import Archive

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

class Vectorise(BasicProcessor):
	"""
	Creates word vectors from tokens
	"""
	type = "vectorise-tokens"  # job type ID
	description = ProcessorDescription(
		title="Count words",
		category="Text analysis",
		tags=["counts"],
		description="Count how often each token appears in the dataset, producing a bag of words per token set. The counts are sorted from most to least frequent.",
		icon="list-ol",
	)
	extension = "zip"  # extension of result file, used internally and in UI
	# a zip archive of data files
	output = Archive()

	# Allow processor on token sets
	compatibility = Compatibility(types={"tokenise-posts"}, preferred_followups=["vector-ranker"])

	def process(self):
		"""
		Unzips token sets, vectorises them and zips them again.
		"""

		# prepare staging area
		staging_area = self.dataset.get_staging_area()

		self.dataset.update_status("Processing token sets")
		vector_paths = []

		# go through all archived token sets and vectorise them
		index = 0
		for packed_tokens in self.source_dataset.iterate_items(self):
			if packed_tokens.file.name == '.token_metadata.json':
				# Skip metadata
				continue
			index += 1
			vector_set_name = packed_tokens.file.stem  # we don't need the full path
			self.dataset.update_status("Processing token set %i (%s)" % (index, vector_set_name))
			self.dataset.update_progress(index / self.source_dataset.num_rows)

			# we support both pickle and json dumps of vectors
			token_unpacker = pickle if vector_set_name.split(".")[-1] == "pb" else json
			write_mode = "wb" if token_unpacker is pickle else "w"

			# temporarily extract file (we cannot use ZipFile.open() as it doesn't support binary modes)
			with packed_tokens.file.open("rb") as binary_tokens:
				# these were saved as pickle dumps so we need the binary mode
				tokens = token_unpacker.load(binary_tokens)

				# flatten token list first - we don't have to separate per post
				tokens = list(itertools.chain.from_iterable(tokens))

				# all we need is a pretty straightforward frequency count
				vectors = {}
				for token in tokens:
					if token not in vectors:
						vectors[token] = 0
					vectors[token] += 1

				# convert to vector list
				vectors_list = [[token, vectors[token]] for token in vectors]

				# sort
				vectors_list = sorted(vectors_list, key=lambda item: item[1], reverse=True)

				# dump the resulting file via pickle
				vector_path = staging_area.joinpath(vector_set_name)
				vector_paths.append(vector_path)

				with vector_path.open(write_mode) as output:
					token_unpacker.dump(vectors_list, output)

		# create zip of archive and delete temporary files and folder
		self.write_archive_and_finish(staging_area)
