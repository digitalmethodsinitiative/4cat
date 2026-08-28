"""
Delete old items
"""

import datetime
import smtplib
import time
import re

from backend.lib.worker import BasicWorker
from common.lib.dataset import DataSet
from common.lib.exceptions import DataSetNotFoundException, WorkerInterruptedException

from common.lib.user import User
from common.config_manager import ConfigWrapper
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from common.lib.helpers import send_email


class ThingExpirer(BasicWorker):
    """
    Delete old items

    Deletes expired datasets. This may be useful for two reasons: to conserve
    disk space and if the user agreement of a particular data source does not
    allow storing scraped or extracted data for longer than a given amount of
    time, as is the case for e.g. Tumblr.

    Also deletes users that have an expiration date that is not zero. Users
    with a close expiration date get a notification.

    Also deletes expired notifications.
    """

    type = "expire-datasets"
    max_workers = 1

    expiry_notification_after_days = 7

    # datasets that have not finished after this many seconds are considered
    # abandoned: their sensitive option values (e.g. API keys) are removed,
    # which normally happens as soon as a dataset starts running
    abandoned_dataset_age = 7 * 86400

    # every account deletion warning starts with this, which lets us find and
    # remove an existing warning when it is no longer accurate
    expiry_notification_prefix = "WARNING: This account will be deleted"

    @classmethod
    def ensure_job(cls, config=None):
        """
        Ensure that the expirer is always running

        This is used to ensure that the expirer is always running, and if it is
        not, it will be started by the WorkerManager.

        :return:  Job parameters for the worker
        """
        return {"remote_id": "localhost", "interval": 1800}

    def work(self):
        """
        Delete datasets, users and notifications
        """

        self.expire_datasets()
        self.expire_users()
        self.expire_notifications()
        self.expire_sensitive_parameters()

        self.job.finish()

    def expire_datasets(self):
        """
        Delete expired datasets
        """
        # find candidates
        # todo: make this better - this can be a lot of datasets!
        datasets = self.db.fetchall("""
                                    SELECT *
                                    FROM datasets
                                    WHERE parameters::json->>'keep' IS NULL
                                    AND key_parent = ''
                                    """)

        # instantiating config wrappers can get expensive, so cache per user
        wrappers = {}

        for dataset in datasets:
            # we only check datasets with no parent, because child datasets
            # inherit the ownership of the parent, and child datasets are
            # deleted when the parent is deleted
            if self.interrupted:
                raise WorkerInterruptedException("Interrupted while expiring datasets")

            # this is a relatively expensive loop that should not block other
            # things, so add a small time.sleep() to give python's interpreter
            # some breathing room
            time.sleep(0.01)

            # the dataset creator's configuration context determines expiration
            try:
                if dataset["creator"] not in wrappers:
                    wrapper = ConfigWrapper(
                        self.config, user=User.get_by_name(self.db, dataset["creator"])
                    )
                    # pre-read expiration
                    wrappers[dataset["creator"]] = (wrapper, wrapper.get("datasources.expiration"))

                wrapper, expiration = wrappers[dataset["creator"]]
                dataset = DataSet(data=dataset, db=self.db, modules=self.modules, check_owners=False)

                if not dataset.parameters.get("expires-after") and not expiration.get(dataset.parameters.get("datasource")):
                    # is_expired() is expensive, so do some pre-checking
                    continue

                if dataset.is_expired(config=wrapper):
                    self.log.info(f"Deleting dataset {dataset.key} (expired)")
                    dataset.delete(commit=False)

            except DataSetNotFoundException:
                # dataset already deleted I guess?
                pass

            finally:
                self.db.commit()

    def expire_sensitive_parameters(self):
        """
        Remove sensitive option values from abandoned datasets

        Sensitive option values (e.g. API keys) are removed from a dataset's
        stored parameters as soon as it starts running (top-level values), and
        from its `next` chain once its follow-up datasets are created. A
        dataset that is created but never picked up by a worker - for example
        because the backend was stopped for good before it could run, or one
        that keeps crashing before finishing - would keep those values forever,
        so remove both here once the dataset is old enough to be considered
        abandoned. An abandoned dataset never created its follow-ups, so
        clearing its `next` chain is safe.
        """
        cutoff = int(time.time()) - self.abandoned_dataset_age
        abandoned = self.db.fetchall(
            "SELECT * FROM datasets WHERE is_finished = FALSE AND timestamp < %s",
            (cutoff,))
        self.log.debug(f"Found {len(abandoned)} abandoned datasets; cleaning up sensitive parameters if present.")

        wrappers = {}
        for dataset_data in abandoned:
            if self.interrupted:
                raise WorkerInterruptedException("Interrupted while cleaning up abandoned datasets")

            try:
                # which options exist (and which are sensitive) can depend on
                # the dataset owner's configuration context
                if dataset_data["creator"] not in wrappers:
                    wrappers[dataset_data["creator"]] = ConfigWrapper(
                        self.config, user=User.get_by_name(self.db, dataset_data["creator"])
                    )

                dataset = DataSet(data=dataset_data, db=self.db, modules=self.modules, check_owners=False)
                dataset.remove_sensitive_parameters(config=wrappers[dataset_data["creator"]])
                dataset.remove_sensitive_parameters_from_next(config=wrappers[dataset_data["creator"]])

            except DataSetNotFoundException:
                # deleted in the meantime
                continue

            except Exception as e:
                # cleaning up must not crash the worker; try again next run
                self.log.warning(f"Could not remove sensitive parameters of dataset {dataset_data['key']}: {e}")

    def expire_users(self):
        """
        Delete expired users

        Users can have a `delete-after` parameter in their user data which
        indicates a date or time after which the account should be deleted.

        The date can be in YYYY-MM-DD format or a unix (UTC) timestamp. If
        the current date is after the given date the account is deleted. If the
        expiration date is within 7 days a notification is added for the user
        to warn them.
        """
        expiring_users = self.db.fetchall(
            "SELECT * FROM users WHERE userdata::json->>'delete-after' IS NOT NULL;"
        )
        now = datetime.datetime.now()

        for expiring_user in expiring_users:
            if self.interrupted:
                raise WorkerInterruptedException("Interrupted while expiring users")

            user = User(db=self.db, data=expiring_user, config=self.config)
            username = user.data["name"]

            # parse expiration date if available
            delete_after = user.get_value("delete-after")
            if not delete_after:
                # deletion may have been called off, in which case an earlier
                # warning about it should no longer be shown
                self.clear_expiry_notifications(username)
                continue

            if re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", str(delete_after)):
                expires_at = datetime.datetime.strptime(delete_after, "%Y-%m-%d")
            elif re.match(r"^[0-9]+$", str(delete_after)):
                expires_at = datetime.datetime.fromtimestamp(int(delete_after))
            else:
                self.log.warning(
                    f"User {username} has invalid expiration date {delete_after}"
                )
                # we cannot tell when the account will be deleted, so any
                # warning mentioning a date would be misleading
                self.clear_expiry_notifications(username)
                continue

            # check if expired...
            if expires_at < now:
                self.log.info(f"User {username} expired - deleting user and datasets")
                user.delete(modules=self.modules)
            else:
                expires_at_human = expires_at.strftime("%-d %B %Y %H:%M")
                expires_at_machine = expires_at.strftime("%Y-%m-%dT%H:%M")

                warning_notification = f'{self.expiry_notification_prefix} at <time datetime="{expires_at_machine}">{expires_at_human}</time>. Make sure to back up your data before then.'

                # if the deletion date was changed an older warning may still
                # be around, mentioning a date that is no longer correct. Both
                # queries run in one transaction, so the user never sees a
                # moment without a warning
                self.clear_expiry_notifications(username, commit=False)
                user.add_notification(warning_notification, allow_dismiss=False)

                # only warn by e-mail if the account will be deleted within 7 days
                if expires_at - now > datetime.timedelta(days=self.expiry_notification_after_days):
                    continue

                # we remember which deletion date we last sent an e-mail about,
                # so that if that date is moved the user is warned again
                notice_for = int(expires_at.timestamp())
                notice = user.get_value("expiry-email-sent", default=None)
                if not isinstance(notice, dict) or notice.get("expires") != notice_for:
                    # nothing sent for this date yet. Older versions of 4CAT
                    # stored the time of sending here instead of the date that
                    # was warned about, so such a value counts as 'not sent'
                    notice = {"expires": notice_for, "status": None}

                if notice["status"] in ("sent", "failed"):
                    continue

                # ensure mail is configured on this server and username looks like an email
                if not self.config.get("mail.server") or not re.match(r"[^@\s]+@[^@\s]+\.[^@\s]+\Z", username):
                    continue

                try:
                    msg = MIMEMultipart("alternative")
                    msg["From"] = self.config.get("mail.noreply")
                    msg["To"] = username
                    msg["Subject"] = "4CAT account expiration warning"

                    plain = (
                        f"Your 4CAT account '{username}' is scheduled for deletion on {expires_at_human}.\n"
                        "Please back up your data before then."
                    )

                    html = (
                        f"<p>Your 4CAT account <strong>{username}</strong> is scheduled for deletion at "
                        f"<time datetime=\"{expires_at_machine}\">{expires_at_human}</time>.</p>"
                        "<p>Please back up your data before then.</p>"
                    )

                    msg.attach(MIMEText(plain, "plain"))
                    msg.attach(MIMEText(html, "html"))

                    # send_email expects (recipient, message, mail_config)
                    send_email([username], msg, self.config)

                except (smtplib.SMTPRecipientsRefused, smtplib.SMTPNotSupportedError, UnicodeEncodeError) as e:
                    # nothing can be delivered to this address, e.g. because it
                    # is not a real e-mail address, so trying again is pointless
                    self.log.warning(f"Cannot send expiration e-mail to {username}: this address cannot be delivered to ({e}). Not trying again.")
                    user.set_value("expiry-email-sent", {**notice, "status": "failed"})

                except Exception as e:
                    # something else went wrong, e.g. the mail server is
                    # unreachable. That can be fixed later, so try again next
                    # time, but only mention it in the log the first time
                    if notice["status"] == "retrying":
                        self.log.debug(f"Could not send expiration e-mail to {username}: {e}")
                    else:
                        self.log.warning(f"Could not send expiration e-mail to {username}: {e}. Will try again later.")
                        user.set_value("expiry-email-sent", {**notice, "status": "retrying"})

                else:
                    user.set_value("expiry-email-sent", {**notice, "status": "sent"})

    def clear_expiry_notifications(self, username, commit=True):
        """
        Remove account deletion warnings for a user

        These warnings mention the date the account will be deleted, so when
        that date changes, or the deletion is called off, the warning needs to
        be removed. Warnings received from the 4CAT update server are left
        alone; those are managed elsewhere.

        :param str username:  User to remove deletion warnings for
        :param bool commit:  Commit the deletion? Set to `False` if a warning
        is added right after, so that both changes are made at once.
        """
        self.db.execute(
            "DELETE FROM users_notifications "
            "WHERE username = %s AND canonical_id = '' AND notification LIKE %s",
            (username, self.expiry_notification_prefix + "%"),
            commit=commit
        )

    def expire_notifications(self):
        """
        Delete expired notifications

        Pretty simple!
        """
        self.db.execute(
            f"DELETE FROM users_notifications WHERE timestamp_expires IS NOT NULL AND timestamp_expires < {time.time()}"
        )
