"""
Create a new 4CAT user and send them a registration e-mail
"""
import argparse
import psycopg2
import time
import sys
import re
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/..")

from common.lib.database import Database
from common.lib.logger import Logger
from webtool.lib.user import User

log = Logger()
db = Database(logger=log, appname="create-user")

cli = argparse.ArgumentParser()
cli.add_argument("-u", "--username", required=True, help="Name of user (must be unique)")
cli.add_argument("-p", "--password", help="Password (if left empty an e-mail will be sent to the user to reset it)")
cli.add_argument("-e", "--noemail", help="Do not force an e-mail as username", action="store_true")
cli.add_argument("-a", "--admin", help="Make this user an admin user", action="store_true")

args = cli.parse_args()

if __name__ != "__main__":
	sys.exit(1)

if not args.noemail and not re.match(r"[^@]+\@.*?\.[a-zA-Z]+", args.username):
	print("Please provide an e-mail address as username.")
	sys.exit(1)

try:
	db.insert("users", data={"name": args.username, "timestamp_token": int(time.time()), "is_admin": args.admin})
except psycopg2.IntegrityError:
	print("Error: User %s already exists." % args.username)
	sys.exit(1)

user = User.get_by_name(args.username)
if user is None:
	print("Warning: User not created properly. No password reset e-mail sent.")
	sys.exit(1)

if args.password:
	user.set_password(args.password)
	print("User created and password set!")
else:
	if args.noemail:
		user.generate_token()
		print("User created! No registration e-mail will be sent.")
		print("%s can complete their registration via the following token:\n%s" % (args.username, user.get_token()))
	else:
		try:
			user.email_token(new=True)
			print("An e-mail containing a link through which the registration can be completed has been sent to %s." % args.username)
		except RuntimeError as e:
			print("""
WARNING: User created but no e-mail was sent. The following exception was raised:
   %s
	   
%s can complete their registration via the following token:
   %s""" % (e, args.username, user.get_token()))