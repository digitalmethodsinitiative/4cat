from unittest.mock import MagicMock

import pytest
import requests

from processors.networks import wikipedia_network
from processors.networks.wikipedia_network import WikiURLCoLinker


"""
Which Wikipedia page a link leads to, for the Wikipedia category network.

The network has one node per page, named after its title, and fetches each
page's categories by that title. Links write titles in different ways: with
underscores for spaces, with characters such as & and + encoded or not. All
spellings of one page must give the same title, and that title must be the
real one, or Wikipedia returns the wrong page or none.
"""


@pytest.mark.parametrize("url, title", [
    ("https://en.wikipedia.org/wiki/Amsterdam", "Amsterdam"),
    ("https://en.wikipedia.org/wiki/Amsterdam_Centraal", "Amsterdam Centraal"),
    # characters that end a title or mean something else when the title is put in a URL as it is
    ("https://en.wikipedia.org/wiki/AT%26T", "AT&T"),
    ("https://en.wikipedia.org/wiki/AT&T", "AT&T"),
    ("https://en.wikipedia.org/wiki/C%2B%2B", "C++"),
    ("https://en.wikipedia.org/wiki/O'Brien", "O'Brien"),
    ("https://en.wikipedia.org/wiki/O%27Brien", "O'Brien"),
    ("https://en.wikipedia.org/wiki/Washington,_D.C.", "Washington, D.C."),
    ("https://en.wikipedia.org/wiki/Washington%2C_D.C.", "Washington, D.C."),
    ("https://en.wikipedia.org/wiki/AC/DC", "AC/DC"),
    ("https://en.wikipedia.org/wiki/What%3F", "What?"),
    # text in other alphabets or with accents, encoded or not
    ("https://en.wikipedia.org/wiki/Caf%C3%A9", "Café"),
    ("https://en.wikipedia.org/wiki/Café", "Café"),
    # titles always start with a capital letter
    ("https://en.wikipedia.org/wiki/amsterdam", "Amsterdam"),
    ("https://en.wikipedia.org/wiki/c%2B%2B", "C++"),
    # Markdown (as in Reddit posts) puts a backslash before underscores in the visible copy of a link
    (r"https://en.wikipedia.org/wiki/Judah\_P.\_Benjamin", "Judah P. Benjamin"),
    # a link to a part of the page, or with extra parameters, leads to the page itself
    ("https://en.wikipedia.org/wiki/Amsterdam#History", "Amsterdam"),
    ("https://en.m.wikipedia.org/wiki/Amsterdam?useskin=vector", "Amsterdam"),
])
def test_title_from_url(url, title):
    assert WikiURLCoLinker.title_from_url(url) == title


def test_link_without_title():
    assert WikiURLCoLinker.title_from_url("https://en.wikipedia.org/wiki/") == ""


# --- how a run ends when Wikipedia does not answer as expected -------------------

class FakeSource:
    """A dataset with one post per text"""
    def __init__(self, bodies):
        self.rows = [{"id": str(i), "thread_id": str(i), "body": body, "url": ""} for i, body in enumerate(bodies)]
        self.num_rows = len(self.rows)

    def iterate_items(self, processor=None, **kwargs):
        yield from (dict(row) for row in self.rows)


class FakeResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")


def page_with_categories(*categories):
    """What Wikipedia shows when asked for the source of a page"""
    source = " ".join(f"[[Category:{category}]]" for category in categories)
    return FakeResponse(200, f'<html><body><textarea id="wpTextbox1">Text {source}</textarea></body></html>')


def run(bodies, answers, monkeypatch, tmp_path):
    """
    Run the processor on posts, with Wikipedia giving the answers in `answers` (by title)

    :return:  The dataset, a mock, to see how the run ended; and the titles that were asked for
    """
    asked = []

    def fake_get(url, params=None, **kwargs):
        asked.append(params["title"])
        answer = answers[params["title"]]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(wikipedia_network.requests, "get", fake_get)
    processor = WikiURLCoLinker.__new__(WikiURLCoLinker)
    processor.source_dataset = FakeSource(bodies)
    processor.dataset = MagicMock()
    processor.dataset.get_results_path.return_value = tmp_path / "network.gexf"
    processor.parameters = {}
    processor.interrupted = False
    processor.process()
    return processor.dataset, asked


def logged(dataset):
    return "\n".join(call.args[0] for call in dataset.log.call_args_list)


AMSTERDAM = "https://en.wikipedia.org/wiki/Amsterdam"
UTRECHT = "https://en.wikipedia.org/wiki/Utrecht"
ROTTERDAM = "https://en.wikipedia.org/wiki/Rotterdam"


def test_all_pages_fetched(monkeypatch, tmp_path):
    dataset, asked = run([f"{AMSTERDAM} and {UTRECHT}"], {
        "Amsterdam": page_with_categories("Capitals in Europe"),
        "Utrecht": page_with_categories("Cities in the Netherlands"),
    }, monkeypatch, tmp_path)

    dataset.finish.assert_called_once_with(4)
    dataset.finish_with_warning.assert_not_called()
    dataset.finish_with_error.assert_not_called()
    assert "Got the categories of 2 of 2 pages" in logged(dataset)


def test_wikipedia_refuses(monkeypatch, tmp_path):
    """The old version made a network without categories and finished as if nothing was wrong"""
    refusal = FakeResponse(403, "Please set a user-agent and respect our robot policy https://w.wiki/4wJS.")
    dataset, asked = run([f"{AMSTERDAM} and {UTRECHT}"], {"Amsterdam": refusal, "Utrecht": refusal},
                         monkeypatch, tmp_path)

    # it stops asking after the first refusal, and fails with Wikipedia's own explanation
    assert asked == ["Amsterdam"]
    message = dataset.finish_with_error.call_args.args[0]
    assert "refused" in message and "403" in message and "Please set a user-agent" in message
    assert "Please set a user-agent" in logged(dataset)
    dataset.finish.assert_not_called()


def test_wikipedia_refuses_after_some_pages(monkeypatch, tmp_path):
    dataset, asked = run([f"{AMSTERDAM} {UTRECHT} {ROTTERDAM}"], {
        "Amsterdam": page_with_categories("Capitals in Europe"),
        "Rotterdam": FakeResponse(429, "<html><body>Too many requests</body></html>"),
        "Utrecht": page_with_categories("Cities in the Netherlands"),
    }, monkeypatch, tmp_path)

    # the titles in one post are fetched in alphabetical order; the network has what came before the refusal
    assert asked == ["Amsterdam", "Rotterdam"]
    num_rows, warning = dataset.finish_with_warning.call_args.args
    assert num_rows == 2 and "Too many requests" in warning
    dataset.finish.assert_not_called()


def test_some_pages_fail(monkeypatch, tmp_path):
    dataset, asked = run([f"{AMSTERDAM} {UTRECHT} {ROTTERDAM}"], {
        "Amsterdam": page_with_categories("Capitals in Europe"),
        "Rotterdam": FakeResponse(200, "<html><title>Permission error</title></html>"),
        "Utrecht": requests.ConnectionError("connection reset"),
    }, monkeypatch, tmp_path)

    # all pages are tried, each failure is logged with its reason, and the run ends with a warning
    assert asked == ["Amsterdam", "Rotterdam", "Utrecht"]
    log = logged(dataset)
    assert "'Rotterdam'; the page may not exist" in log
    assert "Could not reach Wikipedia for 'Utrecht': connection reset" in log
    assert "Got the categories of 1 of 3 pages" in log
    num_rows, warning = dataset.finish_with_warning.call_args.args
    assert num_rows == 4 and "2 of 3 pages could not be fetched" in warning
    dataset.finish.assert_not_called()


def test_no_page_could_be_fetched(monkeypatch, tmp_path):
    dataset, asked = run([f"{AMSTERDAM} {UTRECHT}"], {
        "Amsterdam": FakeResponse(500, "Server error"),
        "Utrecht": FakeResponse(503, "Unavailable"),
    }, monkeypatch, tmp_path)

    assert "any of the 2 Wikipedia pages" in dataset.finish_with_error.call_args.args[0]
    assert "status 500 for 'Amsterdam'" in logged(dataset)
    dataset.finish.assert_not_called()


def test_no_wikipedia_links(monkeypatch, tmp_path):
    dataset, asked = run(["https://nl.wikipedia.org/wiki/Amsterdam and https://example.com/wiki/Utrecht"], {},
                         monkeypatch, tmp_path)

    assert asked == []
    dataset.finish_as_empty.assert_called_once_with("No links to English Wikipedia pages found")
    dataset.finish.assert_not_called()
