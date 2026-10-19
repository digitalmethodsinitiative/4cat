import pytest

from common.lib.item_mapping import MappedItem, MissingMappedField, value_or_missing


"""
What `value_or_missing` is for, and what it deliberately leaves alone.

A mapped field is missing when the source data holds no value for it, so that
a researcher can tell "this post has none" apart from "we never collected
this". `value_or_missing` answers the one part of that question that has only
one possible answer, and leaves the rest to whoever maps a given platform.

It decides one thing: an absent key means the field is missing.

It deliberately does not decide:

- What a null means. That varies from field to field inside a single response,
  so the datasource has to say. Instagram's answer lives in
  `SearchInstagram.get_value_or_missing`, and the fields it does not hold for
  are handled where they are read.
- Whether a value that is present is true. Instagram reports a small, made-up
  like count on posts whose likes are hidden; only a separate field reveals it.
- Whether an empty value means anything is wrong. Zero, an empty string and
  false were sent by the source and are never missing.

Sample data will not catch mistakes here, because most fields are never empty
in practice: re-mapping every historical Instagram dataset produced identical
output before and after a fix to exactly this bug. Hence tests.
"""


def is_missing(value, default):
    return type(value) is MissingMappedField and value.value == default


# --- what the helper decides -------------------------------------------------

def test_absent_key_is_missing():
    """The whole of the helper's job: the source said nothing about this field."""
    assert is_missing(value_or_missing({}, "username", ""), "")


def test_default_is_carried_into_the_missing_field():
    """Processors that ignore missingness fall back on this, so it has to survive."""
    assert is_missing(value_or_missing({}, "num_likes", -1), -1)


@pytest.mark.parametrize("value", ["", 0, 0.0, False, [], {}])
def test_empty_values_the_source_sent_are_kept(value):
    """An empty value is not a missing one: the source told us it was empty."""
    result = value_or_missing({"field": value}, "field", "fallback")

    assert type(result) is not MissingMappedField
    assert result == value


@pytest.mark.parametrize("value", ["someone", 42, True, ["a"], {"a": 1}])
def test_ordinary_values_are_kept(value):
    assert value_or_missing({"field": value}, "field", "fallback") == value


# --- the limits: what the helper hands back for someone else to judge --------

def test_null_is_handed_back_undecided():
    """
    A null is not judged here. It can mean "not collected" for one field and
    "there is none" for the next, so the datasource decides per field.
    """
    result = value_or_missing({"location": None}, "location", "")

    assert type(result) is not MissingMappedField
    assert result is None


def test_a_present_value_is_kept_even_when_the_platform_is_lying():
    """
    Instagram sends a plausible small like count for posts whose likes are
    hidden. Nothing about the value itself gives that away, so the helper
    returns it and the mapper has to consult the platform's own flag.
    """
    hidden = {"like_count": 3, "like_and_view_counts_disabled": True}

    assert value_or_missing(hidden, "like_count", -1) == 3


def test_only_absent_fields_are_reported_as_missing():
    """
    The point of the distinction: a post with an empty caption and no likes
    should not be reported as a post whose caption and likes are unknown.
    """
    item = MappedItem({
        "body": value_or_missing({"caption": ""}, "caption", ""),
        "num_likes": value_or_missing({"like_count": 0}, "like_count", -1),
        "verified": value_or_missing({"is_verified": False}, "is_verified", False),
        "author_fullname": value_or_missing({}, "full_name", ""),
    })

    assert item.get_missing_fields() == ["author_fullname"]


# --- how one datasource answers the question the helper leaves open ----------

def instagram_post(**overrides):
    """A photo post with the least data the Instagram mapper needs."""
    post = {
        "code": "ABC123",
        "media_type": 1,
        "taken_at": 1700000000,
        "like_count": 71,
        "comment_count": 5,
        "user": {"pk": "9", "id": "9", "username": "someone"},
        "image_versions2": {"candidates": [{"url": "https://example.com/a.jpg", "width": 1080, "height": 1080}]},
    }
    post.update(overrides)
    return post


@pytest.fixture(scope="module")
def instagram():
    from datasources.instagram.search_instagram import SearchInstagram
    return SearchInstagram


def test_instagram_counts_a_null_as_missing(instagram):
    """For Instagram, a field left out and a field sent as null mean the same
    thing: the page the post came from does not carry that detail."""
    assert is_missing(instagram.get_value_or_missing({"username": None}, "username", ""), "")
    assert is_missing(instagram.get_value_or_missing({}, "username", ""), "")


def test_instagram_still_keeps_empty_values(instagram):
    """Deciding about nulls must not drag empty values along with it."""
    assert instagram.get_value_or_missing({"play_count": 0}, "play_count", -1) == 0


def test_instagram_marks_hidden_like_counts_missing(instagram):
    """
    The made-up count is not written into the dataset. -1 is the fallback
    because a count of 0 would read as a real number of likes.
    """
    mapped = instagram.map_item(instagram_post(like_count=3, like_and_view_counts_disabled=True))

    assert "num_likes" in mapped.get_missing_fields()
    assert mapped.get_item_data(safe=True)["num_likes"] == -1
    assert mapped.get_item_data(safe=True)["likes_hidden"] == "yes"


def test_instagram_keeps_a_visible_like_count(instagram):
    mapped = instagram.map_item(instagram_post())

    assert "num_likes" not in mapped.get_missing_fields()
    assert mapped.get_item_data(safe=True)["num_likes"] == 71


def test_instagram_reports_an_uncountable_comment_count_as_missing(instagram):
    post = instagram_post()
    del post["comment_count"]

    mapped = instagram.map_item(post)

    assert "num_comments" in mapped.get_missing_fields()
    assert mapped.get_item_data(safe=True)["num_comments"] == -1


def test_instagram_keeps_a_genuine_zero_comment_count(instagram):
    """Zero comments is a real measurement, not an absent one."""
    mapped = instagram.map_item(instagram_post(comment_count=0))

    assert "num_comments" not in mapped.get_missing_fields()
    assert mapped.get_item_data(safe=True)["num_comments"] == 0
