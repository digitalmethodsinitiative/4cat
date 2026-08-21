"""
Tests for the settings modules declare

A worker class may carry a `config` dict declaring settings. `ModuleCollector`
merges those into one mapping and caches it for the config manager to read.

What matters about a definition is that it decides how 4CAT treats the setting:
its `type` governs validation when a value is saved, its `default` applies
whenever nothing is stored, and its `global` flag decides whether values set per
user group apply at all. So which module gets to define a name is not cosmetic,
and these tests are mostly about that question.
"""
import pickle

import pytest

from unittest.mock import patch


@pytest.fixture
def collector():
    """
    A ModuleCollector that has not scanned anything

    Built without running __init__, which would load every module 4CAT has.
    The tests put workers into it by hand instead.
    """
    from common.lib.module_loader import ModuleCollector

    instance = object.__new__(ModuleCollector)
    instance.workers = {}
    instance.log_buffer = ""

    return instance


def _worker(config, extension=None):
    """
    Stand-in for a worker class that declares settings
    """
    return type("FakeWorker", (), {
        "config": config,
        "is_extension": bool(extension),
        "extension_name": extension
    })


def test_core_definition_wins_over_module(collector):
    """
    Core's definition of a setting is authoritative. A module redefining one
    could change its type, its default or its `global` flag, all of which change
    what happens to values an admin already saved.
    """
    collector.workers = {
        "greedy-worker": _worker({
            "4cat.name": {"type": "string", "default": "not 4CAT"},
            "greedy.setting": {"type": "string", "default": "fine"}
        })
    }

    module_config = collector.collect_module_config()

    assert "4cat.name" not in module_config, "a module must not be able to redefine a core setting"
    assert "greedy.setting" in module_config, "the module's other settings are unaffected"
    assert "already defined as a core 4CAT setting" in collector.log_buffer


def test_reserved_namespace_refused(collector):
    """
    A module may not declare into a name reserved for core even where core does
    not use that name yet: otherwise it could claim a name a later 4CAT version
    adds, and own its definition from then on.
    """
    collector.workers = {"squatter": _worker({"4cat.some_setting_4cat_does_not_have_yet": {"type": "string"}})}

    module_config = collector.collect_module_config()

    assert module_config == {}
    assert "reserved for core 4CAT settings" in collector.log_buffer


def test_first_module_wins_between_two_modules(collector):
    """
    Two modules declaring one name is an authoring mistake either way, so the
    rule only has to be predictable: the first declarer keeps it.
    """
    collector.workers = {
        "aaa-worker": _worker({"shared.setting": {"type": "string", "default": "first"}}),
        "zzz-worker": _worker({"shared.setting": {"type": "toggle", "default": "second"}})
    }

    module_config = collector.collect_module_config()

    assert module_config["shared.setting"]["default"] == "first"
    assert "already declared by aaa-worker" in collector.log_buffer


def test_extension_cannot_take_a_setting_a_core_module_declares(collector):
    """
    Only config_definition.py was ever safe from being redeclared. Between two
    modules the winner came down to whichever worker type sorted first, so an
    extension named early in the alphabet could take a setting an in-tree worker
    declares - along with its type and default.

    4CAT's own modules are visited before extensions now. The names below are
    picked so that a plain sort would get this wrong, which is what makes the
    test worth having.
    """
    collector.workers = {
        "zzz-core-worker": _worker({"shared.setting": {"type": "string", "default": "from core"}}),
        "aaa-extension-worker": _worker({"shared.setting": {"type": "toggle", "default": "from extension"}},
                                        extension="an_extension")
    }

    module_config = collector.collect_module_config()

    assert module_config["shared.setting"]["default"] == "from core"
    assert "already declared by zzz-core-worker" in collector.log_buffer


def test_inherited_definition_is_not_a_collision(collector):
    """
    Several classes sharing a base class that declares `config` is normal. They
    all report the same definition object, so the setting is registered once and
    nothing is refused.
    """
    shared = {"shared.setting": {"type": "string", "default": "once"}}
    collector.workers = {
        "worker-a": _worker(shared),
        "worker-b": _worker(shared)
    }

    module_config = collector.collect_module_config()

    assert module_config["shared.setting"] == {"type": "string", "default": "once"}
    assert collector.log_buffer == "", "inheriting a declaration is not a collision"


def test_definition_that_is_not_a_dictionary_is_refused(collector):
    """
    Everything that reads a definition expects a mapping. Catching it here is
    what lets the message name the module responsible - whatever touches it
    first does so long after the collector has finished.
    """
    collector.workers = {"sloppy-worker": _worker({"sloppy.setting": "a string, not a definition"})}

    module_config = collector.collect_module_config()

    assert module_config == {}
    assert "not a dictionary" in collector.log_buffer


def test_unpicklable_definition_is_dropped_rather_than_fatal(collector, tmp_path):
    """
    A definition can hold something pickle cannot write - core itself keeps a
    lambda in one, so a module doing the same is plausible. Losing the whole
    back-end at boot over one setting would be out of proportion, so that
    setting is dropped and reported, and the rest is still cached.
    """
    path = tmp_path.joinpath("module_config.bin")

    collector.write_cache_file(path, {
        "ok.setting": {"type": "string", "default": "kept"},
        "bad.setting": {"type": "string", "default": lambda: "cannot be pickled"}
    })

    with path.open("rb") as infile:
        assert sorted(pickle.load(infile)) == ["ok.setting"]

    assert "bad.setting" in collector.log_buffer
    assert "ok.setting" not in collector.log_buffer


def test_cache_is_written_through_a_temporary_file(collector, tmp_path):
    """
    The front-end reads this file while the back-end writes it, so it is written
    aside and moved into place. A reader sees the previous version or the new
    one, never half of either, and no temporary file is left behind.
    """
    path = tmp_path.joinpath("module_config.bin")

    collector.write_cache_file(path, {"some.setting": {"type": "string"}})

    assert sorted(item.name for item in tmp_path.iterdir()) == ["module_config.bin"]
    with path.open("rb") as infile:
        assert pickle.load(infile) == {"some.setting": {"type": "string"}}


def test_a_failed_write_leaves_the_previous_cache_in_place(collector, tmp_path):
    """
    If the move fails there is nothing useful to do about it, but a half-written
    temporary file must not be left lying next to the real one, and whatever was
    already cached has to survive untouched.
    """
    path = tmp_path.joinpath("module_config.bin")
    with path.open("wb") as outfile:
        pickle.dump({"previous.setting": {"type": "string"}}, outfile)

    with patch("common.lib.module_loader.os.replace", side_effect=OSError("no room on device")):
        with pytest.raises(OSError):
            collector.write_cache_file(path, {"new.setting": {"type": "string"}})

    assert sorted(item.name for item in tmp_path.iterdir()) == ["module_config.bin"]
    with path.open("rb") as infile:
        assert pickle.load(infile) == {"previous.setting": {"type": "string"}}
