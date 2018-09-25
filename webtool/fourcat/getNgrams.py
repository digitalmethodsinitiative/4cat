import sqlite3
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import nltk
import re
import operator
from datetime import datetime, timedelta
from collections import OrderedDict
from nltk.collocations import *
from nltk.tokenize import RegexpTokenizer
from nltk.corpus import stopwords

#HEADERS: num, subnum, thread_num, op, timestamp, timestamp_expired, preview_orig,
# preview_w, preview_h, media_filename, media_w, media_h, media_size,
# media_hash, media_orig, spoiler, deleted, capcode, email, name, trip,
# title, comment, sticky, locked, poster_hash, poster_country, exif

# test db: 4plebs_pol_test_database
# test table: poldatabase
# full db: 4plebs_pol_18_03_2018
# full table: poldatabase_18_03_2018

def getNgrams(querystring, fullcomment = True, colocationamount = 1, windowsize = 4, outputlimit = 10, separateontime = False, timeseparator = 'days', frequencyfilter = 1, timeoffset=None):
	separateontime = separateontime
	maxoutput = outputlimit

	print('Connecting to database')
	conn = sqlite3.connect("../4plebs_pol_withheaders.db")

	print('Beginning SQL query for "' + querystring + '"')
	df = pd.read_sql_query("SELECT timestamp, comment FROM poldatabase WHERE lower(comment) LIKE ?;", conn, params=['%' + querystring + '%'])
	print('Writing results to csv')
	df.to_csv('substring_mentions/mentions_' + querystring + '.csv')

	#take DataFrame columns and convert to list
	print('Converting DataFrame columns to lists')
	li_posts = df['comment'].tolist()
	li_timestamplist = df['timestamp'].tolist()
	#remove column header (first entry in list)
	li_posts = li_posts[1:]
	li_timestamplist = li_timestamplist[1:]

	print('Generating string for colocations')
	forbiddenwords = ['www','youtube','com','watch', 'http', 'https', 'v', 'en', 'wikipedia', 'wiki', 'org']

	#dependent on 'timeseparator', create multiple string or just one string
	if separateontime == False:
		longstring = ''
		longstring = ' '.join(li_posts)
		
		bigram_measures = nltk.collocations.BigramAssocMeasures()

		#all text to lowercase
		longstring = longstring.lower()

		regex = re.compile("[^a-zA-Z]")		#excludes numbers, might have to revise this
		longstring = regex.sub(" ",longstring)

		tokenizer = RegexpTokenizer(r"\w+")
		tmptokens = tokenizer.tokenize(longstring)

		tokens = []

		print('Creating filtered tokens (i.e. excluding stopwords and forbiddenwords)')
		for word in tmptokens:
			if word not in stopwords.words("english"):
				if word not in forbiddenwords:
					match = re.search(word, r'(\d{9})')
					if not match:		#if it's a post number
						tokens.append(word)

		print('Generating colocations')
		colocations = calculateColocation(tokens, windowsize, colocationamount, querystring, fullcomment, frequencyfilter, outputlimit)
		str_colocations = str(colocations)

	elif separateontime == True:
		di_timestrings = {}
		str_timestring = ''
		str_timeinterval = ''

		if timeseparator == 'days':
			dateformat = '%Y-%m-%d'
		elif timeseparator == 'months':
			dateformat = '%Y-%m'
		currenttimeinverval = datetime.fromtimestamp(li_timestamplist[0]).strftime(dateformat)

		print('starting with ' + currenttimeinverval)
		for index, timestamp in enumerate(li_timestamplist):
			#check if the post is the same date as the previous post
			if currenttimeinverval == datetime.fromtimestamp(timestamp).strftime(dateformat):
				str_timestring = str(str_timestring) + str(li_posts[index]) + ' '
			#if its a new day/month, make a new dict entry
			else:
				#store old string
				di_timestrings[currenttimeinverval] = str_timestring
				str_timeinterval = datetime.fromtimestamp(timestamp).strftime(dateformat)
				str_timestring = str(li_posts[index])
				currenttimeinverval = str_timeinterval
				print('new timeframe: ' + str(currenttimeinverval))
			di_timestrings[currenttimeinverval] = str_timestring
		di_time_ngrams = {}

		#if there's no matches with the querystring
		if len(di_timestrings) < 1:
			return('No matches')

		for key, value in di_timestrings.items():
			print('starting colocations for ' + str(key))

			#all text to lowercase
			longstring = value.lower()
			#print(longstring)
			
			regex = re.compile("[^a-zA-Z]")		#excludes numbers, might have to revise this
			longstring = regex.sub(" ", longstring)

			tokenizer = RegexpTokenizer(r"\w+")
			tmptokens = tokenizer.tokenize(longstring)
			tokens = []

			print('Creating filtered tokens (i.e. excluding stopwords and forbiddenwords)')
			for word in tmptokens:
				if word not in stopwords.words("english"):
					if word not in forbiddenwords:
						match = re.search(word, r'(\d{9})')
						if not match:		#if it's a post number
							tokens.append(word)

			di_time_ngrams[key] = calculateColocation(tokens, windowsize, colocationamount, querystring, fullcomment, frequencyfilter, outputlimit)

			#bigram_measures = nltk.collocations.BigramAssocMeasures()
			#raw_freq_ranking = finder.nbest(bigram_measures.raw_freq, 10) #top-10
		colocations = di_time_ngrams
		str_colocations = str(di_time_ngrams)

	print('Generating RankFlow-capable csv of colocations')
	rankflow_df = createColocationCsv(colocations)
	rankflow_df.to_csv('colocations/' + querystring + '-colocations.csv', encoding='utf-8')

	print('Writing restults to textfile')
	write_handle = open('colocations/' + str(querystring) + '-colocations.txt',"w")
	write_handle.write(str(str_colocations))
	write_handle.close()

	return(colocations)

def calculateColocation(inputtokens, windowsize, colocationamount, querystring, fullcomment, frequencyfilter, outputlimit):
	#guide here http://www.nltk.org/howto/collocations.html
	#generate bigrams
	if colocationamount == 1:
		finder = BigramCollocationFinder.from_words(inputtokens, window_size=windowsize)
		#filter on bigrams that only contain the query string
		if fullcomment == False:
			word_filter = lambda w1, w2: querystring not in (w1, w2)
			finder.apply_ngram_filter(word_filter)
	#generate trigrams
	if colocationamount == 2:
		finder = TrigramCollocationFinder.from_words(inputtokens, window_size=windowsize)
		#filter on trigrams that only contain the query string
		if fullcomment == False:
			word_filter = lambda w1, w2, w3: querystring not in (w1, w2, w3)
			finder.apply_ngram_filter(word_filter)
	finder.apply_freq_filter(frequencyfilter)

	colocations = sorted(finder.ngram_fd.items(), key=operator.itemgetter(1), reverse=True)[0:outputlimit]
	return colocations

def createColocationCsv(inputcolocations):
	
	columns = []
	df = pd.DataFrame()

	for key, values in inputcolocations.items():
		li_colocations = []
		li_mentions = []
		mentions = 0
		columns.append(key)
		columns.append('mentions')

		for colocation_tuple in values:
			str_colocations = ''
			#loop through tuple with colocation words and frequency (at the end)
			for index, tuple_value in enumerate(colocation_tuple):
				
				if type(tuple_value) is tuple:
					for string in tuple_value:
						str_colocations = str_colocations + ' ' + string
				else:
					mentions = tuple_value

			li_colocations.append(str_colocations)
			li_mentions.append(mentions)

		tmp_df = pd.DataFrame()
		tmp_df[key] = li_colocations
		tmp_df['mentions'] = li_mentions
		df = pd.concat([df, tmp_df], axis=1)
		
	print(df)
	return(df)

altrightglossary = ['ourguy','based','btfo']

for word in altrightglossary:
	ngrams = getNgrams(word, fullcomment=False, colocationamount=2, windowsize=4, frequencyfilter=1, outputlimit=50, separateontime=True, timeseparator='months')

print(ngrams)
print('Colocations completed')