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

    # this worker's notifications open with this, which is how it finds them
    # again. Note it must *not* set a canonical_id: 4CAT reserves a non-empty
    # canonical_id for notifications that come from the phone-home server, and
    # both common/lib/user.py (which hides rather than deletes those when
    # dismissed) and check_updates.py (which deletes dismissed ones the server
    # no longer lists) rely on that. Matching on the message text instead, as
    # check_updates.py does for its own version notices.
    NOTIFICATION_PREFIX = "Unused settings:"

    @classmethod
    def ensure_job(cls, config=None):
        # roughly daily, offset so it does not run alongside the update check
        return {"remote_id": "", "interval": 87000}

    def work(self):
        if not self.config.get("4cat.report_orphan_settings"):
            self.forget_report()
            return

        audit = self.config.audit_settings()
        removed = sorted(finding["name"] for finding in audit["findings"] if finding["state"] == "vanished")

        self.log.info(f"Settings audit: {len(audit['findings'])} undeclared setting(s), {len(removed)} of which "
                      f"nothing has declared for long enough to look removed.")

        if not removed:
            self.forget_report()
            return

        # keyed on the settings themselves, so re-running with the same result
        # says nothing rather than nagging an admin who has already looked and
        # decided to keep them.
        fingerprint = hashlib.sha256(",".join(removed).encode("utf-8")).hexdigest()[:12]

        # what was reported is remembered here rather than read back off the
        # notification, because dismissing a notification without a canonical id
        # deletes it (common/lib/user.py). Asking the table whether we already
        # spoke would therefore answer "no" the moment an admin says "yes, I
        # know", and the same notice would go out again the next day.
        if self.config.get("4cat.declarations_reported") == fingerprint:
            return

        # a different set than last time, so whatever was said before is out of
        # date whether or not it was dismissed
        self.clear_notifications()

        overridden = [finding["name"] for finding in audit["findings"]
                      if finding["state"] == "vanished" and finding["has_tag_override"]]

        message = (f"{self.NOTIFICATION_PREFIX} {len(removed)} setting(s) are stored but no longer declared by 4CAT "
                   f"or any installed extension. They are not in use and can be "
                   f"[reviewed and removed](/admin/settings/unused).")
        if overridden:
            message += (f" {len(overridden)} of them have a value set for a specific tag, so were configured "
                        f"deliberately at some point: {', '.join(sorted(overridden)[:5])}"
                        f"{' and others' if len(overridden) > 5 else ''}.")

        self.db.insert("users_notifications", {
            "username": "!admin",
            "notification": message,
            "allow_dismiss": True
        }, safe=True)

        self.config.set("4cat.declarations_reported", fingerprint)

    def forget_report(self):
        """
        Drop the notification and the record of having sent it

        Used when there is nothing to report, so that if the same set of
        settings turns up again later it is reported afresh rather than being
        silently suppressed by a fingerprint from before.
        """
        self.clear_notifications()
        self.config.set("4cat.declarations_reported", "")

    def clear_notifications(self):
        """
        Remove any notification this worker has left before

        Scoped to admin notifications with no canonical id that open with this
        worker's own phrase, so it cannot touch anything the phone-home server
        put there. Same approach as `check_updates.py` takes to its own version
        notices.
        """
        self.db.execute("DELETE FROM users_notifications WHERE username = '!admin' AND canonical_id = '' "
                        "AND notification LIKE %s", (self.NOTIFICATION_PREFIX + "%",))
