import sqlite3
import pandas as pd
import time


databaselocation = 'static/data/4plebs_pol_18_03_2018.db'

# connect to db
print('Connecting to database')
conn = sqlite3.connect(databaselocation)
print('Connected to database')

c = conn.cursor()

# create fts table
# c.execute('''
# 	CREATE VIRTUAL TABLE pol_content_fts
# 	USING FTS5(num, title, comment);
# 	''')

# insert data into fts table
c.execute('''
	INSERT INTO pol_content_fts (timestamp, date_full) SELECT timestamp, date_full FROM pol_content;
	''')


conn.commit()
conn.close()

#Benchmark:
# start = time.time()
# df = pd.read_sql_query("SELECT comment FROM pol_content WHERE comment LIKE '%lulz%';", conn)
# print('Regular query finished in:')
# end_first = time.time()
# print(end_first - start)
# df = pd.read_sql_query("SELECT comment FROM pol_content_fts WHERE comment MATCH 'lulz';", conn)
# print('FTS query finished in:')
# end_last = time.time()
# print(end_first - end_last)