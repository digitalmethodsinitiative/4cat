from __future__ import print_function
import sqlite3
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import time
import re
import os
import fourcat.similarities
import nltk
from collections import OrderedDict
from nltk.stem.snowball import SnowballStemmer
from nltk.corpus import stopwords
from scipy.interpolate import spline
from datetime import datetime, timedelta
from collections import OrderedDict
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.cluster import KMeans
from sklearn.externals import joblib
from sklearn.manifold import MDS

#HEADERS: num, subnum, thread_num, op, timestamp, timestamp_expired, preview_orig,
# preview_w, preview_h, media_filename, media_w, media_h, media_size,
# media_hash, media_orig, spoiler, deleted, capcode, email, name, trip,
# title, comment, sticky, locked, poster_hash, poster_country, exif

# full db: 4plebs_pol_18_03_2018
# full table: poldatabase_18_03_2018
# test db: 4plebs_pol_test_database
# test table: poldatabase

def substringFilter(inputstring, histogram = False, stringintitle = False, inputtime = 'months', normalised=False, writetext=False, docsimilarity = False, wordclusters = False, similaritytype=None):
	querystring = inputstring.lower()

	print('Connecting to database')
	conn = sqlite3.connect("data/4plebs_pol_test_database.db")

	print('Beginning SQL query for "' + querystring + '"')
	if stringintitle == False:
		df = pd.read_sql_query("SELECT timestamp, comment FROM poldatabase WHERE lower(comment) LIKE ?;", conn, params=['%' + querystring + '%'])
	else:
		df = pd.read_sql_query("SELECT timestamp, title FROM poldatabase WHERE lower(title) LIKE ?;", conn, params=['%' + querystring + '%'])

	# FOR DEBUGGING PURPOSES:
	#df = pd.read_csv('substring_mentions/mentions_alt-left.csv')

	print('Writing results to csv')
	if '/' in querystring:
		querystring = re.sub(r'/', '', querystring)
	else:
		querystring = querystring
	df.to_csv('substring_mentions/mentions_' + querystring + '.csv')
	return(df)

	if writetext == True:
		df_parsed = pd.DataFrame(columns=['comments','time'])
		df_parsed['comments'] = df['comment']
		#note: make day seperable later
		if inputtime == 'months':
			df_parsed['time'] = [datetime.strftime(datetime.fromtimestamp(i), "%m-%Y") for i in df['timestamp']]
		elif inputtime == 'weeks':
			df_parsed['time'] = [datetime.strftime(datetime.fromtimestamp(i), "%Y") + '-' + str((datetime.fromtimestamp(i).isocalendar()[1])) for i in df['timestamp']]
		elif inputtime == 'days':
			df_parsed['time'] = [datetime.strftime(datetime.fromtimestamp(i), "%d-%m-%Y") for i in df['timestamp']]
		df_parsed['comments'] = [re.sub(r'>', ' ', z) for z in df_parsed['comments']]
		
		print(df_parsed['comments'])

		#write text file for separate months
		currenttime = df_parsed['time'][1]
		oldindex = 1

		li_str_timeseparated = []
		li_str_full = []
		li_stringdates = []
		#create text files for each month
		for index, distincttime in enumerate(df_parsed['time']):
			if distincttime != currenttime or index == (len(df_parsed['time']) - 1):
				print(currenttime, distincttime)
				
				df_sliced = df_parsed[oldindex:index]
				print(df_sliced)
				
				string, li_strings = writeToText(df_sliced, querystring, currenttime)
				li_str_timeseparated.append(string)
				li_str_full.append(li_strings)
				li_stringdates.append(currenttime)
				oldindex = index + 1
				currenttime = distincttime				

	if similaritytype == 'docs' or similaritytype == 'words':
		if similaritytype == 'docs':
			words_stemmed = similarities.getTokens(li_str_timeseparated, li_stringdates,  similaritytype)
			similarities.getDocSimilarity(li_str_timeseparated, words_stemmed, li_stringdates, querystring)
		elif similaritytype == 'words':
			words_stemmed = similarities.getTokens(li_str_full, li_stringdates,  similaritytype)
			#print(words_stemmed)
			similarities.getWordSimilarity(words_stemmed)

	if histogram == True:
		createHistogram(df, querystring, inputtime, normalised)

def writeToText(inputdf, querystring, currenttime):
	txtfile = open('substring_mentions/longstring_' + querystring + '_' + currenttime + '.txt', 'w', encoding='utf-8')
	str_keyword = ''
	li_str = []
	for item in inputdf['comments']:
		item = item.lower()
		regex = re.compile("[^a-zA-Z \.\n]")		#excludes numbers, might have to revise this
		item = regex.sub("", item)
		txtfile.write("%s" % item)
		str_keyword = str_keyword + item
		li_str.append(item)
	return str_keyword, li_str

def createHistogram(inputdf, querystring, inputtimeformat, normalised):
	df = inputdf
	timeformat = inputtimeformat
	li_timestamps = df['timestamp'].values.tolist()
	li_timeticks = []

	dateformat = '%d-%m-%y'

	if timeformat == 'days':
		one_day = timedelta(days = 1)
		startdate = datetime.fromtimestamp(li_timestamps[0])
		enddate = datetime.fromtimestamp(li_timestamps[len(li_timestamps) - 1])
		delta =  enddate - startdate
		print(startdate)
		print(enddate)
		count_days = delta.days + 2
		print(count_days)
		for i in range((enddate-startdate).days + 1):
		    li_timeticks.append(startdate + (i) * one_day)
		dateformat = '%d-%m-%y'
		#convert UNIX timespamp
		mpl_dates = matplotlib.dates.epoch2num(li_timestamps)
		timebuckets = matplotlib.dates.date2num(li_timeticks)

	elif timeformat == 'months':
		#one_month = datetime.timedelta(month = 1)
		startdate = (datetime.fromtimestamp(li_timestamps[0])).strftime("%Y-%m-%d")
		enddate = (datetime.fromtimestamp(li_timestamps[len(li_timestamps) - 1])).strftime("%Y-%m-%d")
		dates = [str(startdate), str(enddate)]
		start, end = [datetime.strptime(_, "%Y-%m-%d") for _ in dates]
		total_months = lambda dt: dt.month + 12 * dt.year
		li_timeticks = []
		for tot_m in range(total_months(start) - 1, total_months(end)):
			y, m = divmod(tot_m, 12)
			li_timeticks.append(datetime(y, m + 1, 1).strftime("%m-%y"))
		#print(li_timeticks)
		dateformat = '%m-%y'
		mpl_dates = matplotlib.dates.epoch2num(li_timestamps)
		
		timebuckets = [datetime.strptime(i, "%m-%y") for i in li_timeticks]
		timebuckets = matplotlib.dates.date2num(timebuckets)

		#print(li_timeticks)
		count_timestamps = 0
		month = 0
		if normalised:
			di_totalcomment = {'2013-11': 63253, '2013-12': 1212205, '2014-01': 1169258, '2014-02': 1057543, '2014-03': 1236363, '2014-04': 1134904, '2014-05': 1194819, '2014-06': 1128180, '2014-07': 1492018, '2014-08': 1738454, '2014-09': 1572138, '2014-10': 1421393, '2014-11': 1441428, '2014-12': 907683, '2015-01': 772383, '2015-02': 890712, '2015-03': 1200995, '2015-04': 1301615, '2015-05': 1380384, '2015-06': 1392750, '2015-07': 1597596, '2015-08': 1904887, '2015-09': 1999249, '2015-10': 2000277, '2015-11': 2345632, '2015-12': 2593167, '2016-01': 2925801, '2016-02': 3112525, '2016-03': 3741424, '2016-04': 3049187, '2016-05': 3132968, '2016-06': 3641258, '2016-07': 4316283, '2016-08': 3619256, '2016-09': 3758381, '2016-10': 4413689, '2016-11': 5515133, '2016-12': 4186594, '2017-01': 5196683, '2017-02': 4365082, '2017-03': 4390319, '2017-04': 4430969, '2017-05': 4372821, '2017-06': 4018824, '2017-07': 3752927, '2017-08': 4087255, '2017-09': 3701459, '2017-10': 3928384, '2017-11': 4121087, '2017-12': 3584879, '2018-01': 3625070, '2018-02': 3468140, '2018-03': 2125521}

			li_totalcomments = [63253, 1212205, 1169258, 1057543, 1236363, 1134904, 1194819, 1128180, 1492018, 1738454, 1572138, 1421393, 1441428, 907683, 772383, 890712, 1200995, 1301615, 1380384, 1392750, 1597596, 1904887, 1999249, 2000277, 2345632, 2593167, 2925801, 3112525, 3741424, 3049187, 3132968, 3641258, 4316283, 3619256, 3758381, 4413689, 5515133, 4186594, 5196683, 4365082, 4390319, 4430969, 4372821, 4018824, 3752927, 4087255, 3701459, 3928384, 4121087, 3584879, 3625070, 3468140, 2125521]

		#print(mpl_dates)
		#print(timebuckets)

	# plot it!
	fig, ax = plt.subplots(1,1)
	ax.hist(mpl_dates, bins=timebuckets, align="left", color='red', ec="k")
	histo = ax.hist(mpl_dates, bins=timebuckets, align="left", color='red', ec="k")

	if timeformat == 'days':
		ax.xaxis.set_major_locator(matplotlib.dates.DayLocator())
		ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter(dateformat))
	elif timeformat == 'months':
		ax.xaxis.set_major_locator(matplotlib.dates.MonthLocator())
		ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter(dateformat))

	#hide every N labels
	for label in ax.xaxis.get_ticklabels()[::2]:
		label.set_visible(False)

	#set title
	ax.set_title('4chan/pol/ comments containing "' + querystring + '", ' + str(startdate) + ' - ' + str(enddate))

	#rotate labels
	plt.gcf().autofmt_xdate()
	plt.savefig('static/data/filters/chans/frequencygraphs/old_' + querystring + '_full.svg')
	# plt.show(block=False)
	# time.sleep(2)
	plt.close()

	newli_timeticks = []
	for item in di_totalcomment:
		newli_timeticks.append(item[0])
	#print(len(newli_timeticks))

	li_counts = []
	#print(ax.xaxis.get_ticklabels())
	li_axisticks = ax.xaxis.get_majorticklabels()
	li_axisticks = li_axisticks[:-3]
	li_axisticks = li_axisticks[3:]
	#print(li_axisticks)
	li_matchticks = []
	for text in li_axisticks:
		strtext = text.get_text()
		li_matchticks.append(strtext)
	print(len(li_matchticks))
	print('matching months: ' + str(li_matchticks))

	#print('histo data:')
	#print(histo)

	#loop over each month
	histoindex = 0
	for month in range(53):
		occurance = False
		for registeredmonth in li_matchticks:
			#print(registeredmonth)
			if registeredmonth == newli_timeticks[month]:
				print('Month ' + str(histoindex) + ' found')
				li_counts.append(histo[0][histoindex])
				histoindex = histoindex + 1
				occurance = True
		if occurance == False:						#if the string did not occur, write 0
			print('no occurances this month')
			li_counts.append(0)
	
	print('li_counts length: ' + str(len(li_counts)))

	li_normalisedcounts = []
	for index, count in enumerate(li_counts):
		#print(li_totalcomments[index])
		count_normalised = (count / li_totalcomments[index]) * 100
		#print(count_normalised)
		li_normalisedcounts.append(count_normalised)

	li_datesformatted = []
	li_histodates = []
	li_graph_timestamps = []
	for index, date in enumerate(newli_timeticks):
		dateobject = datetime.strptime(date, '%m-%y')
		graph_timestamp = index
		formatteddate = datetime.strftime(dateobject, '%Y-%b')
		histodate = datetime.strftime(dateobject, '%b %y')
		li_graph_timestamps.append(graph_timestamp)
		li_datesformatted.append(formatteddate)
		li_histodates.append(histodate)

	print('Writing results to csv')

	# only keep months that have full data
	del newli_timeticks[0]
	del li_datesformatted[0]
	del li_histodates[0]
	del li_graph_timestamps[0]
	del li_normalisedcounts[0]
	del li_counts[0]
	del newli_timeticks[len(newli_timeticks) - 1]
	del li_histodates[len(li_histodates) - 1]
	del li_graph_timestamps[len(li_graph_timestamps) - 1]
	del li_normalisedcounts[len(li_normalisedcounts) - 1]
	del li_counts[len(li_counts) - 1]
	del li_datesformatted[len(li_datesformatted) - 1]

	print(li_datesformatted)
	print(len(newli_timeticks))
	print(len(li_datesformatted))
	print(len(li_normalisedcounts))
	print(len(li_counts))

	finaldf = pd.DataFrame(columns=['date','dateformatted','count','percentage'])
	finaldf['date'] = newli_timeticks
	finaldf['dateformatted'] = li_datesformatted
	finaldf['percentage'] = li_normalisedcounts
	finaldf['count'] = li_counts
	finaldf.to_csv('static/data/filters/chans/substringfilters/occurrances_' + querystring + '.csv', index=False)

	df2 = pd.DataFrame(columns=['count','percentage'])
	df2['dates'] = li_histodates[1:]
	df2['count'] = li_counts[1:]
	df2['percentage'] = li_normalisedcounts[1:]
	df2['timestamps'] = li_graph_timestamps[1:]
	plotNewGraph(df2, querystring)

def plotNewGraph(df, query):
	#df = df.sort_values(by=['timestamps'])
	fig = plt.figure(figsize=(12, 8))
	fig.set_dpi(100)
	ax1 = fig.add_subplot(111)
	ax2 = ax1.twinx()
	print(df)
	df.plot(ax=ax1, y='count', kind='bar', legend=False, width=.9, color='#52b6dd');
	df.plot(ax=ax2, y='percentage', legend=False, kind='line', linewidth=2, color='#d12d04');
	ax1.set_axisbelow(True)
	ax1.set_xticklabels(df['dates'])
	ax1.grid(color='#e5e5e5',linestyle='dashed', linewidth=.6)
	ax1.set_ylabel('Absolute amount', color='#52b6dd')
	ax2.set_ylabel('Percentage of total comments', color='#d12d04')
	ax2.set_ylim(bottom=0)
	plt.title('Amount of 4chan/pol/ comments containing "' + query + '"')

	plt.savefig('static/data/filters/chans/frequencygraphs/trends_' + query + '.svg', dpi='figure')
	plt.savefig('static/data/filters/chans/frequencygraphs/trends_' + query + '.png', dpi='figure')

# for word in li_querywords:
# 	result = substringFilter(word, histogram = False, stringintitle = False, inputtime='months', normalised=True, writetext=False, similaritytype='words')	#returns tuple with df and input string