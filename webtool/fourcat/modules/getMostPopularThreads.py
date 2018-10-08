import sqlite3
import pandas as pd
from datetime import datetime, timedelta

#HEADERS: num, subnum, thread_num, op, timestamp, timestamp_expired, preview_orig,
# preview_w, preview_h, media_filename, media_w, media_h, media_size,
# media_hash, media_orig, spoiler, deleted, capcode, email, name, trip,
# title, comment, sticky, locked, poster_hash, poster_country, exif

# test db: 4plebs_pol_test_database
# test table: poldatabase
# full db: 4plebs_pol_18_03_2018
# full table: poldatabase_18_03_2018

#generates a csv with the most commented on threads, per day, month, or in total. Limit denotes when to stop
def getMostPopularThreads(timeframe='full', limit=25):

	print('Connecting to database')
	conn = sqlite3.connect("../4plebs_pol_18_03_2018.db")
	print('Beginning SQL query to get most popular threads')

	limit = limit
	headers = ['date','comments','timestamp','thread_num','op','title','comment']
	if timeframe=='full':
		df_timethreads = pd.read_sql_query("SELECT COUNT(*)comments, timestamp, thread_num, title, comment, MAX(op) AS op FROM poldatabase_18_03_2018 WHERE comment LIKE '%cuck%' GROUP BY thread_num ORDER BY comments DESC, op DESC LIMIT ?;", conn, params=[limit])
		li_dates = []
		dateformat = '%Y-%m-%d-%H:%M:%S'
		for timestamp in df_timethreads['timestamp']:
			li_dates.append(datetime.fromtimestamp(timestamp).strftime(dateformat))
		df_timethreads['date'] = li_dates
	if timeframe == 'days' or timeframe == 'months':
		if timeframe == 'days':
			dateformat = '%Y-%m-%d'
		elif timeframe == 'months':
			dateformat = '%Y-%m'
		print('Getting first and last timestamps')
		dates = pd.read_sql_query("SELECT DISTINCT(timestamp) FROM poldatabase_18_03_2018;", conn)
		print(dates)
		li_alldates = dates['timestamp'].values.tolist()
		li_alldates.sort()
		firstdate = li_alldates[0]
		lastdate = li_alldates[len(li_alldates) - 1]
		print(firstdate, lastdate)

		df_timethreads = pd.DataFrame(columns=headers)
		newtime = ''
		minquerydate = firstdate
		currenttime = datetime.fromtimestamp(minquerydate).strftime(dateformat)
		for timestamp in li_alldates:
			#print(timestamp)
			if timestamp != lastdate:
				newtime = datetime.fromtimestamp(timestamp).strftime(dateformat)
				#if there's a new date
				if currenttime != newtime:
					print('SQL query for ' + str(newtime))
					maxquerydate = timestamp
					df = pd.DataFrame
					df = pd.read_sql_query("SELECT COUNT(*)comments, thread_num, title, comment, MAX(op) AS op, timestamp FROM poldatabase WHERE timestamp > ? AND timestamp < ? GROUP BY thread_num ORDER BY comments DESC, op DESC LIMIT ?;", conn, params=[minquerydate, maxquerydate, limit])
					tmp_dates = []
					for x in range(len(df['op'])):
						tmp_dates.append(newtime)
					#tmp_dates = pd.Series(tmp_dates)
					df['date'] = tmp_dates
					df_timethreads = df_timethreads.append(df)
					
					minquerydate = timestamp
					currenttime = newtime

	print('Writing results to csv')
	df_timethreads.to_csv('top_threads/top_threads_' + timeframe + '.csv', columns=headers)
	print(df_timethreads)

#timeframe: days, months, full
getMostPopularThreads(timeframe='days', limit=25)

	