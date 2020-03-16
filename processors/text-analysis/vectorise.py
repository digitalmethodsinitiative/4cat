"""
Transform tokeniser output into vectors
"""
import zipfile
import pickle
import shutil
import itertools

from backend.lib.exceptions import ProcessorInterruptedException
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

	input = "zip"
	output = "zip"

	accepts = ["tokenise-posts"]  # query types this post-processor accepts as input

	def process(self):
		"""
		Unzips token sets, vectorises them and zips them again.
		"""

		# prepare staging area
		results_path = self.dataset.get_temporary_path()
		results_path.mkdir()

		self.dataset.update_status("Processing token sets")
		vector_paths = []

		# go through all archived token sets and vectorise them
		with zipfile.ZipFile(self.source_file, "r") as token_archive:
			vector_sets = token_archive.namelist()
			index = 0

			for vector_set in vector_sets:
				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while processing token sets")

				index += 1
				vector_set_name = vector_set.split("/")[-1]  # we don't need the full path
				self.dataset.update_status("Processing token set %i/%i" % (index, len(vector_sets)))

				# temporarily extract file (we cannot use ZipFile.open() as it doesn't support binary modes)
				temp_path = results_path.joinpath(vector_set_name)
				token_archive.extract(vector_set_name, results_path)
				with temp_path.open("rb") as binary_tokens:
					# these were saved as pickle dumps so we need the binary mode
					tokens = pickle.load(binary_tokens)

				temp_path.unlink()

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
				vector_path = results_path.joinpath(vector_set_name)
				vector_paths.append(vector_path)

				with vector_path.open("wb") as output:
					pickle.dump(vectors_list, output)

		# create zip of archive and delete temporary files and folder
		self.dataset.update_status("Compressing results into archive")
		with zipfile.ZipFile(self.dataset.get_results_path(), "w") as zip:
			for vector_path in vector_paths:
				zip.write(vector_path, vector_path.name)
				vector_path.unlink()

		# delete temporary files and folder
		shutil.rmtree(results_path)

		# done!
		self.dataset.update_status("Finished")
		self.dataset.finish(len(vector_paths))
