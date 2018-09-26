import sqlite3
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import operator
import collections
from datetime import datetime, timedelta
from matplotlib.font_manager import FontProperties

# HEADERS: num, subnum, thread_num, op, timestamp, timestamp_expired, preview_orig,
# preview_w, preview_h, media_filename, media_w, media_h, media_size,
# media_hash, media_orig, spoiler, deleted, capcode, email, name, trip,
# title, comment, sticky, locked, poster_hash, poster_country, exif

# test db: 4plebs_pol_test_database
# test table: poldatabase
# full db: 4plebs_pol_18_03_2018
# full table: poldatabase_18_03_2018

def getTopURLs(piegraph = False, histo = False, threshold = 20, querystring = ''):
	conn = sqlite3.connect("../4plebs_pol_18_03_2018.db")

	print('Running SQL query')
	urlSQLquery = "SELECT comment, thread_num, timestamp FROM poldatabase_18_03_2018 WHERE (comment LIKE '%http://%' OR comment LIKE '%https://%' OR comment LIKE '%www.%') AND (lower(comment) LIKE ?);"
	df = pd.read_sql_query(urlSQLquery, conn, params=['%' + querystring + '%'])

	print('Extracting URL regex from DataFrame')
	df['url'] = df['comment'].str.extract('([\/\/|www\.][0-9a-z\.]*\.[0-9a-z\.]+)')
	print(df['url'][:9])

	print('Writing csv')
	if querystring == '':
		querystring = 'full'
	df.to_csv('top_urls/urls_' + querystring + '.csv')

	# make pie graph of all URLs
	if piegraph == True:
		print('Formatting data for pie graph')

		di_all_urls = {}
		for url in df['url']:
			if url not in di_all_urls:
				di_all_urls[url] = 1
			else:
				di_all_urls[url] += 1
		#print(di_all_urls)

		most_used_url = max(di_all_urls.items(), key=operator.itemgetter(1))[0]
		di_pie_urls = {}
		di_pie_urls['other'] = 0
		plotthreshold = di_all_urls[most_used_url] / threshold

		for key, value in di_all_urls.items():
			formatted_url = str(key)[1:]
			if '..' not in formatted_url:		#bugfix
				if value < plotthreshold: 		#if the URL is used 10 times or less than the most popular URL
					di_pie_urls['other'] += 1
				else:
					di_pie_urls[formatted_url] = value

		print('Plotting pie graph')
		createPieGraph(di_pie_urls)

	# make stacked histogram of URLs
	if histo == True:
		print('Formatting data for histogram')
		
		#create month strings to loop through
		df['time'] = [datetime.strftime(datetime.fromtimestamp(i), "%m-%Y") for i in df['timestamp']]
		#dict of temporally separated urls
		di_separated_urls = collections.OrderedDict()

		#loop through months
		for index, timestring in enumerate(df['time']):
			#if the month is not yet registered, add it to the dict
			if timestring not in di_separated_urls:
				print('new month')
				di_separated_urls[timestring] = collections.OrderedDict()
				di_separated_urls[timestring][df['url'][index]] = 1
			else:
				#if the url is not yet registered
				#print(df['url'][index])
				if df['url'][index] not in di_separated_urls[timestring]:
					di_separated_urls[timestring][df['url'][index]] = 1
				#if it is registered
				else:
					di_separated_urls[timestring][df['url'][index]] += 1

		#print(di_separated_urls)

		di_pie_urls = collections.OrderedDict()
		#loop through months
		for month, urls in di_separated_urls.items(): 
			di_pie_urls[month] = collections.OrderedDict()
			#print(month)
			most_used_url = max(urls.items(), key=operator.itemgetter(1))[0]
			di_pie_urls[month]['other'] = 0

			
			print('Threshold: ' + str(threshold))

			#loop through URLs of a month
			for url, count in urls.items():
				formatted_url = str(url)[1:]
				#print(formatted_url)
				if '..' not in formatted_url:		#regex workaround
					if count < threshold: 		#if the URL is used 10 times or less than the most popular URL
						di_pie_urls[month]['other'] += 1
					else:
						di_pie_urls[month][formatted_url] = count

		#print(di_pie_urls)
		print('Plotting histo graph')
		createHisto(di_pie_urls, querystring)

def createPieGraph(dictionary, querystring):
	di = dictionary
	pie_values = di.values()
	pie_labels = di.keys()
	
	fig, ax = plt.subplots()

	# Draw the pie chart
	ax.pie([float(v) for v in di.values()], labels=pie_labels, autopct='%1.2f', startangle=0, pctdistance = 0.9, labeldistance=1.1)	

	# Aspect ratio - equal means pie is a circle
	ax.axis('equal')
	ax.set_title('Top 4chan/pol/ URLs, 29-11-2013 to 21-01-2014')

	plt.show()

def createHisto(dictionary, querystring):
	di_totalcomment = {'11-13': 1, '12-13': 61519, '01-14': 1212183, '02-14': 1169314, '03-14': 1057428, '04-14': 1234152, '05-14': 1135162, '06-14': 1195313, '07-14': 1127383, '08-14': 1491844, '09-14': 1738433, '10-14': 1571584, '11-14': 1424278, '12-14': 1441101, '01-15': 909278, '02-15': 772111, '03-15': 890495, '04-15': 1197976, '05-15': 1300518, '06-15': 1381517, '07-15': 1392446, '08-15': 1597274, '09-15': 1903111, '10-15': 23000, '11-15': 26004, '12-15': 2344421, '01-16': 2592275, '02-16': 2925369, '03-16': 3111713, '04-16': 3736528, '05-16': 3048962, '06-16': 3131789, '07-16': 3642871, '08-16': 4314923, '09-16': 3618363, '10-16': 3759066, '11-16': 4418571, '12-16': 5515200, '01-17': 4187400, '02-17': 5191531, '03-17': 4368911, '04-17': 4386181, '05-17': 4428757, '06-17': 4374011, '07-17': 4020058, '08-17': 3752418, '09-17': 4087688, '10-17': 3703119, '11-17': 3931560, '12-17': 4122068,'01-18': 3584861, '02-18': 3624546, '03-18': 3468642}

	li_timelabels = list(di_totalcomment.keys())
	
	df = pd.DataFrame.from_dict(dictionary, orient='index')
	#print(df.head())
	# df.rename(columns={'': 'A'}, inplace=True)
	# print(df.iloc[0])
	print(li_timelabels[2:])
	ax = df.plot(kind='bar', stacked=True, grid=True, width=.9, figsize=(14,10))
	ax.set_ylim(bottom=0)
	ax.set_ylabel('Amount of URL occurances')
	ax.set_xticklabels(li_timelabels)

	# Shrink current axis by 20%
	box = ax.get_position()
	ax.set_position([box.x0, box.y0, box.width * 0.8, box.height])
	# Put a legend to the right of the current axis
	ax.legend(loc='center left', bbox_to_anchor=(1, 0.5), fancybox=True, shadow=True)
	ax.grid(color='#e5e5e5',linestyle='dashed', linewidth=.6)
	plt.title('Hyperlinks associated with "' + querystring + '", over time')

	# plt.show()

	plt.savefig('../visualisations/urls/urls_histo_' + querystring + '.svg')
	plt.savefig('../visualisations/urls/urls_histo_' + querystring + '.jpg')

	# fig = plt.figure(figsize=(12, 8))
	# fig.set_dpi(100)
	# ax = fig.add_subplot(111)

	# df.plot(ax=ax, kind='bar', width=.9, color='#52b6dd', stacked=True);

	# ax.set_axisbelow(True)
	# ax.set_xticklabels(li_timelabels)
	# ax.grid(color='#e5e5e5',linestyle='dashed', linewidth=.6)
	# ax.set_ylabel('Absolute amount', color='#52b6dd')
	# plt.title('Amount of 4chan/pol/ comments containing "' + query + '"')

li_queries=['trump','we must','vote','podesta','clinton']

for query in li_queries:
	getTopURLs(piegraph=False, histo=True, threshold=200, querystring=query)


