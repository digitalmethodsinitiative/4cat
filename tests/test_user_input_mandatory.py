"""
Tests for the UserInput.mandatory option setting.

This validates that options marked as mandatory raise QueryParametersException
when the user submits an empty value, while still allowing absent/null defaults
and non-empty values.
"""

import pytest

from common.lib.user_input import UserInput
from common.lib.exceptions import QueryParametersException


class TestMandatoryOption:
    """
    Test the mandatory option key for a variety of input types.
    """

    def test_mandatory_text_raises_when_empty(self):
        """
        A mandatory string option with an empty submitted value should raise.
        """
        options = {
            "query": {
                "type": UserInput.OPTION_TEXT,
                "help": "Search query",
                "mandatory": True,
            }
        }
        with pytest.raises(QueryParametersException):
            UserInput.parse_all(options, {"query": ""})

    def test_mandatory_text_raises_when_whitespace_only(self):
        """
        Whitespace-only input should be treated as empty for mandatory fields.
        """
        options = {
            "query": {
                "type": UserInput.OPTION_TEXT,
                "help": "Search query",
                "mandatory": True,
            }
        }
        with pytest.raises(QueryParametersException):
            UserInput.parse_all(options, {"query": "   "})

    def test_mandatory_text_accepts_value(self):
        """
        A mandatory text option with a non-empty value should parse normally.
        """
        options = {
            "query": {
                "type": UserInput.OPTION_TEXT,
                "help": "Search query",
                "mandatory": True,
            }
        }
        parsed = UserInput.parse_all(options, {"query": "hello"})
        assert parsed == {"query": "hello"}

    def test_mandatory_text_missing_default_does_not_raise(self):
        """
        If the option was never submitted and has no default, mandatory should
        not raise.
        """
        options = {
            "query": {
                "type": UserInput.OPTION_TEXT,
                "help": "Search query",
                "mandatory": True,
            }
        }
        parsed = UserInput.parse_all(options, {})
        assert parsed == {"query": None}

    def test_mandatory_text_with_default_missing_input_does_not_raise(self):
        """
        If the option was not submitted but has a default, the default is used.
        """
        options = {
            "query": {
                "type": UserInput.OPTION_TEXT,
                "help": "Search query",
                "default": "default query",
                "mandatory": True,
            }
        }
        parsed = UserInput.parse_all(options, {})
        assert parsed == {"query": "default query"}

    def test_non_mandatory_text_empty_is_allowed(self):
        """
        Without mandatory=True, an empty value should fall back to the default.
        """
        options = {
            "query": {
                "type": UserInput.OPTION_TEXT,
                "help": "Search query",
                "default": "default query",
            }
        }
        parsed = UserInput.parse_all(options, {"query": ""})
        assert parsed == {"query": "default query"}

    def test_mandatory_multi_raises_when_empty(self):
        """
        A mandatory multi-select with no selected values should raise.
        """
        options = {
            "boards": {
                "type": UserInput.OPTION_MULTI,
                "help": "Boards",
                "options": {"pol": "/pol/", "v": "/v/"},
                "mandatory": True,
            }
        }
        with pytest.raises(QueryParametersException):
            UserInput.parse_all(options, {"boards": ""})

    def test_mandatory_multi_accepts_value(self):
        """
        A mandatory multi-select with at least one selected value should parse.
        """
        options = {
            "boards": {
                "type": UserInput.OPTION_MULTI,
                "help": "Boards",
                "options": {"pol": "/pol/", "v": "/v/"},
                "mandatory": True,
            }
        }
        parsed = UserInput.parse_all(options, {"boards": "pol"})
        assert parsed == {"boards": ["pol"]}

    def test_mandatory_daterange_raises_when_both_empty(self):
        """
        A mandatory date range with neither bound provided should raise.
        """
        options = {
            "daterange": {
                "type": UserInput.OPTION_DATERANGE,
                "help": "Date range",
                "mandatory": True,
            }
        }
        with pytest.raises(QueryParametersException):
            UserInput.parse_all(options, {
                "daterange-min": "",
                "daterange-max": "",
            })

    def test_mandatory_daterange_accepts_partial_range(self):
        """
        A mandatory date range with only one bound should parse that bound.
        """
        options = {
            "daterange": {
                "type": UserInput.OPTION_DATERANGE,
                "help": "Date range",
                "mandatory": True,
            }
        }
        parsed = UserInput.parse_all(options, {
            "daterange-min": "2024-01-01",
            "daterange-max": "",
        })
        assert parsed["daterange"][0] is not None
        assert parsed["daterange"][1] is None

    def test_mandatory_multi_option_raises_when_empty(self):
        """
        A mandatory multi_option with no submitted sub-items should raise.
        """
        options = {
            "filters": {
                "type": UserInput.OPTION_MULTI_OPTION,
                "help": "Filters",
                "mandatory": True,
                "options": {
                    "column": {
                        "type": UserInput.OPTION_TEXT,
                        "default": "",
                        "help": "Column",
                    }
                }
            }
        }
        with pytest.raises(QueryParametersException):
            UserInput.parse_all(options, {})

    def test_mandatory_multi_option_accepts_item(self):
        """
        A mandatory multi_option with at least one submitted item should parse.
        """
        options = {
            "filters": {
                "type": UserInput.OPTION_MULTI_OPTION,
                "help": "Filters",
                "mandatory": True,
                "options": {
                    "column": {
                        "type": UserInput.OPTION_TEXT,
                        "default": "",
                        "help": "Column",
                    }
                }
            }
        }
        parsed = UserInput.parse_all(options, {"filters-1-column": "body"})
        assert len(parsed["filters"]) == 1
        assert parsed["filters"][0]["column"] == "body"
