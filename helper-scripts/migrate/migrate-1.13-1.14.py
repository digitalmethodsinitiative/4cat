# update database structure for chan tables to save post deletion timestamp
# separately from main table
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "'/../..")
from common.lib.database import Database
from common.lib.logger import Logger

import config

log = Logger(output=True)
db = Database(logger=log, dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD, host=config.DB_HOST, port=config.DB_PORT, appname="4cat-migrate")

for datasource in ("4chan", "8kun", "8chan"):
	print("  Checking for %s database tables... " % datasource, end="")
	test = db.fetchone("SELECT EXISTS ( SELECT FROM information_schema.tables WHERE table_schema = %s AND table_name = %s )", ("public", "posts_%s" % datasource))
	if not test["exists"]:
		print("not available, nothing to upgrade!")
		continue

	print("\n  Checking if required table exists... ", end="")
	test = db.fetchone(
		"SELECT EXISTS ( SELECT FROM information_schema.tables WHERE table_schema = %s AND table_name = %s )",
		("public", "posts_%s_deleted" % datasource))
	columns = [row["column_name"] for row in db.fetchall("SELECT column_name FROM information_schema.columns WHERE table_name = %s", ("posts_%s" % datasource,))]
	if test["exists"]:
		print("yes!")
		continue

	print("no, creating table posts_%s_deleted... " % datasource, end="")
	db.execute("CREATE TABLE IF NOT EXISTS posts_%s_deleted ( id_seq BIGINT PRIMARY KEY, timestamp_deleted BIGINT DEFAULT 0 )" % datasource)
	print("done")

	print("  Filling table (this can take a while)... ", end="")
	db.execute("INSERT INTO posts_%s_deleted ( SELECT id_seq, timestamp_deleted FROM posts_%s WHERE timestamp_deleted != 0 )" % (datasource, datasource))
	print("done")

	print("  Dropping column timestamp_deleted from main table...", end="")
	db.execute("ALTER TABLE posts_%s DROP COLUMN timestamp_deleted" % datasource)

	print("done!")