"""
Sorting settings the database holds but nothing declares.

Only `vanished` is ever a candidate for removal. Everything else is kept, either
because its extension might come back or because there is no evidence about it
at all.

"""

import pytest

from unittest.mock import MagicMock, patch


DAY = 86400
NOW = 1_700_000_000


@pytest.fixture
def installed_extensions():
    """
    Which extensions the audit should believe are installed

    Tests add to this; without it they would read whatever extensions happen to
    be installed on the machine running them.
    """
    return {}


@pytest.fixture
def config(installed_extensions):
    """
    A ConfigManager with a mock database
    """
    with patch("common.config_manager.Database"), \
         patch("common.lib.helpers.find_extensions", return_value=(installed_extensions, [])):
        from common.config_manager import ConfigManager

        manager = object.__new__(ConfigManager)
        manager.config_definition = {}
        manager.db = MagicMock()
        manager.logger = None
        manager.core_settings = {}
        manager.get = MagicMock(side_effect=lambda key, *args, **kwargs: {
            "4cat.declarations_last_clean_scan": NOW,
            "4cat.declarations_last_scan_complete": True,
        }.get(key))

        yield manager


def stored(name, value="null", tag="", declared_by=None, owner_kind=None, extension_id=None,
           last_seen=None, absent_since=None):
    return {"name": name, "tag": tag, "value": value, "declared_by": declared_by, "owner_kind": owner_kind,
            "extension_id": extension_id, "last_seen": last_seen, "absent_since": absent_since}


def run_audit(config, rows, scan_complete=True):
    """
    Run the audit over a hand-built settings/declarations join

    The clock is pinned so a setting's age is whatever the row says it is,
    rather than however long ago NOW happens to be when the suite runs.
    """
    config.get = MagicMock(side_effect=lambda key, *args, **kwargs: {
        "4cat.declarations_last_clean_scan": NOW,
        "4cat.declarations_last_scan_complete": scan_complete,
    }.get(key))
    config.db.fetchall.return_value = rows

    with patch("common.config_manager.time.time", return_value=NOW):
        audit = config.audit_settings()

    return {finding["name"]: finding for finding in audit["findings"]}, audit



def test_extension_installed_is_dormant(config, installed_extensions):
    """
    An installed extension's settings are not declared while it is switched off,
    but must survive so switching it back on restores its configuration.
    """
    installed_extensions["web_studies"] = {"name": "Web studies"}
    findings, _ = run_audit(config, [
        stored("selenium.browser", declared_by="x-search", owner_kind="extension",
               extension_id="web_studies", last_seen=NOW - 90 * DAY)
    ])

    assert findings["selenium.browser"]["state"] == "dormant"


def test_extension_not_installed_is_kept(config):
    """
    An uninstalled extension's settings are kept indefinitely, so re-installing
    restores the previous configuration rather than reverting to defaults.
    """
    findings, _ = run_audit(config, [
        stored("webjutter-search.password", declared_by="webjutter-search", owner_kind="extension",
               extension_id="webjutter", last_seen=NOW - 900 * DAY)
    ])

    assert findings["webjutter-search.password"]["state"] == "absent_extension"


def test_core_setting_absent_past_the_grace_period_has_vanished(config):
    """
    The one state that is ever offered for removal: last declared by core, and
    found missing longer ago than the grace period.
    """
    findings, _ = run_audit(config, [
        stored("4cat.removed_feature", declared_by="core:config_definition", owner_kind="core",
               last_seen=NOW - 90 * DAY, absent_since=NOW - 60 * DAY)
    ])

    assert findings["4cat.removed_feature"]["state"] == "vanished"


def test_uptime_before_a_setting_went_is_not_counted_against_it(config):
    """
    Age comes from absent_since - the first complete start-up that found the
    setting gone - and never from last_seen, which is only the last time 4CAT
    looked and found it.

    The gap between two start-ups is the operator's uptime. Measuring from
    last_seen would make a setting an upgrade removed look long gone the moment
    it went, so on a server up for months the grace period would buy nothing at
    exactly the point it is meant to.
    """
    findings, _ = run_audit(config, [
        # last declared three months ago, found missing moments ago
        stored("4cat.removed_feature", declared_by="core:config_definition", owner_kind="core",
               last_seen=NOW - 90 * DAY, absent_since=NOW - 60)
    ])

    assert findings["4cat.removed_feature"]["state"] == "recently_absent"


def test_setting_not_yet_recorded_absent_is_not_a_candidate(config):
    """
    No absence recorded means the last complete start-up still had this setting,
    so this process not knowing it is not evidence of anything.
    """
    findings, _ = run_audit(config, [
        stored("4cat.removed_feature", declared_by="core:config_definition", owner_kind="core",
               last_seen=NOW - 90 * DAY, absent_since=None)
    ])

    assert findings["4cat.removed_feature"]["state"] == "recently_absent"


def test_incomplete_boot_never_produces_a_candidate(config):
    """
    While a module fails to import its settings are unreachable, not removed, so
    a start-up that could not load everything must not promote anything to a
    candidate however old it looks.
    """
    findings, audit = run_audit(config, [
        stored("4cat.removed_feature", declared_by="core:config_definition", owner_kind="core",
               last_seen=NOW - 90 * DAY, absent_since=NOW - 60 * DAY)
    ], scan_complete=False)

    assert audit["scan_is_current"] is False
    assert findings["4cat.removed_feature"]["state"] == "recently_absent"


def test_setting_with_no_declaration_is_unknown(config):
    """
    Nothing was ever recorded declaring this, so there is no evidence either
    way and it is never a candidate.
    """
    findings, _ = run_audit(config, [stored("ancient.leftover")])

    assert findings["ancient.leftover"]["state"] == "unknown"


@pytest.mark.parametrize("state", ("dormant", "absent_extension", "recently_absent", "unknown"))
def test_archiving_refuses_every_state_but_vanished(config, state):
    """
    The guard sits in the model rather than the interface, so a request naming a
    setting directly cannot get past it.
    """
    config.audit_settings = MagicMock(return_value={
        "findings": [{"name": "some.setting", "state": state, "declared_by": "x"}]
    })

    with pytest.raises(ValueError):
        config.archive_setting("some.setting")

    config.db.delete.assert_not_called()


def test_archiving_a_setting_in_use_is_refused(config):
    """
    A setting that is still declared does not appear in the audit at all, which
    must be a refusal rather than an unguarded pass.
    """
    config.audit_settings = MagicMock(return_value={"findings": []})

    with pytest.raises(ValueError):
        config.archive_setting("4cat.name")

    config.db.delete.assert_not_called()


def test_restoring_over_a_live_value_is_refused(config):
    """
    Archiving is reversible because it moves rather than deletes. Restoring is
    not: it writes over whatever is stored now, and there is no second archive
    to undo that with. So it has to refuse when the setting is in use again.
    """
    config.clear_cache = MagicMock()
    config.db.fetchone.return_value = {"found": 1}  # archived, and stored again

    with pytest.raises(ValueError, match="write over"):
        config.restore_setting("gone.setting")

    config.db.fetchall.assert_not_called()


def test_restoring_takes_only_the_tag_it_was_asked_for(config):
    """
    The archive lists one row per tag, each with its own Restore button, so
    restoring has to take one and leave the others where they are.
    """
    config.clear_cache = MagicMock()
    config.db.fetchone.side_effect = [{"found": 1}, None]  # archived; not in use
    config.db.fetchall.return_value = [{"name": "gone.setting", "tag": "researchers"}]

    assert config.restore_setting("gone.setting", tag="researchers") == 1

    query, replacements = config.db.fetchall.call_args[0]
    assert "name = %s AND tag = %s" in query
    assert replacements == ("gone.setting", "researchers")


def test_restoring_without_a_tag_takes_every_tag(config):
    """
    No tag means the whole setting, which is what archive_setting() put there.
    """
    config.clear_cache = MagicMock()
    config.db.fetchone.side_effect = [{"found": 1}, None]
    config.db.fetchall.return_value = [{"name": "gone.setting", "tag": ""},
                                       {"name": "gone.setting", "tag": "researchers"}]

    assert config.restore_setting("gone.setting") == 2

    query, replacements = config.db.fetchall.call_args[0]
    assert "tag = %s" not in query
    assert replacements == ("gone.setting",)


def test_archiving_moves_every_tag_in_one_statement(config):
    """
    A setting can hold a value per tag as well as globally, and all of them have
    to move or it comes back partly configured.

    The move is one statement on purpose. The front-end shares a single database
    connection across its threads, so a delete and an insert issued separately
    can have another request commit or roll back between them - which for this
    pair means losing the archived copy and keeping the delete.
    """
    config.audit_settings = MagicMock(return_value={
        "findings": [{"name": "gone.setting", "state": "vanished", "declared_by": "core:config_definition"}]
    })
    config.clear_cache = MagicMock()
    config.uncache_setting = MagicMock()
    config.db.fetchall.return_value = [{"name": "gone.setting", "tag": ""},
                                       {"name": "gone.setting", "tag": "researchers"}]

    moved = config.archive_setting("gone.setting", archived_by="admin")

    assert moved == 2
    config.db.fetchall.assert_called_once()
    query = config.db.fetchall.call_args[0][0]
    assert "DELETE FROM settings" in query and "INSERT INTO settings_archive" in query, (
        f"the move must be a single statement, got: {query}"
    )
    # per name, so every tag goes; a per-(name, tag) delete would leave the rest
    assert "WHERE name = %s" in query.split("RETURNING")[0]
    # nothing may be issued separately, or there is a window to be torn in
    config.db.insert.assert_not_called()
    config.db.delete.assert_not_called()
    # stale values would otherwise be served from memcache, but only the tags
    # that moved need clearing - clear_cache() flushes the whole instance,
    # which 4CAT shares with the rate limiter
    config.uncache_setting.assert_called_once_with("gone.setting", ["", "researchers"])
    config.clear_cache.assert_not_called()
