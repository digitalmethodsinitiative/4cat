"""
Transform tokeniser output into vectors
"""
import json
import pickle
import itertools

from backend.abstract.processor import BasicProcessor

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

class Vectorise(BasicProcessor):
	"""
	Creates word vectors from tokens
	"""
	type = "vectorise-tokens"  # job type ID
	category = "Text analysis"  # category
	title = "Vectorise tokens"  # title displayed in UI
	description = "Creates word vectors for a token set. Token lists are transformed into word => frequency counts."  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor on token sets

		:param module: Dataset or processor to determine compatibility with
		"""
		return module.type == "tokenise-posts"

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
		for token_file in self.iterate_archive_contents(self.source_file):
			index += 1
			vector_set_name = token_file.stem  # we don't need the full path
			self.dataset.update_status("Processing token set %i (%s)" % (index, vector_set_name))

			# we support both pickle and json dumps of vectors
			token_unpacker = pickle if vector_set_name.split(".")[-1] == "pb" else json
			write_mode = "wb" if token_unpacker is pickle else "w"

			# temporarily extract file (we cannot use ZipFile.open() as it doesn't support binary modes)
			with token_file.open("rb") as binary_tokens:
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
