import sqlite3
import csv
import json
import time
import ast
import html
import datetime
import pandas as pd
import sys
import fourcat.modules.similarities as sim
from fourcat import app
from nltk.corpus import stopwords
from bs4 import BeautifulSoup
from flask import Flask, url_for, request, render_template, jsonify
from io import StringIO
from apscheduler.schedulers.blocking import BlockingScheduler
from fourcat.modules.startwordanalysis import startWordAnalysis
from fourcat.modules.substringfilter import *
from fourcat.modules.createstrings import createStrings
from fourcat.modules.wordfrequencies import getWordFrequencies
from fourcat.modules.colocation import getCollocations
from fourcat.modules.chanscraper import *
from fourcat.modules.colocation import *
from fourcat.modules.startwordanalysis import *

# additional views

# HEADERS: num, subnum, thread_num, op, timestamp, timestamp_expired, preview_orig,
# preview_w, preview_h, media_filename, media_w, media_h, media_size,
# media_hash, media_orig, spoiler, deleted, capcode, email, name, trip,
# title, comment, sticky, locked, poster_hash, poster_country, exif

# test db: 4plebs_pol_test_database
# test table: poldatabase
# full db: 4plebs_pol_18_03_2018
# full table: pol_content
# full fts5 table: pol_content_fts

jsonfile = []

# dynamically switch between the test or full db depending on if it exists
if os.path.isfile('fourcat/static/data/4plebs_pol_18_03_2018.db'):
	databaselocation = 'fourcat/static/data/4plebs_pol_18_03_2018.db'
else:
	databaselocation = 'fourcat/static/data/4plebs_pol_test_database.db'

themes = ['vaporwave','meme magick','international chans']

@app.route('/load/<csv_input>')
def load_csv(csv_input):
	"""
	Reads and returns a three-row sample of the data selected.
	Useful for debugging
	"""
	csv_input = csv_input.replace('@','/')
	print(csv_input)

	# if the input is not the 4plebs db, handle csv-files universally
	if csv_input != '4plebs-pol-test-database':
		read_df = pd.read_csv('/static/data/' + csv_input + '.csv', encoding="utf-8")
		sampledf = read_df.head(3)
		htmltable = sampledf.to_html()
		# print(htmltable)
		return htmltable
	else:
		print('Connecting to database')
		conn = sqlite3.connect(databaselocation)

		print('Connected to database')
		df = pd.read_sql_query("SELECT * FROM pol_content LIMIT 20", conn)
		htmltable = df.to_html()
		return htmltable

@app.route('/search/<csv_input>/<searchquery>/<platform>/<histo>/<query_title>')
@app.route('/search/<csv_input>/<searchquery>/<platform>/<histo>/<query_title>/<mindate>/<maxdate>')
def search_csv(csv_input, searchquery, platform, histo = 0, query_title = 0, mindate='', maxdate=''):
	""" 
	Takes a text query and returns a csv sheet with the posts containing that query
	Keywords
	csv_input:		string		the name for the csv to check if it already exists
	searchquery:	string		the search query
	histo:			bool		whether to return a frequency histogram
	query_title:	bool		whether to look for the query in the post title
	mindate:		int			the starting timespan to query
	maxdate:		int			the end timespan to query
	"""
	column_comment = 'comment'
	histo = int(histo)
	print(platform)
	platformselected = platform

	query_title = int(query_title)
	if query_title == 1:
		commentortitle = 'title'
	else:
		commentortitle = 'comment'
	filestring = 'fourcat/static/data/filters/' + platformselected + '/substringfilters/mentions_' + commentortitle + '_' + searchquery + '_' + mindate + '_' + maxdate + '.csv'
	fileexists = checkFileExists(filestring)

	# make a better code later that returns also the freq image if it exists
	if fileexists:
		if histo == 1:
			print('Text data already filtered, skipping database querying.')
			print('Reading csv')
			df = pd.read_csv(filestring, encoding='utf-8')
			print('Creating HTML table of df')
			df_html = df.head()
			htmltable = df_html.to_html(index=False, escape=False)
			print('Creating trend histogram')
			createHistogram(df, searchquery.lower(), inputtimeformat='months', normalised=True)
			return(htmltable)
		else:
			return('file_exists')

	if platformselected == 'chans':
		column_comment = 'comment'
		column_time = 'now'
	elif platformselected == 'reddit':
		column_comment = 'title'
		column_time = 'now'
	elif platformselected == 'fb':
		column_comment = 'name'
		column_time = 'created_utc'
	csv_input = csv_input.replace('@','/')
	query = searchquery.lower()
	pd.set_option('display.max_colwidth', 9999)

	if mindate != '' and maxdate != '':
		print(mindate, maxdate)

	# if it's FB, Reddit or documented 4chan
	if csv_input != '4plebs-pol-test-database':
		read_df = pd.read_csv('/data/' + csv_input + '.csv', encoding="utf-8")
		if mindate != '' and maxdate != '':
			read_df = read_df[(read_df[timecolumn] >= mindate) & (read_df[timecolumn] <= maxdate)]
			
		df = read_df[read_df[column_comment].str.lower().str.contains(query, na=False)]

		if platformselected == 'chans':
			df = df[['now','threadnumber','comment','country']]
		elif platformselected == 'reddit':
			df = df[['title','score','subreddit','permalink','imageurl']]
		elif platformselected == 'fb':
			df = df[['created_time','name','reactionscount','link']]

		htmltable = df.to_html(index=False, escape=False)
	# if the search query is the 4plebs database
	else:
		# to catch large queries, make sure it's not a stopword
		if query not in stopwords.words("english") and len(query) > 2:
			print('Connecting to database "' + databaselocation + '"')
			conn = sqlite3.connect(databaselocation)
			print('Connected to database "' + databaselocation + '"')

			if query_title == 0:
				print('Queried comment for "' + query + '"')
				print(mindate, maxdate)

				#different sql queries for different inputs
				if mindate == '' and maxdate == '':
					df = pd.read_sql_query("SELECT * FROM pol_content_fts WHERE comment MATCH ?;", conn, params=[query])
				else:
					# optimise this query to get time-based text queries on the basis of the fts table later, not sure what is most efficient
					df = pd.read_sql_query("""
						SELECT pol_content.num, pol_content.comment, pol_content.title, pol_content.timestamp FROM pol_content
						INNER JOIN pol_content_fts
						ON pol_content.num = pol_content_fts.num
						WHERE pol_content_fts.comment MATCH ?
						AND pol_content.timestamp > ? AND pol_content.timestamp < ?;
						""", conn, params=[query, mindate, maxdate])
				df_html = df.head()
				print(df_html)
				htmltable = df_html.to_html()

			elif query_title == 1:
				if mindate == '' and maxdate == '':
					df = pd.read_sql_query("SELECT * FROM pol_content_fts WHERE title MATCH ?;", conn, params=[query])
				else:
					df = pd.read_sql_query("SELECT * FROM pol_content_fts WHERE title MATCH ? AND timestamp > ? AND timestamp < ?;", conn, params=[query, mindate, maxdate])
				htmltable = df.to_html(columns=['timestamp', 'title', 'comment'])
			print(len(df))
			if len(df) < 2 and maxdate != 10000000000:
				print('no_match_on_date')
				return('no_match_on_date')

			df.to_csv(filestring, encoding='utf-8')

			# if user has selected they want a time frequency histo
			if histo == 1:
				createHistogram(df, query, inputtimeformat='months', normalised=True)
		#if it's a stopword, let query fail
		else:
			print('invalid')
			return('invalid')

	return(htmltable)

@app.route('/images/<csv_input>/<searchterm>/<platform>')
def show_images(csv_input,searchterm,platform,mindate,maxdate):
	"""
	For future use
	Returns an HTML table with the entries that contain images
	This allows exploring images in the database
	"""
	csv_input = csv_input.replace('@','/')
	platformselected = platform
	searchquery = searchterm
	print(platformselected)

	pd.set_option('display.max_colwidth', 9999)
	read_df = pd.read_csv('fourcat/static/data/' + csv_input + '.csv', encoding="utf-8")

	fulltable = read_df[read_df['imageurl'].str.contains('1', na=False)]

	if searchquery is not '%':
		if platformselected == 'chans':
			column_comment = 'comment'
		elif platformselected == 'reddit':
			column_comment = 'title'
		elif platformselected == 'fb':
			column_comment = 'name'
		fulltable = read_df[read_df[column_comment].str.lower().str.contains(searchquery.lower(), na=False)]
	
	if platformselected == 'chans':
		resultstable = fulltable[['now','threadnumber','comment','country','imageurl']]
	elif platformselected == 'reddit':
		resultstable = fulltable[['title','author','now','score','subreddit','imageurl']]
	elif platformselected == 'fb':
		resultstable = fulltable[['name','id','imageurl','reactionscount','created_time']]
	jsonimages = resultstable.to_json()
	
	return(jsonimages)

@app.route('/wordanalysis/<csv_input>/<filtermethod>/<platform>')
@app.route('/wordanalysis/<csv_input>/<filtermethod>/<platform>/<windowsize>/<colocationword>')
def wordanalysis(csv_input,filtermethod,platform,windowsize=0,colocationword=''):
	"""
	Calls nltk to do n-gram text analysis.
	Probably not for production but might be interesting at a later stage.
	"""
	csvstring = csv_input
	csv_input = csv_input.replace('@','/')
	platformselected = platform

	# check if the query is already made and the respective csv exists
	filestring = 'fourcat/static/data/filters/' + platformselected + '/wordanalysis/' + filtermethod + '_' + colocationword + '_' + csvstring + '_' + windowsize + '.csv'
	fileexists = checkFileExists(filestring)
	if fileexists:
		return('file_exists')

	if platformselected != 'chans':
		read_df = pd.read_csv('fourcat/static/data/' + csv_input + '.csv', encoding="utf-8")
	else:
		# to catch large queries, make sure it's not a stopword
		if colocationword not in stopwords.words("english") and len(colocationword) > 2:
			print('Connecting to database')
			conn = sqlite3.connect(databaselocation)
			print('Connected to database')
			read_df = pd.read_sql_query("SELECT * FROM pol_content WHERE lower(comment) LIKE ?;", conn, params=['%' + colocationword + '%'])
		else:
			print('invalid')
			return('invalid query')
	wordanalysis_results = startWordAnalysis(read_df, filtermethod, platformselected, windowsize, colocationword)
	print(wordanalysis_results)

	if filtermethod == 'frequencies':
		table_frequencies = '<table class="table-responsive" id="frequencies1"><th>rank</th><th>word</th><th>amount</th>'
		for index, word in enumerate(wordanalysis_results):
			table_frequencies = table_frequencies + '<tr><td>'+str(index)+'</td><td>'+ word[0] +'</td><td>'+ str(word[1])+'</td></tr>'
		table_results = table_frequencies + '</table>'

	elif filtermethod == 'bigrams':
		table_bigrams = '<table class="table-responsive"><th>rank</th><th>word 1</th><th>word 2</th><th>co-occurrance</th>'
		for index, bigram in enumerate(wordanalysis_results):
			table_bigrams = table_bigrams + '<tr><td>'+str(index)+'</td><td>'+bigram[0][0]+'</td><td>'+bigram[0][1]+'</td><td>'+str(bigram[1])+'</td></tr>'
		table_results = table_bigrams + '</table>'

	elif filtermethod == 'trigrams':
		table_trigrams = '<table class="table-responsive"><th>rank</th><th>word 1</th><th>word 2</th><th>word 3</th><th>co-occurrance</th>'
		for index,trigram in enumerate(wordanalysis_results):
			table_trigrams = table_trigrams + '<tr><td>'+str(index)+'</td><td>'+trigram[0][0]+'</td><td>'+trigram[0][1]+'</td><td>'+trigram[0][2]+'</td><td>'+str(trigram[1])+'</td></tr>'
		table_results = table_trigrams + '</table>'
	
	#write to csv
	df_results = pd.read_html(table_results)
	df_results = df_results[0]
	df_results.to_csv(filestring, encoding='utf-8', index=False)
	return table_results

def checkFileExists(inputstring):
	if os.path.isfile(inputstring):
		return True
	else:
		return False

@app.route('/send', methods=['GET','POST'])
def accept_submissions():
	# function for sending data to a main screen. Used for the Transmediale 2018 Meme War workshop.
	global jsonfile
	if request.method == 'POST':		
		content = request.get_json()
		content = json.dumps(content)
		#content = html.escape(content, quote=False)
		content = content.replace('>','')
		content = content.replace('&lt;','')
		content = content.replace('<','')
		content = content.replace('&gt;','')
		loadedcontent = json.loads(content)
		
		newcontent = loadedcontent
		print(loadedcontent)
		print(type(newcontent))
		newjsonfile = {}
		newjsonfile['entry'] = newcontent
		jsonfile.append(newjsonfile)
		return content
	else:
		return 'success'
		#return render_template('fourcat.html', inputs=jsonfile)

@app.route('/update', methods=['GET','POST'])
def update_submissions():
	# function for updating data on the main screen. Used for the Transmediale 2018 Meme War workshop.
	print('request for datafile')
	updatejson = json.dumps(jsonfile)
	return updatejson

@app.route('/submissions')
def show_submissions():
	# function for updating data on the main screen. Used for the Transmediale 2018 Meme War workshop.
	inputs = jsonfile
	print(type(jsonfile))
	inputs = json.dumps(inputs)	
	return render_template('submitsuccess.html', inputs = inputs)

@app.route('/penelope')
@app.route('/penelope/<model>/<word>')
def penelope(model='yt-rightwing-transcripts', word='trump'):
	# Function that returns the view of the Penelope word2vec/monadology explorer.
	print('fourcat/static/data/word_embeddings/w2v_model_all-' + model + '.model')
	sims = sim.getW2vSims('fourcat/static/data/word_embeddings/w2v_model_all-' + model + '.model.bin', querystring=word, longitudinal=False)
	
	print('w2v nearest neighbours:')
	print(sims)

	return render_template('penelope.html', inputs=sims)

@app.route('/w2v/<model>/<word>')
def w2v(model, word='kek'):
	# Function that returns the n closest words of a certain word in a word2vec model.
	sims = sim.getW2vSims('fourcat/static/data/word_embeddings/w2v_model_all-' + model + '.model.bin', querystring=word, longitudinal=False)
	return sims