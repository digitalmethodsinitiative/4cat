import sqlite3
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import datetime
import operator
import re

# HEADERS: num, subnum, thread_num, op, timestamp, timestamp_expired, preview_orig,
# preview_w, preview_h, media_filename, media_w, media_h, media_size,
# media_hash, media_orig, spoiler, deleted, capcode, email, name, trip,
# title, comment, sticky, locked, poster_hash, poster_country, exif

# test db: 4plebs_pol_test_database
# test table: poldatabase
# full db: 4plebs_pol_18_03_2018
# full table: poldatabase_18_03_2018

def getTripleParsContent():
	conn = sqlite3.connect("../4plebs_pol_withheaders.db")

	print('Running SQL query')
	SQLquery = "SELECT comment FROM poldatabase WHERE (lower(comment) LIKE '%(((%' AND lower(comment) LIKE '%)))%');"
	df = pd.read_sql_query(SQLquery, conn)
	print('Extracting URL regex from DataFrame')

	li_parscontents = []
	for string in df['comment']:
		li_matches = re.findall(r'[\(]{3,}(.*?)[\)]{3,}', string)
		for match in li_matches:
			if match != '':
				match = match.lower().strip()
				#match = match.strip()
				li_parscontents.append(match)

	print(li_parscontents[:9])
	print('Writing csv')

	#li_parscontents = df['parscontent'].values.tolist()
	di_all_parscontents = {}
	for parscontent in li_parscontents:
		if parscontent not in di_all_parscontents:
			di_all_parscontents[parscontent] = 1
		else:
			di_all_parscontents[parscontent] += 1
	result = sorted(di_all_parscontents.items(), key=operator.itemgetter(1), reverse=True)
	print(result)
	write_handle = open('triplepars2.txt',"w", encoding='utf-8')
	write_handle.write(str(result), encoding='utf-8', errors='ignore')
	write_handle.close()
	return result
result = getTripleParsContent()	#returns tuple with df and input string


print('finished')