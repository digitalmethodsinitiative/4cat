import pytest

from common.lib.helpers import urls_in_text


"""
What `urls_in_text` finds.

4CAT writes the URLs it finds into research datasets, so a URL that is cut
short or merged with the next one is wrong data that nobody notices. ural
1.6.0 and older got several of these cases wrong; 1.6.1 fixed them. These
tests keep checking them, next to the cases it always got right, so that a
new version of ural cannot quietly change the results.
"""


# --- "/@" followed by a name with a dot in it --------------------------------

@pytest.mark.parametrize("url", [
    "https://www.tiktok.com/@maria.bg2/video/7652635784733838614",
    "https://www.tiktok.com/@britt.sharing..fans/video/7652635784733838614",
    "https://www.youtube.com/@some.channel2/videos",
    "https://medium.com/@jane.doe1/my-post-abc123",
    "https://mastodon.social/@user.name2",
    "https://example.com/?ref=@name.surname2",
])
def test_name_after_at_sign_is_not_cut_short(url):
    """ural 1.6.0 and older stopped these URLs inside the name, e.g. at https://www.tiktok.com/@maria.bg"""
    assert urls_in_text(url) == [url]
    assert urls_in_text(f"Look at this: {url}!") == [url]


def test_at_sign_that_ural_already_handled():
    assert urls_in_text("https://www.tiktok.com/@maria.bg/video/1") == ["https://www.tiktok.com/@maria.bg/video/1"]
    assert urls_in_text("https://mastodon.social/@user@other.instance") == [
        "https://mastodon.social/@user@other.instance"]
    assert urls_in_text("https://user:pw@example.com/x") == ["https://user:pw@example.com/x"]


def test_email_addresses_are_not_urls():
    assert urls_in_text("mail me at jane.doe1@example.com please") == []


# --- URLs with a comma between them ------------------------------------------

def test_comma_without_space_separates_urls():
    """ural 1.6.0 and older returned these two as one URL"""
    assert urls_in_text("https://a.com/x,https://b.com/y") == ["https://a.com/x", "https://b.com/y"]
    assert urls_in_text("(https://a.com/x,https://b.com/y)") == ["https://a.com/x", "https://b.com/y"]


def test_comma_with_space_separates_urls():
    assert urls_in_text("https://a.com/x, https://b.com/y") == ["https://a.com/x", "https://b.com/y"]


def test_comma_inside_url_is_kept():
    assert urls_in_text("https://www.google.com/maps/@52.37,4.89,15z") == [
        "https://www.google.com/maps/@52.37,4.89,15z"]


def test_list_of_urls_with_commas_inside_them():
    """A column holding a comma-separated list of URLs, where the URLs themselves also contain commas"""
    assert urls_in_text("https://v.example.com/a.mp4?r=1,2&s=3,https://v.example.com/b.mp4?r=4,5") == [
        "https://v.example.com/a.mp4?r=1,2&s=3", "https://v.example.com/b.mp4?r=4,5"]


# --- URLs inside URLs ---------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://web.archive.org/web/20250000000000*/http://economist.com",
    "https://web.archive.org/web/20250101000000/https://www.economist.com/news",
    "https://web.archive.org/web/2025/https://www.tiktok.com/@maria.bg2/video/1",
    "https://archive.ph/2025.01.01-000000/https://www.example.com/page",
    "https://www.facebook.com/l.php?u=https://example.com/x&h=abc",
])
def test_url_inside_url_is_kept_whole(url):
    assert urls_in_text(url) == [url]
    assert urls_in_text(f"see {url} for more") == [url]
    assert urls_in_text(f"Archived ({url}).") == [url]


def test_url_inside_url_followed_by_another_url():
    assert urls_in_text("https://web.archive.org/web/2025/http://a.com/x,https://b.com/y") == [
        "https://web.archive.org/web/2025/http://a.com/x", "https://b.com/y"]


# --- what ural already does well ----------------------------------------------

def test_punctuation_after_url_is_left_out():
    assert urls_in_text("see https://x.com/a, it is great.") == ["https://x.com/a"]


def test_brackets_around_wikipedia_url():
    assert urls_in_text("(https://en.wikipedia.org/wiki/Foo_(bar))") == ["https://en.wikipedia.org/wiki/Foo_(bar)"]


def test_wikipedia_url_ending_in_bracket():
    """ural 1.6.0 and older left out the closing bracket"""
    assert urls_in_text("https://en.wikipedia.org/wiki/Foo_(bar)") == ["https://en.wikipedia.org/wiki/Foo_(bar)"]
    assert urls_in_text("see https://en.wikipedia.org/wiki/Foo_(bar) here") == ["https://en.wikipedia.org/wiki/Foo_(bar)"]


# --- the text of a URL is never changed ----------------------------------------

def test_encoded_at_sign_stays_encoded():
    text = "https://medium.com/%40jane.doe1/my-post and https://medium.com/@jane.doe1/my-post"
    assert urls_in_text(text) == ["https://medium.com/%40jane.doe1/my-post", "https://medium.com/@jane.doe1/my-post"]


def test_unusual_characters_in_text():
    """The helper swaps "@" for a rarely used character while searching; it must not mix up one already there"""
    assert urls_in_text(" https://www.tiktok.com/@maria.bg2/video/1?x=") == [
        "https://www.tiktok.com/@maria.bg2/video/1?x="]


def test_space_ends_url():
    """In ordinary text, a URL with a space in it cannot be told apart from a URL followed by more words"""
    assert urls_in_text("https://example.com/?q=a b") == ["https://example.com/?q=a"]
    assert urls_in_text("https://example.com/?q=a, b") == ["https://example.com/?q=a"]


# --- what is returned ----------------------------------------------------------

def test_urls_in_order_and_each_once():
    text = "first https://b.com/2\nthen https://a.com/1,https://b.com/2 and https://www.tiktok.com/@a.b2/video/9."
    assert urls_in_text(text) == ["https://b.com/2", "https://a.com/1", "https://www.tiktok.com/@a.b2/video/9"]


@pytest.mark.parametrize("text", ["", None, "no links here, sorry"])
def test_no_urls(text):
    assert urls_in_text(text) == []
