import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "'/../..")

from common.lib.database import Database
from common.lib.logger import Logger

import psycopg2
import config

log = Logger(output=True)
db = Database(logger=log, dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD, host=config.DB_HOST, port=config.DB_PORT, appname="4cat-migrate")

print("  Making sure nltk packages are present...")
import nltk
nltk.download("punkt")
nltk.download("wordnet")

print("  Checking for 4chan database tables... ", end="")
try:
	test = db.fetchone("SELECT * FROM posts_4chan LIMIT 1")
except psycopg2.ProgrammingError:
	print("not available, nothing to upgrade!")
	exit(0)

print("  Checking if required columns exist... ", end="")
columns = [row["column_name"] for row in db.fetchall("SELECT column_name FROM information_schema.columns WHERE table_name = %s", ("posts_4chan",))]
if "board" in columns:
	print("yes!")
else:
	print(" adding 'board' column to 4chan posts table")
	db.execute("ALTER TABLE posts_4chan ADD COLUMN board TEXT DEFAULT ''")

print("  Filling 'board' column")
db.execute("UPDATE posts_4chan SET board = ( SELECT board FROM threads_4chan WHERE id = posts_4chan.thread_id )")

print("  Creating index")
db.execute("CREATE UNIQUE INDEX IF NOT EXISTS posts_4chan_id ON posts_4chan ( id, board )")