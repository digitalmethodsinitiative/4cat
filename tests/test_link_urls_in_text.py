import html
import random
import re

import pytest

from common.lib.helpers import link_urls_in_text, urls_in_text


"""
How `link_urls_in_text` turns the URLs in a text into links.

It makes the links in the CSV preview and in the image descriptions of
PixPlot, so the text comes from datasets and can contain anything. These tests
check that each URL links to exactly itself, that nothing in the text can act
as HTML, and the cases the earlier code got wrong: a URL that is the start of
another one, and URLs at the end of a line or next to quotation marks.
"""


def link(url, text=None):
    """The HTML for one link, as `link_urls_in_text` writes it"""
    return f'<a href="{html.escape(url)}" rel="external">{html.escape(text or url)}</a>'


# --- a URL that is the start of another one ------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("Profile https://x.com/someone and the post https://x.com/someone/status/123",
     "Profile " + link("https://x.com/someone") + " and the post " + link("https://x.com/someone/status/123")),
    ("The post https://x.com/someone/status/123 by https://x.com/someone",
     "The post " + link("https://x.com/someone/status/123") + " by " + link("https://x.com/someone")),
    ("https://en.wikipedia.org/wiki/Amsterdam,https://en.wikipedia.org/wiki/Amsterdam_Centraal",
     link("https://en.wikipedia.org/wiki/Amsterdam") + "," + link("https://en.wikipedia.org/wiki/Amsterdam_Centraal")),
    # an archived page has the URL of the original in it
    ("https://web.archive.org/web/2020/https://bbc.co.uk/news and https://bbc.co.uk/news",
     link("https://web.archive.org/web/2020/https://bbc.co.uk/news") + " and " + link("https://bbc.co.uk/news")),
])
def test_url_that_starts_another_url(text, expected):
    assert link_urls_in_text(text) == expected


def test_same_url_twice():
    assert link_urls_in_text("https://a.com/x and https://a.com/x") == link("https://a.com/x") + " and " + link("https://a.com/x")


# --- what is next to a URL is not part of it ------------------------------------

def test_url_at_end_of_line():
    """The earlier code turned line breaks into <br> first, and linked to https://example.com/end%3Cbr"""
    assert link_urls_in_text("line one https://example.com/end\nline two", line_breaks=True) == \
        "line one " + link("https://example.com/end") + "<br>\nline two"


def test_line_breaks_kept_as_they_are_by_default():
    assert link_urls_in_text("https://example.com/end\nline two") == link("https://example.com/end") + "\nline two"


def test_url_between_quotation_marks_and_angle_brackets():
    assert link_urls_in_text('He said "https://example.com/x" and <https://example.com/y>') == \
        "He said &quot;" + link("https://example.com/x") + "&quot; and &lt;" + link("https://example.com/y") + "&gt;"


def test_url_in_brackets():
    assert link_urls_in_text("(see https://en.wikipedia.org/wiki/Foo_(bar)) and https://example.com/x.") == \
        "(see " + link("https://en.wikipedia.org/wiki/Foo_(bar)") + ") and " + link("https://example.com/x") + "."


# --- the text can not act as HTML -----------------------------------------------

def test_html_in_the_text_is_shown_as_text():
    assert link_urls_in_text("<img src=x onerror=alert(1)> https://example.com/ok") == \
        "&lt;img src=x onerror=alert(1)&gt; " + link("https://example.com/ok")


@pytest.mark.parametrize("text", [
    "javascript://example.com/%0Aalert(1)",
    "JAVASCRIPT://x.com/",
    "ftp://example.com/file",
])
def test_only_web_addresses_become_links(text):
    assert link_urls_in_text(text) == text


def test_link_leads_to_the_url_exactly_as_written():
    """Characters that mean something in HTML are escaped in the link, so the browser reads the URL back unchanged"""
    result = link_urls_in_text("https://en.wikipedia.org/wiki/O'Brien and https://example.com/?a=1&b=2")
    assert result == link("https://en.wikipedia.org/wiki/O'Brien") + " and " + link("https://example.com/?a=1&b=2")
    assert 'href="https://en.wikipedia.org/wiki/O&#x27;Brien"' in result
    assert 'href="https://example.com/?a=1&amp;b=2"' in result


# --- the link text ----------------------------------------------------------------

def test_link_text_is_readable():
    assert link_urls_in_text("https://en.wikipedia.org/wiki/Tonin%C3%A1") == \
        link("https://en.wikipedia.org/wiki/Tonin%C3%A1", "https://en.wikipedia.org/wiki/Toniná")


def test_long_link_text_is_shortened():
    url = "https://www.example.com/a/very/long/path/to/some/page.html"
    result = link_urls_in_text(url, max_length=30)
    assert result.startswith(f'<a href="{url}" rel="external">https://www.example.com/')
    assert "[…]" in result
    assert result.endswith("some/page.html</a>")


def test_short_link_text_is_not_shortened():
    assert link_urls_in_text("https://example.com/x", max_length=30) == link("https://example.com/x")


@pytest.mark.parametrize("text, expected", [
    ("HTTPS://EXAMPLE.COM/Up", link("HTTPS://EXAMPLE.COM/Up")),
    ("no links here", "no links here"),
    ("", ""),
    (12345, "12345"),
])
def test_other_input(text, expected):
    assert link_urls_in_text(text) == expected


# --- random texts ------------------------------------------------------------------

def _random_texts(count):
    """Random texts with URLs, HTML and line breaks in them, some URLs the start of others"""
    pieces = ["https://x.com/someone", "https://x.com/someone/status/123", "https://en.wikipedia.org/wiki/O'Brien",
              "https://example.com/?a=1&b=2", "https://en.wikipedia.org/wiki/Tonin%C3%A1", "javascript://x.com/",
              "<b>", "</a>", '"', "'", "&", "&amp;", "\n", " ", ",", "(", ")", ".", "<script>alert(1)</script>",
              "%", "50% off", "美食", "#tag"]
    generator = random.Random(7)
    return ["".join(generator.choice(pieces) for _ in range(generator.randint(1, 10))) for _ in range(count)]


@pytest.mark.parametrize("text", _random_texts(500))
def test_random_text_gives_safe_html(text):
    result = link_urls_in_text(text, max_length=30, line_breaks=True)

    # apart from the links and line breaks it adds, there is no HTML in the result
    tags = re.compile(r'<a href="[^"<>]*" rel="external">|</a>|<br>')
    assert "<" not in tags.sub("", result) and ">" not in tags.sub("", result)
    assert result.count("<a ") == result.count("</a>")

    # each link leads to a URL that is in the text
    found = urls_in_text(text)
    for href in re.findall(r'<a href="([^"]*)"', result):
        assert html.unescape(href) in found
