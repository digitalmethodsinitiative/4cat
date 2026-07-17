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

    def test_mandatory_text_missing_raises(self):
        """
        A mandatory option that was not submitted at all, and whose default
        does not fill it in, is not satisfied. This is how an API caller
        omitting a field arrives, and it matches what a mandatory date range
        or multi_option already does when absent.
        """
        options = {
            "query": {
                "type": UserInput.OPTION_TEXT,
                "help": "Search query",
                "mandatory": True,
            }
        }
        with pytest.raises(QueryParametersException):
            UserInput.parse_all(options, {})

    def test_mandatory_text_with_default_missing_input_raises(self):
        """
        A default is the form's starting value, not a stand-in for an answer.
        Defaults are no longer filled in for a strict caller, so an option that
        was not submitted has not been given - and a mandatory option that was
        not given fails, whether or not it has a default.
        """
        options = {
            "query": {
                "type": UserInput.OPTION_TEXT,
                "help": "Search query",
                "default": "default query",
                "mandatory": True,
            }
        }
        with pytest.raises(QueryParametersException):
            UserInput.parse_all(options, {})

    def test_missing_option_raises_unless_correcting_silently(self):
        """
        Our own form always submits every field it shows, so an option that is
        missing from the input altogether means an incomplete submission (e.g.
        an API call that left it out). Strict parsing refuses it, naming the
        option - quietly proceeding would let later checks pass on values the
        caller never sent. A caller that asked to be corrected quietly gets
        the default filled in instead.
        """
        options = {
            "query": {
                "type": UserInput.OPTION_TEXT,
                "help": "Search query",
                "default": "default query",
            }
        }

        assert UserInput.parse_all(options, {}, silently_correct=True) == {"query": "default query"}
        with pytest.raises(QueryParametersException) as raised:
            UserInput.parse_all(options, {})
        assert "Search query" in str(raised.value)

    def test_cleared_text_stays_cleared(self):
        """
        The form pre-fills the default into the field, so an empty submitted
        value means the user deliberately removed it. That is an answer
        ("nothing"), and it is stored as such - not quietly swapped back for
        the default the user just deleted. A tolerant caller still gets the
        default.
        """
        options = {
            "query": {
                "type": UserInput.OPTION_TEXT,
                "help": "Search query",
                "default": "default query",
            }
        }
        assert UserInput.parse_all(options, {"query": ""}) == {"query": ""}
        assert UserInput.parse_all(options, {"query": ""}, silently_correct=True) == {"query": "default query"}

    def test_cleared_number_field_raises(self):
        """
        There is no honest empty number: a user who clears a numeric field and
        submits is told to enter a number, rather than having the deleted
        default quietly restored.
        """
        options = {
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "help": "Number of items",
                "coerce_type": int,
                "min": 1,
                "default": 10,
            }
        }
        with pytest.raises(QueryParametersException) as raised:
            UserInput.parse_all(options, {"amount": ""})
        assert "Number of items" in str(raised.value)

        assert UserInput.parse_all(options, {"amount": ""}, silently_correct=True) == {"amount": 10}

    def test_unticking_an_optional_multi_means_none(self):
        """
        Unticking every option of a non-mandatory multi-select is a choice of
        nothing - the result is an empty selection, not the default the user
        just unticked.
        """
        options = {
            "boards": {
                "type": UserInput.OPTION_MULTI,
                "help": "Boards",
                "options": {"pol": "/pol/", "v": "/v/"},
                "default": ["pol"],
            }
        }
        # the form's empty marker on its own: nothing selected
        assert UserInput.parse_all(options, {"boards": ""}) == {"boards": []}
        assert UserInput.parse_all(options, {"boards": ""}, silently_correct=True) == {"boards": ["pol"]}

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

    def test_mandatory_multi_raises_when_nothing_selected(self):
        """
        When a user selects nothing in a multi-select, the form leaves the
        field out of the submission altogether rather than sending it empty -
        the same way an unchecked checkbox behaves. That absent shape, not an
        empty value, is what actually reaches us, so it is the one that has to
        be caught.
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
            UserInput.parse_all(options, {})

    def test_mandatory_multi_raises_when_default_is_unselected(self):
        """
        A user who unticks every option, including a selected default, has
        chosen nothing and should be told so rather than quietly handed the
        default back.

        A browser submits nothing at all for a select with no selection, which
        would be indistinguishable from the field never having been shown, so
        the form submits an empty value alongside it. That empty marker on its
        own is what "I unticked everything" looks like here.
        """
        options = {
            "boards": {
                "type": UserInput.OPTION_MULTI,
                "help": "Boards",
                "options": {"pol": "/pol/", "v": "/v/"},
                "default": ["pol"],
                "mandatory": True,
            }
        }
        with pytest.raises(QueryParametersException):
            UserInput.parse_all(options, {"boards": ""})

    def test_multi_discards_the_empty_marker(self):
        """
        The empty value the form submits alongside the selected ones is not a
        selection, and must not be mistaken for an invalid choice.
        """
        options = {
            "boards": {
                "type": UserInput.OPTION_MULTI,
                "help": "Boards",
                "options": {"pol": "/pol/", "v": "/v/"},
            }
        }
        parsed = UserInput.parse_all(options, {"boards": ["", "pol"]})
        assert parsed == {"boards": ["pol"]}

    def test_multi_still_rejects_an_invalid_choice_alongside_the_marker(self):
        """
        Discarding the marker must not become a way to smuggle bad values past
        validation.
        """
        options = {
            "boards": {
                "type": UserInput.OPTION_MULTI,
                "help": "Boards",
                "options": {"pol": "/pol/", "v": "/v/"},
            }
        }
        with pytest.raises(QueryParametersException):
            UserInput.parse_all(options, {"boards": ["", "nope"]})

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
