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

def getTotalActivity(dateformat='months'):
	print('Connecting to database')
	conn = sqlite3.connect("../4plebs_pol_18_03_2018.db")

	if dateformat == 'months':
		dateformat = '%Y-%m'
	elif dateformat == 'days':
		dateformat = '%Y-%m-%d'

	print('Beginning SQL query')

	li_dates = []

	# dates = pd.read_sql_query("SELECT MIN(timestamp)mintimestamp, MAX(timestamp)maxtimestamp FROM poldatabase_18_03_2018;", conn)
	# print(dates)
	firstdate = 1378739071
	lastdate = 1521370386
	# firstdate = dates['mintimestamp'][0]
	# lastdate = dates['maxtimestamp'][0]
	print(firstdate, lastdate)
	
	li_dates = []
	li_countposts = []

	headers=['date','posts']
	df_timethreads = pd.DataFrame(columns=headers)
	newtime = ''
	minquerydate = firstdate
	currenttime = datetime.fromtimestamp(minquerydate).strftime(dateformat)
	timestamp = firstdate
	while timestamp < lastdate:
		timestamp = timestamp + 1
		#print(timestamp)
		if timestamp != lastdate:
			newtime = datetime.fromtimestamp(timestamp).strftime(dateformat)
			#if there's a new date
			if currenttime != newtime:
				print('SQL query for ' + str(newtime))
				timestring = str(newtime)
				maxquerydate = timestamp
				print(minquerydate, maxquerydate)
				
				df = pd.read_sql_query("SELECT COUNT(*)count FROM poldatabase_18_03_2018 WHERE (timestamp BETWEEN ? AND ?);", conn, params=[minquerydate, maxquerydate])
				print(df)
				print(df['count'])
				li_dates.append(str(newtime))
				li_countposts.append(df['count'][0])
				print(li_countposts)
				minquerydate = timestamp
				currenttime = newtime

	df_timethreads['date'] = li_dates
	df_timethreads['posts'] = li_countposts
	print('Writing results to csv')
	df_timethreads.to_csv('all_activity.csv', index=False)
	print(df_timethreads)


getTotalActivity(dateformat='days')