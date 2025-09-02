import packaging.version
import requests
import json

from common.lib.helpers import add_notification, get_github_version, get_software_version
from backend.lib.worker import BasicWorker


class UpdateChecker(BasicWorker):
    """
    Check for updates

    Checks the configured Github repository (if any) for the latest packaged
    release. If the tag of that release is newer than the current version (per
    the .current-version file), a notification is shown to 4CAT admins in the
    web interface. Once the current version is updated the notification is
    automatically removed.
    """
    type = "check-for-updates"
    max_workers = 1

    @classmethod
    def ensure_job(cls, config=None):
        """
        Ensure that the update checker is always running

        This is used to ensure that the update checker is always running, and if
        it is not, it will be started by the WorkerManager.

        :return:  Job parameters for the worker
        """
        return {"remote_id": "", "interval": 10800}

    def work(self):
        self.get_remote_notifications()
        
        versionfile = self.config.get("PATH_CONFIG").joinpath(".current-version")
        repo_url = self.config.get("4cat.github_url")

        if not versionfile.exists() or not repo_url:
            # need something to compare against...
            return

        timeout = 15
        try:
            (latest_tag, release_url) = get_github_version(self.config.get("4cat.github_url"), timeout)
            if latest_tag == "unknown":
                raise ValueError()
        except ValueError:
            self.log.warning("'4cat.github_url' may be misconfigured - repository does not exist or is private")
            return
        except requests.Timeout:
            self.log.warning(f"GitHub URL '4cat.github_url' did not respond within {timeout} seconds - not checking for new version")
            return
        except (requests.RequestException, json.JSONDecodeError):
            # some issue with the data, or the GitHub API, but not something we
            # can fix from this end, so just silently fail
            return

        with versionfile.open() as infile:
            current_version = infile.readline().strip()

        if packaging.version.parse(latest_tag) > packaging.version.parse(current_version):
            # update available!
            # show a notification for all admins (normal users can't update
            # after all)
            add_notification(self.db, "!admin",
                             "A new version of 4CAT is [available](%s). The latest version is %s; you are running version %s." % (
                                 release_url, latest_tag, current_version
                             ), allow_dismiss=True)

        else:
            # up to date? dismiss any notifications about new versions
            # not if it has a canonical_id - then get_remote_notifications()
            # will deal with it
            self.db.execute("DELETE FROM users_notifications WHERE username = '!admin' "
                            "AND notification LIKE 'A new version of 4CAT%' AND canonical_id = ''")

    def get_remote_notifications(self):
        """
        Get notifications from notifications server

        For important upgrade patch notes, for example, it can be useful to
        have a more elaborate notification than just "a new version is
        available". This method retrieves such notifications from the
        configured "phone home" server and queues them for display to admins.
        """
        phonehome_url = self.config.get("4cat.phone_home_url")
        if not phonehome_url:
            return

        if phonehome_url.endswith("/"):
            phonehome_url = phonehome_url[:-1]

        current_version = get_software_version()[:16]
        phonehome_url += f"/get-notifications/?version={current_version}"

        try:
            notifications = requests.get(phonehome_url).json()
        except (requests.RequestException, json.JSONDecodeError) as e:
            self.log.warning(f"Cannot retrieve notifications from notifications server ({e})")
            return

        # add notifications that do not yet exist to the table and address them
        # to all 4CAT admins
        for canonical_id, notification in notifications.items():
            exists = self.db.fetchone("SELECT * FROM users_notifications WHERE canonical_id = %s", (canonical_id,))
            if exists:
                continue

            self.db.insert("users_notifications", {
                "canonical_id": canonical_id,
                "notification": notification["notification"],
                "notification_long": notification["notification_long"],
                "username": "!admin",
                "allow_dismiss": True
            })

        # if a notification has been dismissed and no longer exists on the
        # server, it can also be deleted locally (but not before that, else it
        # will be added back next time the server is queried)
        for dismissed in self.db.fetchall("SELECT * FROM users_notifications WHERE is_dismissed = TRUE"):
            if dismissed["canonical_id"] not in notifications:
                self.db.delete("users_notifications", {"id": dismissed["id"]}, commit=True)
