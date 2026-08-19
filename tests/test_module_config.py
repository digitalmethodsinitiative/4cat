"""
Module-declared settings, their provenance, and the collision guard.

Modules declare settings in a `config` dict on the worker class, and core holds
the authoritative definition. A module declaring a name core already defines, or
a name in a namespace reserved for core, is refused rather than merged. Between
two modules the first declarer wins, and workers are visited in sorted order so
that outcome is reproducible. A definition inherited from a shared base class is
not a collision.

This matters because a definition controls a setting's `global` flag, which
collapses per-tag resolution; its `default`, which applies whenever no row
exists; and its `type`, which governs validation on save.

"""
import pickle

import pytest


@pytest.fixture
def collector():
    """
    A ModuleCollector with a hand-built worker set and no filesystem scan.

    Built with `object.__new__` so no modules are actually loaded. `workers` and
    `log_buffer` are class attributes on ModuleCollector; assigning them here
    makes instance attributes that shadow the class ones, so these tests cannot
    leak worker state into `test_modules.py` or each other.
    """
    from common.lib.module_loader import ModuleCollector

    instance = object.__new__(ModuleCollector)
    instance.workers = {}
    instance.log_buffer = ""
    instance.scan_failures = {}
    instance.missing_modules = {}

    return instance


def _worker(config, extension=None):
    """
    Build a stand-in worker class declaring the given config
    """
    return type("StandInWorker", (), {
        "config": config,
        "is_extension": extension is not None,
        "extension_name": extension
    })



def test_core_definition_wins_over_module(collector):
    """
    A module may not redefine a setting that core already declares.
    """
    collector.workers = {"rogue": _worker({"4cat.name": {"default": "pwned"}}, extension="rogue_ext")}
    module_config, provenance, collisions = collector.collect_module_config()

    assert "4cat.name" not in module_config
    assert "4cat.name" not in provenance
    assert [c["setting"] for c in collisions] == ["4cat.name"]


def test_reserved_namespace_refused(collector):
    """
    A module may not declare into a core namespace even if core has not used
    that exact name yet - otherwise an extension can squat a name 4CAT adds
    later and own its definition from then on.
    """
    collector.workers = {"rogue": _worker({"privileges.admin.not_yet_invented": {"default": True}}, extension="rogue_ext")}
    module_config, _, collisions = collector.collect_module_config()

    assert module_config == {}
    assert "reserved" in collisions[0]["reason"]


def test_forged_global_flag_never_reaches_definition(collector):
    """
    `global` is read from the definition, not the database. A module that got
    `{"global": True}` onto a core privilege would make `get()` skip tag
    resolution entirely and read only the global value, so every per-tag
    restriction on that setting would silently stop applying.
    """
    collector.workers = {
        "rogue": _worker({"privileges.can_run_processors": {"global": True, "default": True}}, extension="rogue_ext")
    }
    module_config, _, collisions = collector.collect_module_config()

    assert "privileges.can_run_processors" not in module_config, (
        "a module-declared 'global' flag on a core privilege would disable per-tag restrictions"
    )
    assert collisions


def test_inherited_config_is_not_a_collision(collector):
    """
    Several workers sharing a base class all report the *same* config object -
    a Selenium base declares its settings once for a dozen subclasses. That is
    inheritance, not a collision, and must not be refused or logged as one.
    """
    shared = {"selenium.browser": {"default": "firefox"}}

    class Base:
        config = shared
        is_extension = True
        extension_name = "web_studies"

    collector.workers = {
        "b-sub": type("B", (Base,), {}),
        "a-sub": type("A", (Base,), {}),
    }
    module_config, provenance, collisions = collector.collect_module_config()

    assert collisions == []
    assert module_config["selenium.browser"]["default"] == "firefox"
    assert provenance["selenium.browser"]["declared_by"] == "a-sub"
    assert provenance["selenium.browser"]["also_declared_by"] == ["b-sub"]


def test_unpicklable_definition_makes_the_boot_incomplete(collector, tmp_path):
    """
    A definition that cannot be pickled is dropped rather than taking the
    back-end down - core itself puts a lambda in one, so a module doing the same
    is plausible.

    But the setting is then missing from the definition while the module that
    declares it is loaded and still reading it, which is indistinguishable from
    the setting having been removed. So it has to register as a collection
    failure, or the scan counts as clean and the setting ages into `vanished`
    while it is very much in use.
    """
    collector.write_cache_file(tmp_path.joinpath("module_config.bin"),
                               {"ok.setting": {"default": 1}, "bad.setting": {"coerce_type": lambda x: x}},
                               drop_unpicklable=True)

    with tmp_path.joinpath("module_config.bin").open("rb") as infile:
        assert sorted(pickle.load(infile)) == ["ok.setting"]

    assert "bad.setting" in collector.scan_failures
    assert "bad.setting" in collector.collection_failures(), (
        "a dropped setting must make the boot count as incomplete"
    )


def test_sidecar_is_never_silently_pruned(collector, tmp_path):
    """
    Dropping a key to salvage the write is only ever right for the settings
    cache. Doing it to the provenance sidecar would discard the entire
    provenance map, so that has to fail loudly instead.
    """
    # pickle raises PicklingError for a module-level function and AttributeError
    # for a local one, which is why write_cache_file catches broadly
    with pytest.raises((pickle.PicklingError, AttributeError)):
        collector.write_cache_file(tmp_path.joinpath("module_config_provenance.bin"),
                                   {"format": 1, "provenance": {"a": lambda: 1}, "collisions": []})


def test_unknown_submenu_is_reported_but_not_refused(collector):
    """
    `submenu` only decides which heading a tab is listed under. Losing a working
    setting over a typo in an optional presentation key would be out of
    proportion, but silently ignoring it leaves the author with no signal.
    """
    collector.workers = {"w": _worker({"my_ext.setting": {"default": 1, "submenu": "proccesors"}})}
    module_config, _, collisions = collector.collect_module_config()

    assert "my_ext.setting" in module_config
    assert collisions == []
    assert "proccesors" in collector.log_buffer


def test_reads_legacy_cache_without_sidecar(tmp_path):
    """
    An instance upgraded from an older 4CAT has a module_config.bin but no
    provenance sidecar. That must load normally, with everything unattributed,
    rather than failing or discarding the definitions.
    """
    from common.config_manager import ConfigManager

    with tmp_path.joinpath("module_config.bin").open("wb") as outfile:
        pickle.dump({"legacy.setting": {"default": "kept"}}, outfile)

    config = object.__new__(ConfigManager)
    config.core_settings = {"PATH_CONFIG": tmp_path}
    config.config_definition = {}
    config.setting_provenance = {}
    config.setting_collisions = []
    config.logger = None

    config.load_user_settings()

    assert config.config_definition["legacy.setting"] == {"default": "kept"}
    assert config.setting_provenance == {}
