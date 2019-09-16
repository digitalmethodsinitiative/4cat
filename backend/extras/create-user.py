import argparse
import psycopg2
import time
import sys
import re
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/../..")

from backend.lib.database import Database
from backend.lib.logger import Logger
from webtool.lib.user import User

log = Logger()
db = Database(logger=log, appname="create-user")

cli = argparse.ArgumentParser()
cli.add_argument("-u", "--username", required=True, help="Name of user (must be unique)")

args = cli.parse_args()

if __name__ != "__main__":
	sys.exit(1)

if not re.match(r"[^@]+\@.*?\.[a-zA-Z]+", args.username):
	print("Please provide an e-mail address as username.")
	sys.exit(1)

try:
	db.insert("users", data={"name": args.username, "timestamp_token": int(time.time())})
except psycopg2.IntegrityError:
	print("Error: User %s already exists." % args.username)
	sys.exit(1)

user = User.get_by_name(args.username)
if user is None:
	print("Warning: User not created properly. No password reset e-mail sent.")
	sys.exit(1)

try:
	user.email_token(new=True)
	print("An e-mail containing a link through which the registration can be completed has been sent to %s." % args.username)
except RuntimeError as e:
	print("""
WARNING: User registered but no e-mail was sent. The following exception was raised:
   %s
   
%s can complete their registration via the following token:
   %s""" % (e, args.username, user.get_token()))