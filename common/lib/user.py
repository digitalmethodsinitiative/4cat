"""
User class
"""
import html2text
import hashlib
import smtplib
import socket
import bcrypt
import json
import time
import os

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from common.lib.helpers import send_email
from common.lib.exceptions import DataSetException
from common.config_manager import config


class User:
    """
    User class

    Compatible with Flask-Login
    """
    data = None
    userdata = None
    is_authenticated = False
    is_active = False
    is_anonymous = True
    db = None

    name = "anonymous"

    @staticmethod
    def get_by_login(db, name, password):
        """
        Get user object, if login is correct

        If the login data supplied to this method is correct, a new user object
        that is marked as authenticated is returned.

        :param db:  Database connection object
        :param name:  User name
        :param password:  User password
        :return:  User object, or `None` if login was invalid
        """
        user = db.fetchone("SELECT * FROM users WHERE name = %s", (name,))
        if not user or not user.get("password", None):
            # registration not finished yet
            return None
        elif not user or not bcrypt.checkpw(password.encode("ascii"), user["password"].encode("ascii")):
            # non-existing user or wrong password
            return None
        else:
            # valid login!
            return User(db, user, authenticated=True)

    @staticmethod
    def get_by_name(db, name):
        """
        Get user object for given user name

        :param db:  Database connection object
        :param str name:  Username to get object for
        :return:  User object, or `None` for invalid user name
        """
        user = db.fetchone("SELECT * FROM users WHERE name = %s", (name,))
        if not user:
            return None
        else:
            return User(db, user)

    @staticmethod
    def get_by_token(db, token):
        """
        Get user object for given token, if token is valid

        :param db:  Database connection object
        :param str token:  Token to get object for
        :return:  User object, or `None` for invalid token
        """
        user = db.fetchone(
            "SELECT * FROM users WHERE register_token = %s AND (timestamp_token = 0 OR timestamp_token > %s)",
            (token, int(time.time()) - (7 * 86400)))
        if not user:
            return None
        else:
            return User(db, user)

    def can_access_dataset(self, dataset, role=None):
        """
        Check if this user should be able to access a given dataset.

        This depends mostly on the dataset's owner, which should match the
        user if the dataset is private. If the dataset is not private, or
        if the user is an admin or the dataset is private but assigned to
        an anonymous user, the dataset can be accessed.

        :param dataset:  The dataset to check access to
        :return bool:
        """
        if not dataset.is_private:
            return True

        elif self.is_admin:
            return True

        elif dataset.is_accessible_by(self, role=role):
            return True

        elif dataset.get_owners == ("anonymous",):
            return True

        else:
            return False

    def __init__(self, db, data, authenticated=False):
        """
        Instantiate user object

        Also sets the properties required by Flask-Login.

        :param db:  Database connection object
        :param data:  User data
        :param authenticated:  Whether the user should be marked as authenticated
        """
        self.db = db
        self.data = data
        try:
            self.userdata = json.loads(self.data["userdata"])
        except (TypeError, json.JSONDecodeError):
            self.userdata = {}

        if self.data["name"] != "anonymous":
            self.is_anonymous = False
            self.is_active = True

        self.name = self.data["name"]
        self.is_authenticated = authenticated

        self.userdata = json.loads(self.data.get("userdata", "{}"))

        if not self.is_anonymous and self.is_authenticated:
            self.db.update("users", where={"name": self.data["name"]}, data={"timestamp_seen": int(time.time())})

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
            return config.get("flask.autologin.name")
        else:
            return self.data["name"]

    def get_token(self):
        """
        Get password reset token

        May be empty or invalid!

        :return str: Password reset token
        """
        return self.generate_token(regenerate=False)

    def clear_token(self):
        """
        Reset password rest token

        Clears the token and token timestamp. This allows requesting a new one
        even if the old one had not expired yet.

        :return:
        """
        self.db.update("users", data={"register_token": "", "timestamp_token": 0}, where={"name": self.get_id()})

    @property
    def is_special(self):
        """
        Check if user is special user

        :return:  Whether the user is the anonymous user, or the automatically
        logged in user.
        """
        return self.get_id() in ("autologin", "anonymous")

    @property
    def is_admin(self):
        """
        Check if user is an administrator

        :return bool:
        """
        try:
            return "admin" in self.data["tags"]
        except (ValueError, TypeError) as e:
            # invalid JSON?
            return False

    @property
    def is_deactivated(self):
        """
        Check if user has been deactivated

        :return bool:
        """
        return self.data.get("is_deactivated", False)

    def email_token(self, new=False):
        """
        Send user an e-mail with a password reset link

        Generates a token that the user can use to reset their password. The
        token is valid for 72 hours.

        Note that this requires a mail server to be configured, or a
        `RuntimeError` will be raised. If a server is configured but the mail
        still fails to send, it will also raise a `RuntimeError`. Note that
        in these cases a token is still created and valid (the user just gets
        no notification, but an admin could forward the correct link).

        If the user is a 'special' user, a `ValueError` is raised.

        :param bool new:  Is this the first time setting a password for this
                          account?
        :return str:  Link for the user to set their password with
        """
        if not config.get('mail.server'):
            raise RuntimeError("No e-mail server configured. 4CAT cannot send any e-mails.")

        if self.is_special:
            raise ValueError("Cannot send password reset e-mails for a special user.")

        username = self.get_id()

        # generate a password reset token
        register_token = self.generate_token(regenerate=True)

        # prepare welcome e-mail
        sender = config.get('mail.noreply')
        message = MIMEMultipart("alternative")
        message["From"] = sender
        message["To"] = username

        # the actual e-mail...
        url_base = config.get("flask.server_name")
        protocol = "https" if config.get("flask.https") else "http"
        url = "%s://%s/reset-password/?token=%s" % (protocol, url_base, register_token)

        # we use slightly different e-mails depending on whether this is the first time setting a password
        if new:

            message["Subject"] = "Account created"
            mail = """
			<p>Hello %s,</p>
			<p>A 4CAT account has been created for you. You can now log in to 4CAT at <a href="%s://%s">%s</a>.</p>
			<p>Note that before you log in, you will need to set a password. You can do so via the following link:</p>
			<p><a href="%s">%s</a></p> 
			<p>Please complete your registration within 72 hours as the link above will become invalid after this time.</p>
			""" % (username, protocol, url_base, url_base, url, url)
        else:

            message["Subject"] = "Password reset"
            mail = """
			<p>Hello %s,</p>
			<p>Someone has requested a password reset for your 4CAT account. If that someone is you, great! If not, feel free to ignore this e-mail.</p>
			<p>You can change your password via the following link:</p>
			<p><a href="%s">%s</a></p> 
			<p>Please do this within 72 hours as the link above will become invalid after this time.</p>
			""" % (username, url, url)

        # provide a plain-text alternative as well
        html_parser = html2text.HTML2Text()
        message.attach(MIMEText(html_parser.handle(mail), "plain"))
        message.attach(MIMEText(mail, "html"))

        # try to send it
        try:
            send_email([username], message)
            return url
        except (smtplib.SMTPException, ConnectionRefusedError, socket.timeout) as e:
            raise RuntimeError("Could not send password reset e-mail: %s" % e)

    def generate_token(self, username=None, regenerate=True):
        """
        Generate and store a new registration token for this user

        Tokens are not re-generated if they exist already

        :param username:  Username to generate for: if left empty, it will be
        inferred from self.data
        :param regenerate:  Force regenerating even if token exists
        :return str:  The token
        """
        if self.data.get("register_token", None) and not regenerate:
            return self.data["register_token"]

        if not username:
            username = self.data["name"]

        register_token = hashlib.sha256()
        register_token.update(os.urandom(128))
        register_token = register_token.hexdigest()
        self.db.update("users", data={"register_token": register_token, "timestamp_token": int(time.time())},
                       where={"name": username})

        return register_token

    def get_value(self, key, default=None):
        """
        Get persistently stored user property

        :param key:  Name of item to get
        :param default:  What to return if key is not avaiable (default None)
        :return:
        """
        return self.userdata.get(key, default)

    def set_value(self, key, value):
        """
        Set persistently stored user property

        :param key:  Name of item to store
        :param value:  Value
        :return:
        """
        self.userdata[key] = value
        self.data["userdata"] = json.dumps(self.userdata)

        self.db.update("users", where={"name": self.get_id()}, data={"userdata": json.dumps(self.userdata)})

    def set_password(self, password):
        """
        Set user password

        :param password:  Password to set
        """
        if self.is_anonymous:
            raise Exception("Cannot set password for anonymous user")

        salt = bcrypt.gensalt()
        password_hash = bcrypt.hashpw(password.encode("ascii"), salt)

        self.db.update("users", where={"name": self.data["name"]}, data={"password": password_hash.decode("utf-8")})

    def add_notification(self, notification, expires=None, allow_dismiss=True):
        """
        Add a notification for this user

        Notifications that already exist with the same parameters are not added
        again.

        :param str notification:  The content of the notification. Can contain
        Markdown.
        :param int expires:  Timestamp when the notification should expire. If
        not provided, the notification does not expire
        :param bool allow_dismiss:  Whether to allow a user to dismiss the
        notification.
        """
        self.db.insert("users_notifications", {
            "username": self.get_id(),
            "notification": notification,
            "timestamp_expires": expires,
            "allow_dismiss": allow_dismiss
        }, safe=True)

    def dismiss_notification(self, notification_id):
        """
        Dismiss a notification

        The user can only dismiss their own notifications!

        :param int notification_id:  ID of the notification to dismiss
        """
        self.db.execute("DELETE FROM users_notifications WHERE id IN ( SELECT n.id FROM users_notifications AS n, users AS u "
            "WHERE u.name = %s AND n.id = %s "
            "AND (u.name = n.username OR (u.tags @> '[\"admin\"]' AND n.username = '!admins') OR n.username = '!everyone'))", (self.get_id(), notification_id))

    def get_notifications(self):
        """
        Get all notifications for this user

        That is all the user's own notifications, plus those for the groups of
        users this user belongs to

        :return list:  Notifications, as a list of dictionaries
        """
        notifications = self.db.fetchall(
            "SELECT n.* FROM users_notifications AS n, users AS u "
            "WHERE u.name = %s "
            "AND (u.name = n.username OR (u.tags @> '[\"admin\"]' AND n.username = '!admins') OR n.username = '!everyone')", (self.get_id(),))

        return notifications

    def add_tag(self, tag):
        """
        Add tag to user

        If the tag is already in the tag list, nothing happens.

        :param str tag:  Tag
        """
        if tag not in self.data["tags"]:
            self.data["tags"].append(tag)
            self.sort_user_tags()

    def remove_tag(self, tag):
        """
        Remove tag from user

        If the tag is not part of the tag list, nothing happens.

        :param str tag:  Tag
        """
        if tag in self.data["tags"]:
            self.data["tags"].remove(tag)
            self.sort_user_tags()

    def sort_user_tags(self):
        """
        Ensure user tags are stored in the correct order

        The order of the tags matters, since it decides which one will get to
        override the global configuration. To avoid having to cross-reference
        the canonical order every time the tags are queried, we ensure that the
        tags are stored in the database in the right order to begin with. This
        method ensures that.
        """
        tags = self.data["tags"]
        sorted_tags = []

        for tag in config.get("flask.tag_order"):
            if tag in tags:
                sorted_tags.append(tag)

        for tag in tags:
            if tag not in sorted_tags:
                sorted_tags.append(tag)

        # whitespace isn't a tag
        sorted_tags = [tag for tag in sorted_tags if tag.strip()]

        self.data["tags"] = sorted_tags
        self.db.update("users", where={"name": self.get_id()}, data={"tags": json.dumps(sorted_tags)})



    def delete(self, also_datasets=True):
        from common.lib.dataset import DataSet

        username = self.data["name"]

        self.db.delete("users_favourites", where={"name": username}, commit=False),
        self.db.delete("users_notifications", where={"username": username}, commit=False)
        self.db.delete("access_tokens", where={"name": username}, commit=False)

        # find datasets and delete
        datasets = self.db.fetchall("SELECT key FROM datasets_owners WHERE name = %s", (username,))

        # delete any datasets and jobs related to deleted datasets
        if datasets:
            for dataset in datasets:
                try:
                    dataset = DataSet(key=dataset["key"], db=self.db)
                except DataSetException:
                    # dataset already deleted?
                    continue

                if len(dataset.get_owners()) == 1 and also_datasets:
                    dataset.delete(commit=False)
                    self.db.delete("jobs", where={"remote_id": dataset.key}, commit=False)
                else:
                    dataset.remove_owner(self)

        # and finally the user
        self.db.delete("users", where={"name": username}, commit=False)
        self.db.commit()

    def __getattr__(self, attr):
        """
        Getter so we don't have to use .data all the time

        :param attr:  Data key to get
        :return:  Value
        """

        if attr in dir(self):
            # an explicitly defined attribute should always be called in favour
            # of this passthrough
            attribute = getattr(self, attr)
            return attribute
        elif attr in self.data:
            return self.data[attr]
        else:
            raise AttributeError("User object has no attribute %s" % attr)

    def __setattr__(self, attr, value):
        """
        Setter so we can flexibly update the database

        Also updates internal data stores (.data etc). If the attribute is
        unknown, it is stored within the 'userdata' attribute.

        :param str attr:  Attribute to update
        :param value:  New value
        """

        # don't override behaviour for *actual* class attributes
        if attr in dir(self):
            super().__setattr__(attr, value)
            return

        if attr not in self.data:
            self.userdata[attr] = value
            attr = "userdata"
            value = self.userdata

        if attr == "userdata":
            value = json.dumps(value)

        self.db.update("users", where={"name": self.get_id()}, data={attr: value})

        self.data[attr] = value

        if attr == "userdata":
            self.userdata = json.loads(value)
