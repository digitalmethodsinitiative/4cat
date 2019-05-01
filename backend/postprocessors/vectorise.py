"""
Transform tokeniser output into vectors
"""
import zipfile
import pickle
import shutil
import os

from backend.abstract.postprocessor import BasicPostProcessor


class Vectorise(BasicPostProcessor):
	"""
	Creates word vectors from tokens
	"""
	type = "vectorise-posts"  # job type ID
	category = "Text analysis"  # category
	title = "Vectorise tokens"  # title displayed in UI
	description = "Creates word vectors for a token set. Token lists are transformed into word => frequency counts."  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI

	accepts = ["tokenise-posts"]  # query types this post-processor accepts as input

	def process(self):
		"""
		Unzips token sets, vectorises them and zips them again.
		"""

		# prepare staging area
		dirname_base = self.query.get_results_path().replace(".", "") + "-vectors"
		dirname = dirname_base
		index = 1
		while os.path.exists(dirname):
			dirname = dirname_base + "-" + str(index)
			index += 1

		os.mkdir(dirname)

		self.query.update_status("Processing token sets")
		vector_paths = []

		# go through all archived token sets and vectorise them
		with zipfile.ZipFile(self.source_file, "r") as token_archive:
			vector_sets = token_archive.namelist()
			index = 0

			for vector_set in vector_sets:
				index += 1
				vector_set_name = vector_set.split("/")[-1]  # we don't need the full path
				self.query.update_status("Processing token set %i/%i" % (index, len(vector_sets)))

				# temporarily extract file (we cannot use ZipFile.open() as it doesn't support binary modes)
				temp_path = dirname + "/" + vector_set_name
				token_archive.extract(vector_set_name, dirname)
				with open(temp_path, "rb") as binary_tokens:
					# these were saved as pickle dumps so we need the binary mode
					tokens = pickle.load(binary_tokens)
				os.unlink(temp_path)

				# all we need is a pretty straightforward frequency count
				vectors = {}
				for token in tokens:
					if token not in vectors:
						vectors[token] = 0
					vectors[token] += 1

				# dump the resulting file via pickle
				vector_path = dirname + "/" + vector_set_name
				vector_paths.append(vector_path)

				with open(vector_path, "wb") as output:
					pickle.dump(vectors, output)

		# create zip of archive and delete temporary files and folder
		self.query.update_status("Compressing results into archive")
		with zipfile.ZipFile(self.query.get_results_path(), "w") as zip:
			for vector_path in vector_paths:
				zip.write(vector_path, vector_path.split("/")[-1])
				os.unlink(vector_path)

		# delete temporary files and folder
		shutil.rmtree(dirname)

		# done!
		self.query.update_status("Finished")
		self.query.finish(len(vector_paths))
