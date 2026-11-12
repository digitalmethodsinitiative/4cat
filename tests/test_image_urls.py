import pytest

from common.lib.helpers import holds_only_urls, looks_like_image_url, urls_in_text
from processors.visualisation.download_images import ImageDownloader


"""
Which URLs count as image links, for the image downloader and Top images.
"""


# --- looks_like_image_url -------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://site.com/img.jpg",
    "https://site.com/img.JPEG",
    "https://site.com/path/img.png?width=200",
    "https://preview.redd.it/3thfhsrsykb61.gif?format=mp4&s=afc1e4568789d2a0095bd1c91c5010860ff76834",
    "https://i.imgur.com/abc.gifv",
    "https://imgur.com/gallery/abc",
    "https://www.imgur.com/abc",
    "https://gfycat.com/SomeAnimal",
    "https://example.com/image?file=photo.jpg",
])
def test_image_links(url):
    assert looks_like_image_url(url)


@pytest.mark.parametrize("url", [
    "https://example.com/post/123",
    "https://www.youtube.com/watch?v=abc123",
    "https://jpg.example.com/page",
])
def test_not_image_links(url):
    assert not looks_like_image_url(url)


def test_image_link_without_extension_is_not_recognised():
    """Many image hosts leave out the extension; only a column holding nothing but URLs gets those through"""
    assert not looks_like_image_url("https://pbs.twimg.com/media/abc?format=jpg&name=large")


# --- holds_only_urls ---------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "https://a.com/x",
    "https://a.com/x, https://b.com/y",
    "https://a.com/x,https://b.com/y\nhttps://c.com/z",
    "(https://a.com/x).",
    "https://example.com/img, https://example.com/img2",
    "https://pbs.twimg.com/media/abc?x=y_",
])
def test_only_urls(text):
    assert holds_only_urls(text, urls_in_text(text))


@pytest.mark.parametrize("text", [
    "Look at https://a.com/x",
    "https://a.com/x 2",
    "no links here",
    "",
])
def test_not_only_urls(text):
    assert not holds_only_urls(text, urls_in_text(text))


# --- the image downloader: a column of URLs, or text ----------------------------

def test_column_with_only_a_url_uses_it_even_without_extension():
    url = "https://pbs.twimg.com/media/abc?format=jpg&name=large"
    assert ImageDownloader.find_image_urls(url) == {url}


@pytest.mark.parametrize("value", ["https://a.com/x.", "(https://a.com/x)", " https://a.com/x;\n"])
def test_punctuation_around_a_single_url_is_not_text(value):
    assert ImageDownloader.find_image_urls(value) == {"https://a.com/x"}


def test_trailing_underscore_cut_off_a_url_is_not_text():
    """ural leaves a trailing "_" out of the URL; what remains is not text"""
    assert ImageDownloader.find_image_urls("https://pbs.twimg.com/media/abc?x=y_") == {
        "https://pbs.twimg.com/media/abc?x=y"}


@pytest.mark.parametrize("separator", [", ", " "])
def test_list_where_one_url_starts_another(separator):
    urls = ["https://example.com/img", "https://example.com/img2"]
    assert ImageDownloader.find_image_urls(separator.join(urls)) == set(urls)


def test_list_without_extensions_is_not_treated_as_text():
    """Neither URL looks like an image, so this only passes if the value counts as a list of URLs"""
    urls = ["https://pbs.twimg.com/media/abc?format=jpg", "https://pbs.twimg.com/media/def?format=png"]
    assert ImageDownloader.find_image_urls(",".join(urls)) == set(urls)


@pytest.mark.parametrize("separator", [",", ", ", "\n"])
def test_column_with_a_list_of_urls_uses_all_of_them(separator):
    urls = ["https://pbs.twimg.com/media/abc?format=jpg", "https://b.com/c.png",
            "https://web.archive.org/web/2013/https://www.example.com/img"]
    assert ImageDownloader.find_image_urls(separator.join(urls)) == set(urls)


def test_urls_with_commas_in_a_list_stay_whole():
    value = "https://cdn.example.com/a.jpg?crop=1,2,3,https://cdn.example.com/b.jpg?crop=4,5"
    assert ImageDownloader.find_image_urls(value) == {
        "https://cdn.example.com/a.jpg?crop=1,2,3", "https://cdn.example.com/b.jpg?crop=4,5"}


def test_text_only_gives_image_links():
    value = "Look at https://site.com/img.jpg and my post https://example.com/post/123, nice (https://imgur.com/abc)."
    assert ImageDownloader.find_image_urls(value) == {"https://site.com/img.jpg", "https://imgur.com/abc"}


def test_text_without_urls_gives_nothing():
    assert ImageDownloader.find_image_urls("no links here, sorry") == set()
