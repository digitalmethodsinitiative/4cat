"""
Report settings the database holds that nothing declares
"""
import hashlib

from backend.lib.worker import BasicWorker


class SettingsAuditor(BasicWorker):
    """
    Look for settings nothing declares any more

    4CAT keeps a setting's stored value when whatever declared it goes away,
    because there is usually no way to tell a setting that was removed from one
    whose extension is merely uninstalled or disabled. Over time that leaves
    values behind for settings that no longer exist.

    This worker tells admins about the ones that look genuinely removed, and
    removes nothing itself. A notification is its only output, so it does
    nothing at all unless `4cat.report_orphan_settings` is on - on a server that
    is not being developed against there is nothing to act on.
    """
    type = "audit-settings"
    max_workers = 1

    # notifications are keyed by which settings they are about, so an admin who
    # dismisses one is not told about the same settings again, but does hear
    # about it if a different set turns up later
    NOTIFICATION_PREFIX = "settings-audit-"

    @classmethod
    def ensure_job(cls, config=None):
        # roughly daily, offset so it does not run alongside the update check
        return {"remote_id": "", "interval": 87000}

    def work(self):
        if not self.config.get("4cat.report_orphan_settings"):
            self.clear_notifications()
            return

        audit = self.config.audit_settings()
        removed = sorted(finding["name"] for finding in audit["findings"] if finding["state"] == "vanished")

        self.log.info(f"Settings audit: {len(audit['findings'])} undeclared setting(s), {len(removed)} of which "
                      f"nothing has declared for long enough to look removed.")

        if not removed:
            self.clear_notifications()
            return

        # keyed on the settings themselves, so re-running with the same result
        # finds the existing notification and leaves it alone. Replacing it
        # would clear the dismissed flag and start nagging an admin who has
        # already looked and decided to keep them.
        fingerprint = hashlib.sha256(",".join(removed).encode("utf-8")).hexdigest()[:12]
        canonical_id = self.NOTIFICATION_PREFIX + fingerprint

        if self.db.fetchone("SELECT id FROM users_notifications WHERE canonical_id = %s", (canonical_id,)):
            return

        # a different set than last time, so whatever was said before is out of
        # date whether or not it was dismissed
        self.clear_notifications()

        overridden = [finding["name"] for finding in audit["findings"]
                      if finding["state"] == "vanished" and finding["has_tag_override"]]

        message = (f"{len(removed)} setting(s) are stored but no longer declared by 4CAT or any installed extension. "
                   f"They are not in use and can be removed from the settings panel.")
        if overridden:
            message += (f" {len(overridden)} of them have a value set for a specific tag, so were configured "
                        f"deliberately at some point: {', '.join(sorted(overridden)[:5])}"
                        f"{' and others' if len(overridden) > 5 else ''}.")

        self.db.insert("users_notifications", {
            "canonical_id": canonical_id,
            "username": "!admin",
            "notification": message,
            "allow_dismiss": True
        }, safe=True)

    def clear_notifications(self):
        """
        Remove any notification this worker has left before

        Matched on the canonical id, which this worker owns, rather than on the
        text of the message.
        """
        self.db.execute("DELETE FROM users_notifications WHERE canonical_id LIKE %s",
                        (self.NOTIFICATION_PREFIX + "%",))
