# For local imageboard datasources, make sure that the id_seq is the primary key.
# Also make sure there are indexes for id-board pairs for both the posts and threads tables.
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

	print("\n  Checking if id_seq is the primary threads key... ")
	threads_primary_key_col = [row["column_name"] for row in db.fetchall("SELECT c.column_name FROM information_schema.key_column_usage AS c LEFT JOIN information_schema.table_constraints AS t ON t.constraint_name = c.constraint_name WHERE t.table_name = 'threads_%s' AND t.constraint_type = 'PRIMARY KEY';" % datasource)][0]
	if threads_primary_key_col == "id_seq":
		print("  id_seq already the primary key for threads %s" % datasource)
	else:
		print(" changing primary threads key from %s to id_seq" % threads_primary_key_col)
		db.execute("ALTER TABLE threads_%s DROP CONSTRAINT threads_%s_pkey" % (datasource, datasource))
		db.execute("ALTER TABLE threads_%s ADD PRIMARY KEY (id_seq)" % datasource)

	print("  Checking if id_seq is the primary posts key... ")
	posts_primary_key_col = [row["column_name"] for row in db.fetchall("SELECT c.column_name FROM information_schema.key_column_usage AS c LEFT JOIN information_schema.table_constraints AS t ON t.constraint_name = c.constraint_name WHERE t.table_name = 'posts_%s' AND t.constraint_type = 'PRIMARY KEY';" % datasource)][0]
	if posts_primary_key_col == "id_seq":
		print("  id_seq already the primary key for posts %s" % datasource)
	else:
		print(" changing primary posts key from %s to id_seq" % posts_primary_key_col)
		db.execute("ALTER TABLE posts_%s DROP CONSTRAINT posts_%s_pkey" % (datasource, datasource))
		db.execute("ALTER TABLE posts_%s ADD PRIMARY KEY (id_seq)" % datasource)

	print("  Making indexes for post-board pairs")

	print("  Creating unique index constraints for id-board pairs for posts table")
	db.execute("DROP INDEX IF EXISTS posts_id")
	db.execute("CREATE UNIQUE INDEX IF NOT EXISTS posts_%s_idboard ON posts_%s ( id, board )" % (datasource, datasource))
	print("  Creating unique index constraints for id-board pairs for threads table")
	db.execute("DROP INDEX IF EXISTS threads_id")
	db.execute("CREATE UNIQUE INDEX IF NOT EXISTS threads_%s_idboard ON threads_%s ( id, board )" % (datasource, datasource))

print("  Done!")