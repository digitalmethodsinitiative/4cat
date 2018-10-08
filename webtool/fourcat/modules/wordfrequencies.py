import re
import operator
import nltk
import pandas as pd
from nltk.collocations import *
from nltk.tokenize import RegexpTokenizer
from nltk.corpus import stopwords
from fourcat.createstrings import *

def getWordFrequencies(content, limitinput):
	limit = limitinput
	content = content.lower()

	content = content.lower()

	regex = re.compile("[^a-zA-Z]")			#no numbers, might have to revise this
	content = regex.sub(" ",content)

	tokenizer = RegexpTokenizer(r"\w+")
	tmptokens = tokenizer.tokenize(content)

	tokens = []
	forbiddenwords = ['www','youtube','com','watch', 'http', 'https', 'v','like','people','even','would','one','make','get']
	for word in tmptokens:
		if word not in stopwords.words("english"):
			if word not in forbiddenwords:
				match = re.search(word, r'(\d{9})')
				if not match:		#if it's a post number or a anon number
					#do nothing, can maybe later append these to the posts most mentioned
					tokens.append(word)

	di_wordfrequency = {}
	for token in tokens:
		if token not in di_wordfrequency:
			di_wordfrequency[token] = 1
		else:
			di_wordfrequency[token] += 1
	# to sort a dictionary by value, we need the operator module from the Python Core Library and have to create a list (dictionaries are orderless)

	import operator
	# the first parameter of the sorted() function transforms the dictionary into a list containing lists
	# the second parameter tells it which element to use; 0 would be the moderator name, 1 is the value
	# the third parameter allows us to reverse the order (or not)
	return sorted(di_wordfrequency.items(), key=operator.itemgetter(1), reverse=True)[0:limitinput]