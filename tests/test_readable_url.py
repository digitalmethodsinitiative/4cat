import random
import re
from urllib.parse import quote

import pytest

from common.lib.helpers import URL_ENCODED_CHARACTERS, readable_url, urls_in_text


"""
What `readable_url` does to the URLs datasources give it.

The function makes URLs readable for the preview and the CSV export, without
changing the page they lead to. Its earlier version decoded everything and
encoded the query again, which turned "?q=%23tag" into "?q=#tag" (a search for
nothing, with "#tag" as a fragment), split values on encoded "&" and "=", wrote
repeated keys out as Python lists, and decoded "%252B" twice. These tests check
those cases, the URL shapes found in Zeeschuimer data, and URLs that arrive
partly encoded or not encoded at all.

Zeeschuimer has a JavaScript copy of this function; its tests use the same
cases.
"""


# --- readable text is decoded ------------------------------------------------

@pytest.mark.parametrize("url, expected", [
    ("https://www.douyin.com/search/%E7%BE%8E%E9%A3%9F?aid=1&type=general",
     "https://www.douyin.com/search/美食?aid=1&type=general"),
    ("https://www.instagram.com/explore/tags/caf%C3%A9/?hl=en",
     "https://www.instagram.com/explore/tags/café/?hl=en"),
    ("https://example.com/?q=%E5%BE%AE%E5%8D%9A%20%E7%83%AD%E6%90%9C",
     "https://example.com/?q=微博%20热搜"),
    ("https://x.com/search?q=%23%D9%85%D8%B1%D8%AD%D8%A8%D8%A7&src=typeahead_click",
     "https://x.com/search?q=%23مرحبا&src=typeahead_click"),
    ("https://example.com/?q=it%E2%80%94works%20%E2%9C%9D%EF%B8%8F%20%F0%9F%98%80",
     "https://example.com/?q=it—works%20✝\ufe0f%20😀"),
    ("https://example.com/#%E8%AF%9D%E9%A2%98", "https://example.com/#话题"),
    # lowercase escapes are decoded too
    ("https://example.com/?q=%e7%be%8e", "https://example.com/?q=美"),
])
def test_readable_text_is_decoded(url, expected):
    assert readable_url(url) == expected


# --- encoded ASCII stays as it is -----------------------------------------------

@pytest.mark.parametrize("url", [
    # a hashtag search: decoding %23 would make "#blessed" a fragment and the search empty
    "https://www.instagram.com/explore/search/keyword/?q=%23blessed",
    "https://x.com/search?q=%23hashtag%20lang%3Aen&src=typed_query&f=live",
    "https://www.tiktok.com/@someone/video/7567473806386760982?q=%23tag&t=1767714509282",
    # encoded & and = are part of a value, not separators
    "https://example.com/?q=%3D%26&r=%23",
    # + means a space in a query; %2B is a plus sign
    "https://example.com/search?q=a%2Bb",
    "https://example.com/search?q=a+b",
    # a URL that was encoded twice stays that way, as the site wrote it
    "https://example.com/search?q=a%252Bb",
    "https://example.com/search?q=%2520",
    "https://www.xiaohongshu.com/search_result?keyword=%25E5%2590%258C%25E4%25BA%25BAAI&source=web_explore_feed",
    "https://nl.pinterest.com/search/pins/?q=covers%20aesthetic&source_module_id=OB_covers%2520aesthetic"
    "&add_refine=Covers%7Cguide%7Cword%7C3",
    # an encoded / ? # % or space in the path is not a separator either
    "https://example.com/a%2Fb%3Fc/d%20e/100%25",
    # a URL in a parameter stays as it was: encoded, or not
    "https://weibo.com/newlogin?tabtype=weibo&gid=102803&openLoginLayer=0&url=https%3A%2F%2Fweibo.com%2F",
    "https://weibo.com/newlogin?tabtype=weibo&gid=102803&openLoginLayer=0&url=https://weibo.com/",
    "https://www.instagram.com/accounts/onetap/?next=%2F",
    # the page reads the fragment itself
    "https://example.com/#/route?tab=1%202",
    # letters and digits, which RFC 3987 would decode
    "https://example.com/?q=%41%31",
    # quotation marks would end the link in the preview
    "https://www.linkedin.com/search/results/content/?datePosted=%22past-month%22&keywords=ai%20coding&sid=j).&sortBy=%22relevance%22",
])
def test_encoded_ascii_stays_encoded(url):
    assert readable_url(url) == url


# --- nothing is reordered, merged or dropped ----------------------------------

@pytest.mark.parametrize("url", [
    "https://example.com/?a=1&b=2&a=3",
    "https://example.com/?a=1&b=2&a=3&a=",
    "https://example.com/?a=&b&=c&&d=",
    "https://example.com/?&&",
    "https://example.com/?",
    "https://example.com/?q=1#",
    "https://example.com/a;?q=1",
    "https://example.com/a;b/c;d?k=v;w=x",
    "HTTPS://Example.COM/Path?Q=1",
    "https://[::1]:8080/?q=1",
    "https://[fe80::1%25eth0]/?q=1",
    "https://user:pw@[2001:db8::1]:443/?q=1",
    "https://weibo.com/7786617255/RmncIsrT0?from=feed#comment",
    "view-source:https://www.tiktok.com/@someone",
    "mailto:someone@example.com?subject=hi",
    "http:path?q=1",
    "//example.com/?q=1",
    "/relative/path?q=1",
])
def test_structure_is_kept(url):
    assert readable_url(url) == url


# --- a whole URL that was saved encoded ----------------------------------------------

@pytest.mark.parametrize("url, expected", [
    ("https%3A%2F%2Fexample.com%2Fsearch%3Fq%3Dhello", "https://example.com/search?q=hello"),
    ("https%3A//example.com/search%3Fq%3Dhello", "https://example.com/search?q=hello"),
    ("HTTP%3a%2f%2fexample.com%2f", "HTTP://example.com/"),
    # encoded twice
    ("https%253A%252F%252Fexample.com%252Fsearch%253Fq%253Dhello", "https://example.com/search?q=hello"),
    # what was encoded inside the URL stays encoded: %2523 was %23, a "#" in the search term
    ("https%3A%2F%2Fx.com%2Fsearch%3Fq%3D%2523blessed%2520tag", "https://x.com/search?q=%23blessed%20tag"),
    # text outside ASCII is decoded as for any URL
    ("https%3A%2F%2Fwww.douyin.com%2Fsearch%2F%E7%BE%8E%E9%A3%9F", "https://www.douyin.com/search/美食"),
    ("https%3A%2F%2Fwww.douyin.com%2Fsearch%2F%25E7%25BE%258E%25E9%25A3%259F", "https://www.douyin.com/search/美食"),
])
def test_url_encoded_as_a_whole_is_decoded(url, expected):
    assert readable_url(url) == expected


@pytest.mark.parametrize("url", [
    "https://www.douyin.com/search/%E7%BE%8E%E9%A3%9F?aid=1&type=general",
    "https://x.com/search?q=%23hashtag%20lang%3Aen&src=typed_query&f=live",
    "https://weibo.com/newlogin?tabtype=weibo&gid=102803&openLoginLayer=0&url=https://weibo.com/",
    "https://www.xiaohongshu.com/search_result?keyword=%25E5%2590%258C%25E4%25BA%25BAAI&source=web_explore_feed",
    "https://example.com/搜索?q=微博 热搜&tag=#话题#",
    "https://example.com/?q=%E5%BE%AE%E5&r=%zz&s=100%",
    "https://example.com/a\\b?q=a%2Bb+c",
])
def test_url_encoded_as_a_whole_gives_the_same_result(url):
    """Encoding a whole URL once or twice before it is saved makes no difference to the result"""
    once = quote(url, safe="")
    twice = quote(once, safe="")
    assert readable_url(once) == readable_url(url)
    assert readable_url(twice) == readable_url(url)


# --- what a URL cannot contain is encoded ----------------------------------------

@pytest.mark.parametrize("url, expected", [
    ("https://example.com/search?q=hello world", "https://example.com/search?q=hello%20world"),
    ("https://example.com/搜索?q=微博 热搜&tag=#话题#", "https://example.com/搜索?q=微博%20热搜&tag=#话题#"),
    ("https://example.com/?q=1#frag ment?x=1", "https://example.com/?q=1#frag%20ment?x=1"),
    ('https://example.com/?a=say "hi"&b=<b>', "https://example.com/?a=say%20%22hi%22&b=%3Cb%3E"),
    ("https://example.com/{a|b}^`", "https://example.com/%7Ba%7Cb%7D%5E%60"),
    ("https://example.com/?a=\x01\x7f", "https://example.com/?a=%01%7F"),
    ("mailto:someone@example.com?subject=hi there", "mailto:someone@example.com?subject=hi%20there"),
    ("not a url", "not%20a%20url"),
])
def test_unsafe_characters_are_encoded(url, expected):
    assert readable_url(url) == expected


def test_backslash_is_left_alone():
    """Browsers read a backslash in the path as "/"; encoding it would lead elsewhere"""
    assert readable_url("https://example.com/a\\b?q=c\\d") == "https://example.com/a\\b?q=c\\d"


# --- invisible characters stay visible ---------------------------------------------

@pytest.mark.parametrize("url, expected", [
    # already encoded: zero-width space, no-break space, right-to-left override, BOM, ideographic space
    ("https://example.com/?a=%E2%80%8B&b=%C2%A0&c=%E2%80%AE&d=%EF%BB%BF&e=%E3%80%80",
     "https://example.com/?a=%E2%80%8B&b=%C2%A0&c=%E2%80%AE&d=%EF%BB%BF&e=%E3%80%80"),
    # not encoded
    ("https://example.com/?a=x\u200by&b=x\u00a0y&c=\u202eabc&d=\ufeff&e=x\u3000y",
     "https://example.com/?a=x%E2%80%8By&b=x%C2%A0y&c=%E2%80%AEabc&d=%EF%BB%BF&e=x%E3%80%80y"),
    # visible text next to an invisible character is still decoded
    ("https://example.com/?q=%E7%BE%8E%E2%80%8B%E9%A3%9F", "https://example.com/?q=美%E2%80%8B食"),
    # the replacement character means some other program could not read the text
    ("https://example.com/?q=%EF%BF%BD", "https://example.com/?q=%EF%BF%BD"),
])
def test_invisible_characters_stay_encoded(url, expected):
    assert readable_url(url) == expected


def test_emoji_joiners_and_selectors_are_shown():
    """Zero-width joiners and variation selectors are part of how emoji are written"""
    family = "%F0%9F%91%A8%E2%80%8D%F0%9F%91%A9%E2%80%8D%F0%9F%91%A7"
    assert readable_url(f"https://example.com/?q={family}") == "https://example.com/?q=👨\u200d👩\u200d👧"
    assert readable_url("https://example.com/?q=%E2%9D%A4%EF%B8%8F") == "https://example.com/?q=❤\ufe0f"


# --- what cannot be decoded is left as it is ----------------------------------------

@pytest.mark.parametrize("url", [
    # cut off in the middle of a character: the whole run stays encoded
    "https://example.com/?q=%E5%BE%AE%E5",
    "https://example.com/?q=%E5%BE%AE%E5%E5%8D%9A",
    # not valid UTF-8 at all
    "https://example.com/?q=%ED%A0%80&r=%F0%80%80&s=%C0%AF&t=%FF",
    # Chinese in an older encoding (GBK): decoding parts of it would show the wrong characters
    "https://example.com/?q=%C3%C0%CA%B3",
    # a % that does not start an escape
    "https://example.com/?q=%zz&r=%4&s=%%41&t=100%",
])
def test_undecodable_escapes_are_kept(url):
    assert readable_url(url) == url


# --- clean-up, empty and odd input ------------------------------------------------------

@pytest.mark.parametrize("url, expected", [
    ("  https://example.com/?q=1", "https://example.com/?q=1"),
    ("\thttps://exa\nmple.com/?q=1\r", "https://example.com/?q=1"),
    ("https://example.com/?q=a\tb", "https://example.com/?q=ab"),
    ("", ""),
    (None, ""),
    (12345, "12345"),
])
def test_clean_up_and_odd_input(url, expected):
    assert readable_url(url) == expected


def test_broken_half_character_does_not_fail():
    """Half of a two-part character, which only hand-made JSON can contain, passes through"""
    assert readable_url("https://example.com/?a=\ud800") == "https://example.com/?a=\ud800"


# --- links stay whole in the preview -------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://www.douyin.com/search/%E5%8D%95%E4%BA%B2%E5%A6%88%E5%A6%88?enter_from=live_detail&source=normal_search",
    "https://x.com/search?q=%23%D9%85%D8%B1%D8%AD%D8%A8%D8%A7&src=typeahead_click",
    "https://www.linkedin.com/search/results/content/?datePosted=%22past-month%22&keywords=ai%20coding&sid=j).&sortBy=%22relevance%22",
    "https://example.com/搜索?q=微博 热搜",
    "https://example.com/?q=%E7%BE%8E%E2%80%8B",
])
def test_result_is_one_whole_link(url):
    result = readable_url(url)
    assert urls_in_text(f"See {result} here.") == [result]


# --- running it again changes nothing ------------------------------------------------------

def _random_urls(count):
    """Random URLs built from pieces that tend to cause trouble"""
    pieces = list("abcXYZ019-._~:/?#[]@!$&'()*+,;=%\" <>\\^`{|}") + [
        "\t", "\n", "\x01", "\x7f", "\u00a0", "\u200b", "\u202e", "\u3000", "\ufeff", "\ufffd", "\U0001f600",
        "\U000e0001", "\ue000", "美", "é", "✝\ufe0f", "%E7%BE%8E", "%e7%be%8e", "%C3%A9", "%E2%80%8B", "%C2%A0",
        "%E2%80%AE", "%EF%BB%BF", "%EF%BF%BD", "%F0%9F%98%80", "%E5", "%BE", "%E5%BE", "%ED%A0%80", "%C0%AF",
        "%F4%90%80%80", "%C3%C0%CA%B3", "%25", "%2525", "%23", "%26", "%3D", "%2B", "%20", "%3A", "%2F", "%5C",
        "%41", "%7F", "%01", "%zz", "%4", "%",
    ]
    prefixes = ["https://example.com/", "https://example.com/p?q=", "https://example.com/?a=1#", "", "  https://x.com/",
                "https%3A%2F%2Fexample.com%2F", "https%253A%252F%252Fx.com%252F"]
    generator = random.Random(4)
    return [generator.choice(prefixes) + "".join(generator.choice(pieces) for _ in range(generator.randint(1, 12)))
            for _ in range(count)]


@pytest.mark.parametrize("url", _random_urls(2000))
def test_running_again_changes_nothing(url):
    result = readable_url(url)
    assert readable_url(result) == result

    # the result holds nothing that should have been encoded...
    assert not URL_ENCODED_CHARACTERS.search(result)

    # ...and every encoded ASCII character is still there, unless the whole URL was encoded
    if not re.match(r"https?%(25)*3A", url.strip(), re.IGNORECASE):
        ascii_escapes = re.compile(r"%[0-7][0-9A-Fa-f]")
        assert len(ascii_escapes.findall(result)) >= len(ascii_escapes.findall(url))
