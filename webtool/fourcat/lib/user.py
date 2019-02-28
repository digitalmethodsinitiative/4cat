"""
User class
"""
import bcrypt

from fourcat import db, app, config


class User:
	"""
	User class

	Compatible with Flask-Login
	"""
	data = {}
	is_authenticated = False
	is_active = False
	is_anonymous = True

	name = "anonymous"

	def get_by_login(name, password):
		"""
		Get user object, if login is correct

		If the login data supplied to this method is correct, a new user object
		that is marked as authenticated is returned.

		:param name:  User name
		:param password:  User password
		:return:  User object, or `None` if login was invalid
		"""
		user = db.fetchone("SELECT * FROM users WHERE name = %s", (name,))
		if not user or not bcrypt.checkpw(password.encode("ascii"), user["password"].encode("ascii")):
			return None
		else:
			return User(user, authenticated=True)

	def get_by_name(name):
		"""
		Get user object for given user name

		:return:  User object, or `None` for invalid user name
		"""
		user = db.fetchone("SELECT * FROM users WHERE name = %s", (name,))
		if not user:
			return None
		else:
			return User(user)

	def __init__(self, data, authenticated=False):
		"""
		Instantiate user object

		Also sets the properties required by Flask-Login.

		:param data:  User data
		:param authenticated:  Whether the user should be marked as authenticated
		"""
		self.data = data

		if self.data["name"] != "anonymous":
			self.is_anonymous = False
			self.is_active = True

		self.name = self.data["name"]
		if authenticated:
			print("Authenticating %s" % data["name"])
		self.is_authenticated = authenticated

	def authenticate(self):
		"""
		Mark user object as authenticated.
		"""
		self.is_authenticated = True

	def get_id(self):
		"""
		Get user ID

		:return:  User ID
		"""
		return self.data["name"]

	def get_name(self):
		"""
		Get user name

		This is usually the user ID. For the two special users, provide a nicer
		name to display in interfaces, etc.

		:return: User name
		"""
		if self.data["name"] == "anonymous":
			return "Anonymous"
		elif self.data["name"] == "autologin":
			return config.FlaskConfig.HOSTNAME_WHITELIST_NAME
		else:
			return self.data["name"]

	def is_special(self):
		"""
		Check if user is special user

		:return:  Whether the user is the anonymous user, or the automatically
		logged in user.
		"""
		return self.get_id() in ("autologin", "anonymous")

	def set_password(self, password):
		"""
		Set user password

		:param password:  Password to set
		"""
		if self.is_anonymous:
			raise Exception("Cannot set password for anonymous user")

		salt = bcrypt.gensalt()
		password_hash = bcrypt.hashpw(password.encode("ascii"), salt)

		db.update("users", where={"name": self.data["name"]}, data={"password": password_hash.decode("utf-8")})
