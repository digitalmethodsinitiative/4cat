import packaging.version
import requests
import json

from common.lib.helpers import add_notification, get_github_version
from backend.lib.worker import BasicWorker
from pathlib import Path


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
        versionfile = Path(self.config.get("PATH_ROOT"), "config/.current-version")
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
            self.db.execute("DELETE FROM users_notifications WHERE username = '!admin' "
                            "AND notification LIKE 'A new version of 4CAT%'")
