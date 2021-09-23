# this should have been done in the 1.9 -> 1.10 migration script, but alas...
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "'/../..")
from common.lib.database import Database
from common.lib.logger import Logger

import config

log = Logger(output=True)
db = Database(logger=log, dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD, host=config.DB_HOST, port=config.DB_PORT, appname="4cat-migrate")

for datasource in ("8kun", "8chan"):
	print("  Checking for %s database tables... " % datasource, end="")

	test = db.fetchone("SELECT EXISTS ( SELECT FROM information_schema.tables WHERE table_schema = %s AND table_name = %s )", ("public", "posts_%s" % datasource))
	if not test["exists"]:
		print("not available, nothing to upgrade!")
		continue

	print("  Checking if required columns exist... ", end="")
	columns = [row["column_name"] for row in db.fetchall("SELECT column_name FROM information_schema.columns WHERE table_name = %s", ("posts_%s" % datasource,))]
	if "board" in columns:
		print("yes!")
	else:
		print(" adding 'board' column to %s posts table" % datasource)
		db.execute("ALTER TABLE posts_%s ADD COLUMN board TEXT DEFAULT ''" % datasource)

	print("  Filling 'board' column (this can take a while)")
	db.execute("UPDATE posts_%s SET board = ( SELECT board FROM threads_%s WHERE id = posts_%s.thread_id )" % (datasource, datasource, datasource))

	print("  Creating index")
	db.execute("CREATE UNIQUE INDEX IF NOT EXISTS posts_%s_id ON posts_%s ( id, board )" % (datasource, datasource))