import argparse
import psycopg2
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + '/..')

from backend.lib.database import Database
from backend.lib.logger import Logger
from fourcat.lib.user import User

log = Logger()
db = Database(logger=log)

cli = argparse.ArgumentParser()
cli.add_argument("-u", "--username", required=True, help="Name of user (must be unique)")
cli.add_argument("-p", "--password", required=True, help="Password")

args = cli.parse_args()

if __name__ == "__main__":
	try:
		db.insert("users", data={"name": args.username})
		user = User.get_by_name(args.username)
		user.set_password(args.password)
		print("Created user %s" % args.username)
	except psycopg2.IntegrityError:
		print("Error: User %s already exists." % args.username)