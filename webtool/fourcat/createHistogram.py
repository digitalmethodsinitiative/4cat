import pandas as pd
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import time
import re
import os
from datetime import date, datetime, timedelta
from collections import OrderedDict
from matplotlib.ticker import ScalarFormatter

di_totalcomment = {'2013-11': 63253, '2013-12': 1212205, '2014-01': 1169258, '2014-02': 1057543, '2014-03': 1236363, '2014-04': 1134904, '2014-05': 1194819, '2014-06': 1128180, '2014-07': 1492018, '2014-08': 1738454, '2014-09': 1572138, '2014-10': 1421393, '2014-11': 1441428, '2014-12': 907683, '2015-01': 772383, '2015-02': 890712, '2015-03': 1200995, '2015-04': 1301615, '2015-05': 1380384, '2015-06': 1392750, '2015-07': 1597596, '2015-08': 1904887, '2015-09': 1999249, '2015-10': 2000277, '2015-11': 2345632, '2015-12': 2593167, '2016-01': 2925801, '2016-02': 3112525, '2016-03': 3741424, '2016-04': 3049187, '2016-05': 3132968, '2016-06': 3641258, '2016-07': 4316283, '2016-08': 3619256, '2016-09': 3758381, '2016-10': 4413689, '2016-11': 5515133, '2016-12': 4186594, '2017-01': 5196683, '2017-02': 4365082, '2017-03': 4390319, '2017-04': 4430969, '2017-05': 4372821, '2017-06': 4018824, '2017-07': 3752927, '2017-08': 4087255, '2017-09': 3701459, '2017-10': 3928384, '2017-11': 4121087, '2017-12': 3584879, '2018-01': 3625070, '2018-02': 3468140, '2018-03': 2125521}

li_totalcomments = [63253, 1212205, 1169258, 1057543, 1236363, 1134904, 1194819, 1128180, 1492018, 1738454, 1572138, 1421393, 1441428, 907683, 772383, 890712, 1200995, 1301615, 1380384, 1392750, 1597596, 1904887, 1999249, 2000277, 2345632, 2593167, 2925801, 3112525, 3741424, 3049187, 3132968, 3641258, 4316283, 3619256, 3758381, 4413689, 5515133, 4186594, 5196683, 4365082, 4390319, 4430969, 4372821, 4018824, 3752927, 4087255, 3701459, 3928384, 4121087, 3584879, 3625070, 3468140, 2125521]

di_totalthreads = {'2013-09': 1, '2013-11': 1514, '2013-12': 28827, '2014-01': 27537, '2014-02': 24338, '2014-03': 26086, '2014-04': 25917, '2014-05': 25909, '2014-06': 24301, '2014-07': 32147, '2014-08': 34295, '2014-09': 33908, '2014-10': 29955, '2014-11': 29313, '2014-12': 46547, '2015-01': 19692, '2015-02': 21520, '2015-03': 30041, '2015-04': 31505, '2015-05': 33098, '2015-06': 37833, '2015-07': 40682, '2015-08': 48558, '2015-09': 54562, '2015-10': 51533, '2015-11': 66440, '2015-12': 73255, '2016-01': 78008, '2016-02': 80849, '2016-03': 98149, '2016-04': 78861, '2016-05': 82652, '2016-06': 94564, '2016-07': 104147, '2016-08': 96223, '2016-09': 101897, '2016-10': 133773, '2016-11': 191605, '2016-12': 115409, '2017-01': 134600, '2017-02': 113708, '2017-03': 113349, '2017-04': 121685, '2017-05': 117634, '2017-06': 96822, '2017-07': 95565, '2017-08': 111826, '2017-09': 88076, '2017-10': 94396, '2017-11': 95713, '2017-12': 85371, '2018-01': 85360, '2018-02': 83711, '2018-03': 50395}

li_totalthreads = [1, 1514, 28827, 27537, 24338, 26086, 25917, 25909, 24301, 32147, 34295, 33908, 29955, 29313, 46547, 19692, 21520, 30041, 31505, 33098, 37833, 40682, 48558, 54562, 51533, 66440, 73255, 78008, 80849, 98149, 78861, 82652, 94564, 104147, 96223, 101897, 133773, 191605, 115409, 134600, 113708, 113349, 121685, 117634, 96822, 95565, 111826, 88076, 94396, 95713, 85371, 85360, 83711, 50395]

def createHistogram(df, querystring='', timeformat='months', includenormalised=False):
	li_dates = df['date_full'].values.tolist()
	li_timeticks = []

	dateformat = '%d-%m-%y'

	df_histo = pd.DataFrame()

	if timeformat == 'months':
		df['date_histo'] = [date[:7] for date in df['date_full']]
		df = df.groupby(by=['date_histo']).agg(['count'])
		print(df)

	elif timeformat == 'days':
		df['date_histo'] = [date[:10] for date in df['date_full']]
		df = df.groupby(by=['date_histo']).agg(['count'])
		print(df)

	#create new list of all dates between start and end date
	#sometimes one date has zero counts, and gets skipped by matplotlib
	li_dates = []
	if timeformat == 'months':
		d1 = datetime.strptime(df.index[0], "%Y-%m").date()  # start date
		d2 = datetime.strptime(df.index[len(df) - 1], "%Y-%m").date()  # end date
		print(d1, d2)
		delta = d2 - d1         # timedelta
		for i in range(delta.days + 1):
			date = d1 + timedelta(days=i)
			date = str(date)[:7]
			if date not in li_dates:
				li_dates.append(date)
		print(li_dates)
	if timeformat == 'days':
		d1 = datetime.strptime(df.index[0], "%Y-%m-%d").date()  # start date
		d2 = datetime.strptime(df.index[len(df) - 1], "%Y-%m-%d").date()  # end date
		print(d1, d2)
		delta = d2 - d1         # timedelta
		for i in range(delta.days + 1):
			li_dates.append(d1 + timedelta(days=i))

	#create list of counts. 0 if it does not appears in previous DataFrame
	li_counts = [0 for i in range(len(li_dates))]
	for index, indate in enumerate(li_dates):
		if indate in df.index.values and df.loc[indate][1] > 0:
			li_counts[index] = df.loc[indate][1]

	print(li_counts)
	df_histo['date'] = li_dates
	df_histo['count'] = li_counts

	#create list of average countrs
	li_av_count = []
	for i in range(len(df_histo)):
		av_count = (df_histo['count'][i] / di_totalcomment[df_histo['date'][i]]) * 100
		li_av_count.append(av_count)

	df_histo['av_count'] = li_av_count

	# remove march 2018
	print(df_histo['date'][len(df_histo) - 1])
	if timeformat == 'months' and df_histo['date'][len(df_histo) - 1] == '2018-03':
		df_histo.drop([len(df_histo) - 1], inplace=True)

	print(df_histo)
	df_histo.to_csv('substring_mentions/occurrances_' + querystring + '.csv', index=False)

	# plot it
	fig, ax = plt.subplots(1,1)
	fig = plt.figure(figsize=(12, 8))
	fig.set_dpi(100)
	ax = fig.add_subplot(111)

	ax2 = ax.twinx()
	if timeformat == 'days':
		ax.xaxis.set_major_locator(matplotlib.dates.DayLocator())
		ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter(dateformat))
	elif timeformat == 'months':
		ax.xaxis.set_major_locator(matplotlib.dates.MonthLocator())
		ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter(dateformat))
	ax.get_yaxis().set_major_formatter(plt.FuncFormatter(lambda x, loc: "{:,}".format(int(x))))
	
	df_histo.plot(ax=ax, y='count', kind='bar', legend=False, width=.9, color='#52b6dd');
	df_histo.plot(ax=ax2, y='av_count', legend=False, kind='line', linewidth=2, color='#d12d04');
	ax.set_axisbelow(True)
	# ax.set_xticks(xticks)
	ax.set_xticklabels(df_histo['date'], rotation='vertical')
	ax.grid(color='#e5e5e5',linestyle='dashed', linewidth=.6)
	ax.set_ylabel('Absolute amount', color='#52b6dd')
	ax2.set_ylabel('Percentage of total comments', color='#d12d04')
	ax2.set_ylim(bottom=0)
	plt.title('Amount of 4chan/pol/ comments containing "' + querystring + '"')

	plt.savefig('../visualisations/substring_counts/svg/' + querystring + '.svg', dpi='figure',bbox_inches='tight')
	plt.savefig('../visualisations/substring_counts/jpg/' + querystring + '.jpg', dpi='figure',bbox_inches='tight')

def plotMultipleTrends(df1=None,df2=None,df3=None, query='', filename='', twoaxes=False):
	#takes multiple words and plots the occurance of these.
	df_1 = df1.loc[1:].reset_index()
	print(df1)
	print(df_1)
	df_1['numbs'] = [x for x in range(len(df_1))]
	datelabels = [date for date in df_1['dateformatted']]
	df_2 = df2.loc[1:].reset_index()
	df_3 = df3.loc[1:].reset_index()

	fig = plt.figure(figsize=(12, 8))
	fig.set_dpi(100)
	ax = fig.add_subplot(111)

	if twoaxes:
		df_1.plot(ax=ax, y='percentage', label = 'trump', kind='line', legend=False, linewidth=2, color='orange');
		ax2 = ax.twinx()
		df_2.plot(ax=ax2, y='percentage',  label = 'god-emperor', kind='line', legend=False, linewidth=2, color='blue');
	else:
		df_1.plot(ax=ax, y='percentage', label = 'trump', kind='line', legend=False, linewidth=2, color='orange');
		df_2.plot(ax=ax, y='percentage',  label = 'nice', kind='line', legend=False, linewidth=2, color='blue');
		df_3.plot(ax=ax, y='percentage',  label = 'would', kind='line', legend=False, linewidth=2, color='green');
	ax.set_xticks(df_1['numbs'])
	ax.set_xticklabels(df_1['date'], rotation=90)

	lines, labels = ax.get_legend_handles_labels()
	plt.xlim([0,len(datelabels) -1])
	ax.set_ylim(bottom=0)
	ax.set_axisbelow(True)
	#ax2.set_axisbelow(True)
	ax.grid(color='#e5e5e5',linestyle='dashed', linewidth=.6)
	ax.set_ylabel('Percentage of total comments')
	plt.title('Percentage of 4chan/pol/ comments containing "' + query + '"')

	if twoaxes:
		lines2, labels2 = ax2.get_legend_handles_labels()
		print('do nothing')
		ax2.legend(lines + lines2, labels + labels2, loc='upper left')
	# 	lns = ln1 + ln2
	# 	labs = [l.get_label() for axes in ln1]
		ax2.set_ylim(bottom=0)
	# 	ax.legend(lns, labs, loc='upper left')
	else:
		ax.legend(loc='upper left')

	plt.savefig('../visualisations/substring_counts/' + filename + '_multiple.svg', dpi='figure',bbox_inches='tight')
	plt.savefig('../visualisations/substring_counts/' + filename + '_multiple.jpg', dpi='figure',bbox_inches='tight')
	#plt.show()

def createHistoFromTfidf(df='', li_words=''):
	df = df[df['word'].isin([li_words])]
	df = df.transpose()
	print(df)
	df['numbs'] = [x for x in range(len(df))]
	datelabels = [date for date in df['dateformatted']]

	fig = plt.figure(figsize=(12, 8))
	fig.set_dpi(100)
	ax = fig.add_subplot(111)

	df.plot(ax=ax, y='percentage', label = 'trump', kind='line', legend=False, linewidth=2, color='orange');
	
	ax.set_xticks(df['numbs'])
	ax.set_xticklabels(df['date'], rotation=90)

	lines, labels = ax.get_legend_handles_labels()
	plt.xlim([0,len(datelabels) -1])
	ax.set_ylim(bottom=0)
	ax.set_axisbelow(True)
	#ax2.set_axisbelow(True)
	ax.grid(color='#e5e5e5',linestyle='dashed', linewidth=.6)
	ax.set_ylabel('Percentage of total comments')
	plt.title('Percentage of 4chan/pol/ comments containing "' + query + '"')

	if twoaxes:
		lines2, labels2 = ax2.get_legend_handles_labels()
		ax2.legend(lines + lines2, labels + labels2, loc='upper left')
		ax2.set_ylim(bottom=0)
	else:
		ax.legend(loc='upper left')

	plt.savefig('tfidf/' + filename + '_trump_tfidf.svg', dpi='figure',bbox_inches='tight')
	plt.savefig('tfidf/' + filename + '_trump_tfidf.jpg', dpi='figure',bbox_inches='tight')
	#plt.show()

def createThreadMetaHisto(df=''):
	print('Creating bar chart for thread meta data')
	#df = df.sort_values(by='amount_of_posts', ascending=True)
	print(df.head())
	li_labels = []
	for count in df['amount_of_posts']:
		if count == '500':
			count = '500+'
			li_labels.append(count)
		else:
			li_labels.append(count)
	print(li_labels)

	fig = plt.figure(figsize=(12, 8))
	fig.set_dpi(100)
	ax = fig.add_subplot(111)
	ax2 = ax.twinx()
	ax3 = ax.twinx()
	kwarg = {'position': 1}
	df.plot(ax=ax, x='amount_of_posts', y='occurrances', kind='bar', label='Threads containing "trump"', position=0.0, legend=False, width=.9, color='#52b6dd');
	df.plot(ax=ax2, x='amount_of_posts', y='averagetrumps', kind='line', label='Trump count: Average posts with "trump" per thread', legend=False, linewidth=1.2, color='red');
	df.plot(ax=ax3, x='amount_of_posts', y='averagetrumpdensity', kind='line', label='Trump density: Percentage of total thread posts with "trump"', legend=False, linewidth=1.2, color='orange');
	plt.title('All threads on 4chan/pol/ containing "trump", separated by thread length')

	ax2.set_ylim(bottom=0, top=25)
	ax3.set_ylim(bottom=0, top=25)

	ax.grid(color='#e5e5e5',linestyle='dashed', linewidth=.6)

	ax.set_xticklabels(li_labels)
	#legend
	# lines, labels = ax.get_legend_handles_labels()
	# lines2, labels2 = ax2.get_legend_handles_labels()
	# lines3, labels3 = ax3.get_legend_handles_labels()
	# ax2.legend(lines + lines2 + lines3, labels + labels2 + labels, loc='upper right')
	ax.set_xlabel("Amount of posts in thread")
	ax.set_ylabel('Threads having 1> post(s) containing "trump"', color='#52b6dd')
	ax2.set_ylabel('Posts containing "trump", average per thread', color='red')
	ax3.set_ylabel('Percentage of posts containing "trump", per thread', color='orange')
	ax2.yaxis.set_label_coords(1.06,0.5)
	
	plt.show()

def getThreadMetaInfo(df=''):
	df['thread_count'] = [int(string) for string in df['thread_count']]
	print(len(df))
	df = df.sort_values(by='thread_count', ascending=True)
	print(df.head())
	print(df['thread_count'])

	di_threadlengths = {}
	di_average_trumps = {}
	di_average_trumpdensity = {}


	count_500 = 0
	li_500_trumps = []
	li_500_trumpdensities = []

	for index, count in enumerate(df['thread_count']):
		mod_count = count - (count % 10)
		str_mod_count = str(mod_count)
		if mod_count >= 500:
			count_500 += 1
			li_500_trumps.append(df['trump_count'][index])
			li_500_trumpdensities.append(df['trump_density'][index])
		elif str_mod_count in di_threadlengths:
			di_threadlengths[str_mod_count] += 1
			di_average_trumps[str_mod_count].append(df['trump_count'][index])
			di_average_trumpdensity[str_mod_count].append(df['trump_density'][index])
		else:
			di_threadlengths[str_mod_count] = 1
			print(str_mod_count)
			di_average_trumps[str_mod_count] = []
			di_average_trumpdensity[str_mod_count] = []
			di_average_trumps[str_mod_count].append(df['trump_count'][index])
			di_average_trumpdensity[str_mod_count].append(df['trump_density'][index])

	di_threadlengths['500'] = count_500
	di_average_trumps['500'] = li_500_trumps
	di_average_trumpdensity['500'] = li_500_trumpdensities

	#calculate the average trump count and trump density per length of thread ('do longer threads contain more Trumps?')
	averagetrumps = 0
	li_averagetrumps = []
	for key, value in di_average_trumps.items():
		for av in value:
			#print(av)
			averagetrumps += av
		averagetrumps = (averagetrumps / len(value))
		#print(averagetrumps)
		li_averagetrumps.append(averagetrumps)
	trumpdensities = 0
	li_trumpdensities = []
	for key, value in di_average_trumpdensity.items():
		for av in value:
			#print(av)
			trumpdensities += av
		#print(len(value), trumpdensities)
		trumpdensities = (trumpdensities / len(value)) * 100
		#print(trumpdensities)
		li_trumpdensities.append(trumpdensities)

	df_plot = pd.DataFrame.from_dict(di_threadlengths, orient='index')
	df_plot.reset_index(level=0, inplace=True)
	df_plot.columns = ['amount_of_posts','occurrances']
	df_plot['averagetrumps'] = li_averagetrumps
	df_plot['averagetrumpdensity'] = li_trumpdensities
	print(df_plot.head())
	return df_plot

def createThreadsHisto(inputdf=''):
	#create a histogram showing the amount of comments in a word-dense thread
	#make a counted df first and use it as the input df (with: df.groupby(['column']).agg('count'))

	df = pd.read_csv(inputdf)
	li_av_count = []
	df = df[16:]
	df.drop_duplicates(subset=['thread_num'], inplace=True)
	df = df.groupby(['date_month']).agg('count')
	print(df.head())
	df.reset_index(inplace=True)

	#create average thread occurance
	# for index, count in enumerate(df['num']):
	# 	av_count = ((float(count) / float(li_totalthreads[19 + index])) * 100)
	# 	print(av_count)
	# 	li_av_count.append(float(av_count))

	#create list of average countrs
	li_av_count = []
	for i in range(len(df)):
		av_count = (df['num'][i] / di_totalthreads[df['date_month'][i]]) * 100
		li_av_count.append(av_count)

	df['average_count'] = li_av_count
	df['count'] = pd.to_numeric(df['num'])
	df = df[:-1]
	print(df[:100])
	df.to_csv(inputdf[-4:] + '_counts.csv', encoding='utf-8')

	li_labels = df['date_month']
	fig = plt.figure(figsize=(12, 8))
	fig.set_dpi(100)
	ax = fig.add_subplot(111)
	print(type(df['count'][5]))

	df.plot(ax=ax, y='count', kind='bar', label='Amount of Trump-dense threads', position=0.5, legend=False, width=.9, color='#52b6dd');
	ax2 = ax.twinx()
	ax2.plot(li_av_count, color='#d12d04')
	plt.title('Amount of Trump-dense threads')
	ax.set_xticklabels(li_labels)
	ax.set_ylim(bottom=0)
	ax2.set_ylim(bottom=0)
	ax.grid(color='#e5e5e5',linestyle='dashed', linewidth=.6)
	ax.set_ylabel('Absolute amount of Trump-dense threads', color='#52b6dd')
	ax.get_yaxis().set_major_formatter(plt.FuncFormatter(lambda x, loc: "{:,}".format(int(x))))

	ax2.set_ylabel('Percentage of total threads', color='#d12d04')
	plt.show()

# df= "substring_mentions/mentions_trump/trump_threads/trump_threads_15percent_30min.csv"
# createThreadsHisto(inputdf=df)

def createThreadsCommentHisto(inputdf=''):
	#create a histogram showing the amount of comments in a word-dense thread
	#make a counted df first and use it as the input df (with: df.groupby(['column'].agg('count')))

	df = pd.read_csv(inputdf)
	df = df[3:]
	print(df.head())
	li_av_count = []
	#create average counts between the total comments of threads and total comments on entire board
	for index, count in enumerate(df['num']):
		av_count = ((float(count) / float(li_totalcomments[16 + index])) * 100)
		print(av_count)
		li_av_count.append(float(av_count))

	df_histo['av_count'] = li_av_count
	df['average_count'] = li_av_count
	df['num'] = pd.to_numeric(df['num'])
	df = df[:-1]
	print(df[:100])
	df.to_csv(inputdf[-4:] + '_counts.csv', encoding='utf-8')

	li_labels = df['date_month']
	fig = plt.figure(figsize=(12, 8))
	fig.set_dpi(100)
	ax = fig.add_subplot(111)
	print(type(df['num'][5]))

	df.plot(ax=ax, y='num', kind='bar', label='Posts in Trump-dense threads', position=0.5, legend=False, width=.9, color='#52b6dd');
	ax2 = ax.twinx()
	ax2.plot(li_av_count, color='#d12d04')
	plt.title('Amount of posts in Trump-dense threads')
	ax.set_xticklabels(li_labels)
	ax.set_ylim(bottom=0)
	ax2.set_ylim(bottom=0, top=42.8)
	ax.grid(color='#e5e5e5',linestyle='dashed', linewidth=.6)
	ax.set_ylabel('Absolute amount of posts in Trump-dense threads', color='#52b6dd')

	ax2.set_ylabel('Percentage of total comments', color='#d12d04')
	plt.show()

def createCosineDistHisto(di_cos_dist, word1, word2):
	# requires an orderd dict of with time as key, and cosine distance as value. Is called in similarities.getW2vCosineDistance()
	x = [i for i in range(len(di_cos_dist))]
	print(x)
	y = di_cos_dist.values()
	print(y)
	labels = [key for key, value in di_cos_dist.items()]
	print(labels)
	fig = plt.figure(figsize=(11, 8))
	fig.set_dpi(100)
	ax = fig.add_subplot(111)
	ax.plot(x, y)
	#ax.set_ylim()
	ax.set_xlim(left=0, right=0)
	ax.set_xticks(x)
	ax.set_xticklabels(labels, rotation='vertical')
	ax.grid(color='#e5e5e5',linestyle='dashed', linewidth=.6)
	ax.set_ylabel('Cosine distance')

	plt.title('Word2vec cosine distance between "' + word1 + '" and "' + word2 + '"')
	plt.show()
	if '/' in word2:
		word2 = re.sub('/', '', word2)
	plt.savefig('../visualisations/w2v_cosine_distance/w2v_cos_dist_' + word1 + '-' + word2 + '.png', dpi='figure',bbox_inches='tight')
	plt.savefig('../visualisations/w2v_cosine_distance/w2v_cos_dist_' + word1 + '-' + word2 + '.svg', dpi='figure',bbox_inches='tight')

def getAllActivityHisto(threads=False):
	ordi_totalcomments = OrderedDict([('2013-12', 1212205),('2014-01', 1169258),('2014-02', 1057543),('2014-03', 1236363),('2014-04', 1134904),('2014-05', 1194819),('2014-06', 1128180),('2014-07', 1492018),('2014-08', 1738454),('2014-09', 1572138),('2014-10', 1421393),('2014-11', 1441428),('2014-12', 907683),('2015-01', 772383),('2015-02', 890712),('2015-03', 1200995),('2015-04', 1301615),('2015-05', 1380384),('2015-06', 1392750),('2015-07', 1597596),('2015-08', 1904887),('2015-09', 1999249),('2015-10', 2000277),('2015-11', 2345632),('2015-12', 2593167),('2016-01', 2925801),('2016-02', 3112525),('2016-03', 3741424),('2016-04', 3049187),('2016-05', 3132968),('2016-06', 3641258),('2016-07', 4316283),('2016-08', 3619256),('2016-09', 3758381),('2016-10', 4413689),('2016-11', 5515133),('2016-12', 4186594),('2017-01', 5196683),('2017-02', 4365082),('2017-03', 4390319),('2017-04', 4430969),('2017-05', 4372821),('2017-06', 4018824),('2017-07', 3752927),('2017-08', 4087255),('2017-09', 3701459),('2017-10', 3928384),('2017-11', 4121087),('2017-12', 3584879),('2018-01', 3625070),('2018-02', 3468140)])

	ordi_totalthreads = OrderedDict([('2013-12', 28827), ('2014-01', 27537), ('2014-02', 24338), ('2014-03', 26086), ('2014-04', 25917), ('2014-05', 25909), ('2014-06', 24301), ('2014-07', 32147), ('2014-08', 34295), ('2014-09', 33908), ('2014-10', 29955), ('2014-11', 29313), ('2014-12', 46547), ('2015-01', 19692), ('2015-02', 21520), ('2015-03', 30041), ('2015-04', 31505), ('2015-05', 33098), ('2015-06', 37833), ('2015-07', 40682), ('2015-08', 48558), ('2015-09', 54562), ('2015-10', 51533), ('2015-11', 66440), ('2015-12', 73255), ('2016-01', 78008), ('2016-02', 80849), ('2016-03', 98149), ('2016-04', 78861), ('2016-05', 82652), ('2016-06', 94564), ('2016-07', 104147), ('2016-08', 96223), ('2016-09', 101897), ('2016-10', 133773), ('2016-11', 191605), ('2016-12', 115409), ('2017-01', 134600), ('2017-02', 113708), ('2017-03', 113349), ('2017-04', 121685), ('2017-05', 117634), ('2017-06', 96822), ('2017-07', 95565), ('2017-08', 111826), ('2017-09', 88076), ('2017-10', 94396), ('2017-11', 95713), ('2017-12', 85371), ('2018-01', 85360), ('2018-02', 83711)])
	
	if threads == False:
		ordi = ordi_totalcomments
		str_label = 'posts'
	else:
		ordi = ordi_totalthreads
		str_label = 'threads'

	x = [i for i in range(len(ordi))]
	print(x)
	y = ordi.values()
	print(y)
	labels = [key for key, value in ordi.items()]
	print(labels)
	fig = plt.figure(figsize=(11, 8))
	fig.set_dpi(100)
	ax = fig.add_subplot(111)
	ax.bar(x, y)
	ax.get_yaxis().set_major_formatter(plt.FuncFormatter(lambda x, loc: "{:,}".format(int(x))))
	ax.set_ylim(bottom=0)
	plt.xlim(-0.5,len(x)-.5)
	ax.set_xticks(x)
	ax.set_xticklabels(labels, rotation='vertical')
	ax.grid(color='#e5e5e5',linestyle='dashed', linewidth=.6)
	ax.set_ylabel('Total amount of ' + str_label)
	for label in ax.xaxis.get_ticklabels()[::2]:
		label.set_visible(False)
	plt.title('Total amount of ' + str_label + ' on 4chan/pol/')
	# plt.show()
	plt.savefig('../visualisations/total_activity_' + str_label + '.png', dpi='figure',bbox_inches='tight')
	plt.savefig('../visualisations/total_activity_' + str_label + '.svg', dpi='figure',bbox_inches='tight')


