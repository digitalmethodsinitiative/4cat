"""
Create a csv with tf-idf ranked terms
"""
import os
import pickle

from backend.lib.helpers import UserInput
from backend.abstract.postprocessor import BasicPostProcessor

from csv import DictReader
from sklearn.feature_extraction.text import TfidfVectorizer

import config

class tfIdf(BasicPostProcessor):
	"""
	
	Get tf-idf terms

	"""
	type = "tfidf"  # job type ID
	category = "Text analysis"  # category
	title = "Tf-idf"  # title displayed in UI
	description = "Get the tf-idf values of tokenised text. Works better with more documents (e.g. day-separated)."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI
	accepts = ["tokenise-posts"]  # query types this post-processor accepts as input

	options = {
		"n_size": {
			"type": UserInput.OPTION_CHOICE,
			"default": "1 word",
			"options": {"1": "1 word", "2": "2 words"},
			"help": "Amount of words to return (tf-idf unigrams or bigrams)"
		},
		"min_df": {
			"type": UserInput.OPTION_TEXT,
			"default": 1,
			"min": 1,
			"max": 10000,
			"help": "The maximum amount of days/months/years a term may appear in. Useful for fetching rare terms that are not constantly prevalent throughout dataset."
		},
		"max_df": {
			"type": UserInput.OPTION_TEXT,
			"default": 999,
			"min": 1,
			"max": 10000,
			"help": "The minimum amount of days/months/years a term should appear in. Useful for filtering out very sporadic terms."
		},
		"max_output": {
			"type": UserInput.OPTION_TEXT,
			"default": "25",
			"min": 1,
			"max": 100,
			"help": "Output number - The amount of words to return per timeframe"
		}
	}
	
	def process(self):
		"""
		Unzips and appends tokens to fetch and write a tf-idf matrix
		"""

		# Validate and process user inputs - parse to int
		parameters = [int(parameter) for parameter in self.parameters]

		tokens = OrderedDict()

		# Go through all archived token sets and generate collocations for each
		with zipfile.ZipFile(self.source_file, "r") as token_archive:
			token_sets = token_archive.namelist()
			index = 0

			# Loop through the tokens (can also be a single set)
			for tokens_name in token_sets:
				
				# Get the date
				date_string = tokens_name.split('.')[0]
				
				# Temporarily extract file (we cannot use ZipFile.open() as it doesn't support binary modes)
				temp_path = dirname + "/" + tokens_name
				token_archive.extract(tokens_name, dirname)
				with open(temp_path, "rb") as binary_tokens:
					# these were saved as pickle dumps so we need the binary mode
					tokens[date_string] = pickle.load(binary_tokens)
				os.unlink(temp_path)
				
		# Get the collocations. Returns a tuple.
		self.query.update_status("Generating tf-idf for token set")
		tf_idf_matrix = self.get_tfidf(tokens, window_size, n_size, query_string=query_string, max_output=max_output)

		# Loop through the results and store them in the results list
		# for tpl in collocations:
		# 	result = {}
		# 	result['collocation'] = ' '.join(tpl[0])
		# 	result['value'] = tpl[1]
		# 	result['date'] = date_string
		# 	results.append(result)

		if not results:
			return

		# Generate csv and finish
		self.query.update_status("Writing to csv and finishing")				
		self.query.write_csv_and_finish(results)

	def get_tfidf(self, tokens, ngram_range=1, min_df=0, max_df=0, top_n=25):
		'''
		Creates a csv with the top n highest scoring tf-idf words.

		:param tokens,		list of tokens. Should be unpickled first
		:param max_df,		filter out words that appear in more than length of token list - max_df
		:param min_df,		filter out words that appear in less than min_df
		:param ngram_range, the amount of words to extract

		:returns ...
		'''

		# Validate some input
		if min_df != 0:
			min_df = len(tokens) - min_df
			return 'Terms must appear in at least ' + str(min_df) + ' of the total ' + str(len(tokens)) + ' files.'
		if max_df == 0:
			max_df = len(tokens)
		else:
			max_df = len(tokens) - max_df
			return 'Terms may only appear in max ' + str(max_df) + ' of the total ' + str(len(tokens)) + ' files.'

		# Set the ngram range as tuple (e.g. `(2,2)`)
		if isinstance(ngram_range, int):
			ngram_range = (ngram_range,ngram_range)

		# Vectorise
		self.query.update_status('Vectorizing')
		tfidf_vectorizer = TfidfVectorizer(min_df=min_df, max_df=max_df, ngram_range=ngram_range, analyzer='word', token_pattern=None, tokenizer=lambda i:i, lowercase=False)
		tfidf_matrix = tfidf_vectorizer.fit_transform(tokens)
		print(tfidf_matrix)
		return tfidf_matrix

		feature_array = np.array(tfidf_vectorizer.get_feature_names())
		tfidf_sorting = np.argsort(tfidf_matrix.toarray()).flatten()[::-1]
		
		# Print and store top n highest scoring tf-idf scores
		top_words = feature_array[tfidf_sorting][:top_n]
		print(top_words)

		weights = np.asarray(tfidf_matrix.mean(axis=0)).ravel().tolist()
		df_weights = pd.DataFrame({'term': tfidf_vectorizer.get_feature_names(), 'weight': weights})
		df_weights = df_weights.sort_values(by='weight', ascending=False).head(100)
		#df_weights.to_csv(output[:-4] + '_top100_terms.csv')
		#print(df_weights.head())

		df_matrix = pd.DataFrame(tfidf_matrix.toarray(), columns=tfidf_vectorizer.get_feature_names())
		
		# Turn the dataframe 90 degrees
		df_matrix = df_matrix.transpose()
		#print('Amount of words: ' + str(len(df_matrix)))
		
		self.query.update_status('Writing tf-idf vector to csv')

		# Do some editing of the dataframe
		df_matrix.columns = li_filenames
		cols = df_matrix.columns.tolist()
		cols = li_filenames

		df_matrix = df_matrix[cols]
		#df_matrix.to_csv(output[:-4] + '_matrix.csv')
		
		df_full = pd.DataFrame()

		print('Writing top ' + str(top_n) + ' terms per token file to "' + output[:-4] + '_full.csv"')

		# Store top terms per doc in a csv
		for index, doc in enumerate(df_matrix):
			df_tim = (df_matrix.sort_values(by=[doc], ascending=False))[:top_n]
			df_timesep = pd.DataFrame()
			df_timesep[doc] = df_tim.index.values[:top_n]
			df_timesep['tfidf_score_' + str(index + 1)] = df_tim[doc].values[:top_n]
			df_full = pd.concat([df_full, df_timesep], axis=1)

		df_full.to_csv(output[:-4] + '_full.csv')

		print('Writing a Rankflow-proof csv to "' + output[:-4] + '_rankflow.csv"')
		df_rankflow = df_full
		#df_rankflow = df_rankflow.drop(df_rankflow.columns[0], axis=1)
		
		cols = df_rankflow.columns
		for index, col in enumerate(cols):
			#print(col)
			if 'tfidf' in col:
				li_scores = df_rankflow[col].tolist()
				vals = [int(tfidf * 100) for tfidf in li_scores]
				df_rankflow[col] = vals

		df_rankflow.to_csv(output[:-4] + domain + '_rankflow.csv', encoding='utf-8', index=False)

		print('Done!')