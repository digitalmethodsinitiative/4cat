# For local imageboard datasources, make sure that the id_seq is the primary key.
# Also make sure there are indexes for id-board pairs for both the posts and threads tables.
import sys
import os

from psycopg2.errors import UniqueViolation

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "'/../..")
from common.lib.database import Database
from common.lib.logger import Logger

import config

log = Logger(output=True)
db = Database(logger=log, dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD, host=config.DB_HOST, port=config.DB_PORT, appname="4cat-migrate")

for datasource in ("4chan", "8kun", "8chan"):
	print("  Checking for %s database tables... " % datasource, end="")

	table = db.fetchone("SELECT EXISTS ( SELECT FROM information_schema.tables WHERE table_schema = %s AND table_name = %s )", ("public", "posts_%s" % datasource))
	if not table["exists"]:
		print("not available, nothing to upgrade!")
		continue

	# Remove and add unique key constraints for threads table
	print("\n  Checking if id_seq is the primary threads key... ")

	thread_constraints = [(row["column_name"], row["constraint_name"]) for row in db.fetchall("SELECT c.column_name, c.constraint_name FROM information_schema.key_column_usage AS c LEFT JOIN information_schema.table_constraints AS t ON t.constraint_name = c.constraint_name WHERE t.table_name = 'threads_%s' AND t.constraint_type = 'PRIMARY KEY';" % datasource)]

	make_primary_threads_key = False

	if not thread_constraints:
		print("  No unique key detected for the threads table, adding a unique key constraint to the `id_seq` column.")
		make_primary_threads_key = True
	else:
		constraint_col, constraint_name = thread_constraints[0]
		
		if constraint_col == "id_seq":
			print("  id_seq already the primary key for threads %s" % datasource)
		else:
			print(" changing primary threads key from %s to id_seq (this might take a while)." % constraint_col)
			make_primary_threads_key = True
			db.execute("ALTER TABLE threads_%s DROP CONSTRAINT %s" % (datasource, constraint_name))

	if make_primary_threads_key:
		try:
			db.execute("ALTER TABLE threads_%s ADD PRIMARY KEY (id_seq)" % datasource)
		except UniqueViolation:
			print("  Encountered duplicate id_seq value, rebuilding the column.")
			db.execute("ALTER TABLE threads_%s DROP COLUMN id_seq" % datasource)
			db.execute("ALTER TABLE threads_%s ADD COLUMN id_seq SERIAL PRIMARY KEY" % datasource)

	# Remove and add unique key constraints for posts table
	print("  Checking if id_seq is the primary posts key... ")

	post_constraints = [(row["column_name"], row["constraint_name"]) for row in db.fetchall("SELECT c.column_name, c.constraint_name FROM information_schema.key_column_usage AS c LEFT JOIN information_schema.table_constraints AS t ON t.constraint_name = c.constraint_name WHERE t.table_name = 'posts_%s' AND t.constraint_type = 'PRIMARY KEY';" % datasource)]

	make_primary_posts_key = False

	if not post_constraints:
		print("  No unique key detected for the posts table, adding a unique key constraint to the `id_seq` column.")
		make_primary_posts_key = True
	else:
		constraint_col, constraint_name = post_constraints[0]
		
		if constraint_col == "id_seq":
			print("  id_seq already the primary key for posts %s" % datasource)
		else:
			print(" changing primary posts key from %s to id_seq (this might take a while)." % constraint_col)
			make_primary_posts_key = True
			db.execute("ALTER TABLE posts_%s DROP CONSTRAINT %s" % (datasource, constraint_name))

	if make_primary_posts_key:
		try:
			db.execute("ALTER TABLE posts_%s ADD PRIMARY KEY (id_seq)" % datasource)
		except UniqueViolation:
			print("  Encountered duplicate id_seq value, rebuilding the entire column.")
			db.execute("ALTER TABLE posts_%s DROP COLUMN id_seq" % datasource)
			db.execute("ALTER TABLE posts_%s ADD COLUMN id_seq SERIAL PRIMARY KEY" % datasource)

	print("  Making indexes for post-board pairs")

	print("  Creating unique index constraints for id-board pairs for posts table")
	db.execute("DROP INDEX IF EXISTS posts_id")
	db.execute("DROP INDEX IF EXISTS posts_%s_id" % datasource)
	db.execute("CREATE UNIQUE INDEX IF NOT EXISTS posts_%s_idboard ON posts_%s ( id, board )" % (datasource, datasource))
	print("  Creating unique index constraints for id-board pairs for threads table")
	db.execute("DROP INDEX IF EXISTS threads_id")
	db.execute("DROP INDEX IF EXISTS threads_%s_id" % datasource)
	db.execute("CREATE UNIQUE INDEX IF NOT EXISTS threads_%s_idboard ON threads_%s ( id, board )" % (datasource, datasource))

print("  Done!")