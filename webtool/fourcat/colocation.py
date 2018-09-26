# this is kind of an example for something that goes into the direction of a tool ,-)
# it takes a CSV file as input (in this case a Netvizz top comments file) and calculates the top bigrams per timeframe
# the output is a file with a of bigrams per timeframe, including their frequency
# the output is compatible with the RankFlow tool (http://labs.polsys.net/tools/rankflow/) - copy and paste out of Excel 

import re
import operator
import pandas as pd
import nltk
from nltk.collocations import *
from nltk.tokenize import RegexpTokenizer
from nltk.corpus import stopwords

# this function takes a string as input and returns a sorted list of bigrams extraxted from the string
def getCollocations(content, limit, nsize, windowsize, colocationword=None):
	maxoutput = limit
	bigram_measures = nltk.collocations.BigramAssocMeasures()

	content = content.lower()

	regex = re.compile("[^a-zA-Z]")		#no numbers, might have to revise this
	content = regex.sub(" ", content)

	tokenizer = RegexpTokenizer(r"\w+")
	tmptokens = tokenizer.tokenize(content)

	#log likelihood bovenop tf-idf

	tokens = []
	forbiddenwords = ['www','youtube','com','watch', 'http', 'https', 'v']

	for word in tmptokens:
		if word not in stopwords.words("english"):
			if word != 'nan':
				if word not in forbiddenwords:
					match = re.search(word, r'(\d{9})')
					if not match:		#if it's a post number or a anon number
						#do nothing, can maybe later append these to the posts most mentioned
						tokens.append(word)

	if nsize == 'bigram':
		finder = BigramCollocationFinder.from_words(tokens, window_size=windowsize)
		if colocationword != None:
			word_filter = lambda w1, w2: colocationword not in (w1, w2)
			finder.apply_ngram_filter(word_filter)
	if nsize == 'trigram':
		finder = TrigramCollocationFinder.from_words(tokens, window_size=windowsize)
		if colocationword != None:
			word_filter = lambda w1, w2, w3: colocationword not in (w1, w2, w3)
			finder.apply_ngram_filter(word_filter)
	
	return sorted(finder.ngram_fd.items(), key=operator.itemgetter(1), reverse=True)[0:limit]

