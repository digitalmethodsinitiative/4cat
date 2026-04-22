import sys
import types
import importlib.util
import pytest


@pytest.fixture(scope="module")
def ui_module():
    """Import `common/lib/user_input.py` in isolation with minimal stubs.

    This mirrors the standalone script but provides fixtures for pytest.
    """
    # stub exceptions module
    exc_mod = types.ModuleType("common.lib.exceptions")
    class QueryParametersException(Exception):
        pass
    exc_mod.QueryParametersException = QueryParametersException

    # register minimal module tree so imports inside user_input succeed
    sys.modules["common"] = types.ModuleType("common")
    sys.modules["common.lib"] = types.ModuleType("common.lib")
    sys.modules["common.lib.exceptions"] = exc_mod

    # stub dateutil.parser.parse
    sys.modules["dateutil"] = types.ModuleType("dateutil")
    dateutil_parser = types.ModuleType("dateutil.parser")
    dateutil_parser.parse = lambda s: None
    sys.modules["dateutil.parser"] = dateutil_parser

    # stub werkzeug.datastructures.ImmutableMultiDict
    wz = types.ModuleType("werkzeug")
    wz_ds = types.ModuleType("werkzeug.datastructures")
    class ImmutableMultiDict:
        pass
    wz_ds.ImmutableMultiDict = ImmutableMultiDict
    sys.modules["werkzeug"] = wz
    sys.modules["werkzeug.datastructures"] = wz_ds

    spec = importlib.util.spec_from_file_location(
        "user_input",
        "common/lib/user_input.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module.UserInput, module.RequirementsNotMetException


@pytest.mark.parametrize("req,other,expected", [
    ("c==red", {"c": "red"}, True),
    ("c==red", {"c": "blue"}, False),
    ("c=red", {"c": "red"}, True),
    ("c!=red", {"c": "blue"}, True),
    ("c!=red", {"c": "red"}, False),
    ("c^=hel", {"c": "hello"}, True),
    ("c^=hel", {"c": "world"}, False),
    ("c!^=hel", {"c": "world"}, True),
    ("c$=llo", {"c": "hello"}, True),
    ("c$=llo", {"c": "world"}, False),
    ("c~=ell", {"c": "hello"}, True),
    ("c~=xyz", {"c": "hello"}, False),
])
def test_requirement_single_cases(ui_module, req, other, expected):
    UserInput, _ = ui_module
    assert UserInput._requirement_met(req, other) is expected


def test_requirement_list_and_and_string_and_or(ui_module):
    UserInput, Req = ui_module

    # list / tuple → AND semantics
    settings = {"requires": ["c==red", "s==big"], "type": "string"}
    assert UserInput.parse_value(settings, "x", {"c": "red", "s": "big"}) == "x"
    with pytest.raises(Req):
        UserInput.parse_value(settings, "x", {"c": "red", "s": "small"})

    # && string → AND
    settings2 = {"requires": "c==red && s==big", "type": "string"}
    assert UserInput.parse_value(settings2, "x", {"c": "red", "s": "big"}) == "x"
    with pytest.raises(Req):
        UserInput.parse_value(settings2, "x", {"c": "blue", "s": "big"})

    # || string → OR
    settings3 = {"requires": "c==red || c==blue", "type": "string"}
    assert UserInput.parse_value(settings3, "x", {"c": "red"}) == "x"
    assert UserInput.parse_value(settings3, "x", {"c": "blue"}) == "x"
    with pytest.raises(Req):
        UserInput.parse_value(settings3, "x", {"c": "green"})
