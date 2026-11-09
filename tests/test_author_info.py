import pytest

from backend.lib.search import Search
from common.lib.author_info import AuthorInfoReplacer


"""
Hiding the people behind collected items, and what that can and cannot reach.

4CAT offers two ways to hide an author: replace their details with a hash, so
two items from the same person can still be told apart from two items by
different people, or replace them with REDACTED, which drops that link too.

Both are offered in three places - while a dataset is being collected, while a
CSV file is uploaded, and afterwards through the 'Pseudonymise or anonymise'
processor. Those used to be separate pieces of code, and they drifted: the
collection side read the chosen mode from one parameter name for hashing and a
different, never-written one for redacting, so asking for REDACTED on an NDJSON
data source quietly did nothing at all while the interface said it had, and the
CSV upload looked only for names starting with a lower case 'author', leaving a
'username' or 'Author' column in the clear. All three now share
`AuthorInfoReplacer`, and these tests hold that shared behaviour in place.

What is deliberately not tested here, because it is not what this code does:

- Whether every personal detail is gone. Fields are chosen by name, so an
  author named inside the text of a post stays where it is. Choosing which
  names to look for is a data source's job, not this class's.
- Whether a hash can be traced back. That is a question about the salt, which
  the caller chooses.
"""


def hashed(value, salt=b"fixed-salt"):
    """The hash a given value gets, for a known salt."""
    return AuthorInfoReplacer(AuthorInfoReplacer.PSEUDONYMISE, salt=salt).replace(value)


# --- which fields get replaced -----------------------------------------------

def test_default_fields_cover_author_and_user():
    """With no field list given, the usual two name patterns are used."""
    replacer = AuthorInfoReplacer(AuthorInfoReplacer.ANONYMISE)
    row = {"author": "ada", "author_id": "1", "user_name": "ada", "body": "hello"}

    assert replacer.filter_row(row) == {
        "author": "REDACTED",
        "author_id": "REDACTED",
        "user_name": "REDACTED",
        "body": "hello",
    }


def test_fields_may_be_given_as_a_comma_separated_string():
    """The processor's form field is one string; a data source gives a list."""
    assert AuthorInfoReplacer.parse_fields("author*, sender") == ["author*", "sender"]
    assert AuthorInfoReplacer.parse_fields(["author*", "sender"]) == ["author*", "sender"]


def test_a_custom_field_list_replaces_the_default():
    """A platform that names its author field something else can say so."""
    replacer = AuthorInfoReplacer(AuthorInfoReplacer.ANONYMISE, fields=["sender*"])
    row = {"sender_name": "ada", "author": "ada"}

    assert replacer.filter_row(row) == {"sender_name": "REDACTED", "author": "ada"}


def test_names_are_matched_whatever_their_case():
    """
    Platforms name their fields however they like, and 4CAT runs on more than
    one operating system. Without this, a field called `Author` would be
    replaced on a Windows machine and left alone on a Linux server.
    """
    replacer = AuthorInfoReplacer(AuthorInfoReplacer.ANONYMISE)

    assert replacer.filter_row({"Author": "ada"})["Author"] == "REDACTED"
    assert replacer.filter_item({"User": {"name": "ada"}})["User"]["name"] == "REDACTED"


def test_patterns_are_matched_whatever_their_case():
    """A field list typed in the processor's form may be capitalised."""
    replacer = AuthorInfoReplacer(AuthorInfoReplacer.ANONYMISE, fields=["Author*", "SENDER"])

    assert replacer.filter_row({"author_id": "1", "sender": "ada"}) == {
        "author_id": "REDACTED",
        "sender": "REDACTED",
    }


def test_fields_that_do_not_match_are_left_alone():
    """Nothing outside the chosen names is touched, in either shape."""
    replacer = AuthorInfoReplacer(AuthorInfoReplacer.ANONYMISE, fields=["author*"])

    assert replacer.filter_row({"body": "hi", "timestamp": 1}) == {"body": "hi", "timestamp": 1}
    assert replacer.filter_item({"body": "hi", "sender": {"name": "ada"}}) == {
        "body": "hi",
        "sender": {"name": "ada"},
    }


# --- flat rows, as written to a CSV file -------------------------------------

def test_flat_row_is_redacted():
    replacer = AuthorInfoReplacer(AuthorInfoReplacer.ANONYMISE)

    assert replacer.filter_row({"author": "ada"})["author"] == "REDACTED"


def test_flat_row_is_hashed():
    """The value is replaced by something that is neither the original nor blank."""
    replacer = AuthorInfoReplacer(AuthorInfoReplacer.PSEUDONYMISE, salt=b"fixed-salt")
    result = replacer.filter_row({"author": "ada"})["author"]

    assert result not in ("ada", "", None)
    assert result == hashed("ada")


def test_the_same_name_gets_the_same_hash_within_one_run():
    """Two items by one person stay recognisable as one person."""
    replacer = AuthorInfoReplacer(AuthorInfoReplacer.PSEUDONYMISE)
    first = replacer.filter_row({"author": "ada"})["author"]
    second = replacer.filter_row({"author": "ada"})["author"]

    assert first == second
    assert first != replacer.filter_row({"author": "grace"})["author"]


# --- nested items, as written to an NDJSON file ------------------------------

def test_everything_under_a_matching_name_is_replaced():
    """A platform sends an author object; all of it goes, not just the top."""
    replacer = AuthorInfoReplacer(AuthorInfoReplacer.ANONYMISE)
    item = {"author": {"handle": "ada", "did": "did:plc:123"}, "text": "hello"}

    assert replacer.filter_item(item) == {
        "author": {"handle": "REDACTED", "did": "REDACTED"},
        "text": "hello",
    }


def test_matching_names_are_found_however_deeply_nested():
    replacer = AuthorInfoReplacer(AuthorInfoReplacer.ANONYMISE)
    item = {"post": {"embed": {"record": {"author": {"handle": "ada"}}}}}

    assert replacer.filter_item(item)["post"]["embed"]["record"]["author"]["handle"] == "REDACTED"


def test_values_in_a_matching_list_are_replaced():
    replacer = AuthorInfoReplacer(AuthorInfoReplacer.ANONYMISE)

    assert replacer.filter_item({"authors": ["ada", "grace"]}) == {"authors": ["REDACTED", "REDACTED"]}


def test_the_original_item_is_left_alone():
    """Callers get a copy back, so the item they passed in is unchanged."""
    replacer = AuthorInfoReplacer(AuthorInfoReplacer.ANONYMISE)
    item = {"author": "ada"}
    replacer.filter_item(item)

    assert item == {"author": "ada"}


def test_nested_and_flat_shapes_agree():
    """The same name and mode give the same replacement in either shape."""
    replacer = AuthorInfoReplacer(AuthorInfoReplacer.PSEUDONYMISE, salt=b"fixed-salt")

    assert replacer.filter_row({"author": "ada"})["author"] == replacer.filter_item({"author": "ada"})["author"]


# --- saying what was actually done -------------------------------------------

def test_a_report_says_what_was_asked_for_and_what_happened():
    replacer = AuthorInfoReplacer(AuthorInfoReplacer.ANONYMISE, fields=["author*"])
    replacer.filter_row({"author": "ada", "author_id": "1", "body": "hi"})

    assert replacer.report() == {"modes": ["anonymise"], "fields": ["author*"], "replaced": 2}


def test_a_mode_that_replaced_nothing_is_not_claimed():
    """A run that found none of its fields did nothing, so it claims nothing."""
    replacer = AuthorInfoReplacer(AuthorInfoReplacer.ANONYMISE, fields=["nowhere*"])
    replacer.filter_row({"author": "ada"})

    assert replacer.report()["modes"] == []
    assert replacer.report()["fields"] == ["nowhere*"]


# --- going over the same file more than once ---------------------------------

def test_a_second_run_adds_to_the_first():
    """Hashing some fields and removing others is two runs over one file."""
    first = AuthorInfoReplacer(AuthorInfoReplacer.ANONYMISE, fields=["author*"])
    first.filter_row({"author": "ada", "author_id": "1"})

    second = AuthorInfoReplacer(AuthorInfoReplacer.PSEUDONYMISE, fields=["user*"])
    second.filter_row({"user_name": "ada"})

    assert second.report(previous=first.report()) == {
        "modes": ["anonymise", "pseudonymise"],
        "fields": ["author*", "user*"],
        "replaced": 3,
    }


def test_a_later_run_that_matches_nothing_keeps_the_earlier_one():
    """
    Otherwise a harmless second run marks a hidden dataset as untouched.

    Overwriting the record would leave a count of zero, which the interface
    reads as "the fields were never found" - on a file that was in fact hidden.
    """
    first = AuthorInfoReplacer(AuthorInfoReplacer.ANONYMISE, fields=["author*"])
    first.filter_row({"author": "ada"})

    second = AuthorInfoReplacer(AuthorInfoReplacer.ANONYMISE, fields=["nowhere*"])
    second.filter_row({"author": "ada"})

    combined = second.report(previous=first.report())

    assert combined["replaced"] == 1
    assert combined["modes"] == ["anonymise"]


def test_replacements_are_counted_across_items():
    """The count covers a whole dataset, not one row."""
    replacer = AuthorInfoReplacer(AuthorInfoReplacer.ANONYMISE)
    replacer.filter_row({"author": "ada"})
    replacer.filter_row({"author": "grace"})

    assert replacer.report()["replaced"] == 2


def test_nested_replacements_are_counted_too():
    """Nested items go through the same counter as flat rows."""
    replacer = AuthorInfoReplacer(AuthorInfoReplacer.ANONYMISE)
    replacer.filter_item({"author": {"handle": "ada", "did": "did:plc:x"}})

    assert replacer.report()["replaced"] == 2


def test_a_count_of_zero_means_nothing_was_found():
    """
    What the interface needs to tell the two cases apart.

    A dataset whose author fields were never found looks exactly like one that
    was hidden properly, unless the count says otherwise.
    """
    replacer = AuthorInfoReplacer(AuthorInfoReplacer.ANONYMISE, fields=["author*"])
    replacer.filter_item({"_sender": {"username": "ada"}, "message": "hi"})

    assert replacer.report()["replaced"] == 0


def test_nothing_is_counted_before_anything_runs():
    assert AuthorInfoReplacer(AuthorInfoReplacer.ANONYMISE).report()["replaced"] == 0


# --- the salt ----------------------------------------------------------------

def test_a_fixed_salt_gives_the_same_hash_every_time():
    """Used when hashes should line up across datasets on one server."""
    assert hashed("ada") == hashed("ada")


def test_a_random_salt_gives_a_different_hash_each_time():
    """The default, so a name cannot be matched up between datasets."""
    first = AuthorInfoReplacer(AuthorInfoReplacer.PSEUDONYMISE).replace("ada")
    second = AuthorInfoReplacer(AuthorInfoReplacer.PSEUDONYMISE).replace("ada")

    assert first != second


def test_a_salt_may_be_text_or_bytes():
    """The server-wide salt is stored as text; a random one is bytes."""
    assert hashed("ada", salt="fixed-salt") == hashed("ada", salt=b"fixed-salt")


# --- modes -------------------------------------------------------------------

def test_an_unknown_mode_is_refused():
    """Better to stop than to quietly leave author details in place."""
    with pytest.raises(ValueError):
        AuthorInfoReplacer("redact")

    with pytest.raises(ValueError):
        AuthorInfoReplacer(None)


# --- what a collecting data source asks for ----------------------------------

class FakeSearch:
    """Just enough of a search worker to call the real method on."""
    get_author_filter = Search.get_author_filter

    def __init__(self, mode=None, pseudonymise_fields=None):
        self.parameters = {"pseudonymise": mode} if mode else {}
        if pseudonymise_fields is not None:
            self.pseudonymise_fields = pseudonymise_fields


@pytest.mark.parametrize("mode", [AuthorInfoReplacer.PSEUDONYMISE, AuthorInfoReplacer.ANONYMISE])
def test_both_modes_reach_the_data(mode):
    """
    Neither mode may be a silent no-op.

    Redacting used to fall through to nothing while collecting, because the mode
    was read from a parameter name that is never written.
    """
    author_filter = FakeSearch(mode).get_author_filter()

    assert author_filter is not None
    assert author_filter.filter_item({"author": "ada"})["author"] != "ada"


def test_no_filter_when_the_dataset_did_not_ask_for_one():
    assert FakeSearch().get_author_filter() is None
    assert FakeSearch("none").get_author_filter() is None


def test_a_data_source_may_name_its_own_fields():
    """Raw data keeps the platform's own names, which are not always 'author'."""
    author_filter = FakeSearch(AuthorInfoReplacer.ANONYMISE, pseudonymise_fields=["_sender*"]).get_author_filter()

    assert author_filter.filter_item({"_sender": {"name": "ada"}})["_sender"]["name"] == "REDACTED"


def test_data_sources_that_name_nothing_get_the_default():
    author_filter = FakeSearch(AuthorInfoReplacer.ANONYMISE).get_author_filter()

    assert author_filter.fields == list(AuthorInfoReplacer.DEFAULT_FIELDS)


def test_collecting_gives_every_dataset_its_own_salt():
    """Two datasets on one server cannot be lined up against each other."""
    first = FakeSearch(AuthorInfoReplacer.PSEUDONYMISE).get_author_filter()
    second = FakeSearch(AuthorInfoReplacer.PSEUDONYMISE).get_author_filter()

    assert first.replace("ada") != second.replace("ada")
