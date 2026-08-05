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
        }.get(key))

        yield manager


def stored(name, value="null", tag="", declared_by=None, owner_kind=None, extension_id=None,
           last_seen=None, last_definition=None):
    return {"name": name, "tag": tag, "value": value, "declared_by": declared_by, "owner_kind": owner_kind,
            "extension_id": extension_id, "last_seen": last_seen, "last_definition": last_definition}


def run_audit(config, rows, latest_scan=NOW):
    """
    Run the audit over a hand-built settings/declarations join
    """
    config.db.fetchone.return_value = {"seen": latest_scan}
    config.db.fetchall.return_value = rows

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


def test_core_setting_unseen_across_clean_scans_has_vanished(config):
    """
    The one state that is ever offered for removal: last declared by core, and
    absent for longer than the grace period of complete scans.
    """
    findings, _ = run_audit(config, [
        stored("4cat.removed_feature", declared_by="core:config_definition", owner_kind="core",
               last_seen=NOW - 60 * DAY)
    ])

    assert findings["4cat.removed_feature"]["state"] == "vanished"


def test_incomplete_boot_never_produces_a_candidate(config):
    """
    While a module fails to import its settings are unreachable, not removed. A
    boot that could not see everything must not promote anything to a candidate,
    however old it looks - last_seen advances on every boot, the clean-scan
    marker only on complete ones, so the two differing means the last boot was
    incomplete.
    """
    findings, audit = run_audit(config, [
        stored("4cat.removed_feature", declared_by="core:config_definition", owner_kind="core",
               last_seen=NOW - 60 * DAY)
    ], latest_scan=NOW + DAY)

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


def test_archiving_moves_every_tag_not_just_the_global_one(config):
    """
    A setting can hold a value per tag as well as globally. Archiving has to take
    all of them, or the setting is half-removed and comes back partly configured.
    """
    config.audit_settings = MagicMock(return_value={
        "findings": [{"name": "gone.setting", "state": "vanished", "declared_by": "core:config_definition"}]
    })
    config.clear_cache = MagicMock()
    config.db.fetchall.return_value = [
        {"name": "gone.setting", "value": '"a"', "tag": ""},
        {"name": "gone.setting", "value": '"b"', "tag": "researchers"},
    ]

    moved = config.archive_setting("gone.setting", archived_by="admin")

    assert moved == 2
    assert config.db.insert.call_count == 2
    # by name, so every tag goes; deleting per (name, tag) would leave the rest
    config.db.delete.assert_called_once_with("settings", where={"name": "gone.setting"}, commit=False)
    # stale values would otherwise be served from memcache under any tag
    config.clear_cache.assert_called_once()
