import importlib.util
import json
import re
import unicodedata
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from kiwipiepy import Kiwi
from kiwipiepy.utils import Stopwords

from common.lib.exceptions import QueryNeedsExplicitConfirmationException, QueryParametersException
from common.lib.helpers import compile_term_regex
from processors.filtering.accent_fold import AccentFoldingFilter
from processors.metrics.rank_attribute import AttributeRanker


"""
How 4CAT handles Korean text.

Korean writes particles and endings as part of the word: 학교 (school), 학교에서 (at school) and 학교가 (school, as
the subject) are three forms of one word. These tests hold how the tokeniser splits such words with Kiwi, how
searches can find them, and that other processors do not damage Hangul. They also hold how the tokeniser handles
Chinese, the other language that it recommends its own tokeniser for.
"""


# the tokeniser's folder has a dash in its name, so it cannot be imported by name
_spec = importlib.util.spec_from_file_location(
    "tokenise", Path(__file__).parent.parent / "processors" / "text-analysis" / "tokenise.py")
_tokenise = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tokenise)
Tokenise = _tokenise.Tokenise

SENTENCE = "학교에서 친구들이랑 떡볶이 먹었는데 진짜 맛있었음 ㅋㅋㅋ"


@pytest.fixture(scope="module")
def kiwi():
    return Kiwi()


def run_tokenise(tmp_path, texts, **parameters):
    """
    Run the tokeniser on some texts, as the backend would

    :return tuple:  The token lists, and the warning the dataset finished with
    """
    root = Path(__file__).parent.parent
    config = MagicMock()
    config.get.return_value = root
    defaults = {option: settings.get("default") for option, settings in Tokenise.get_options(config=config).items()}

    processor = Tokenise.__new__(Tokenise)
    processor.config = config
    processor.parameters = {**defaults, "columns": ["body"], **parameters}
    processor.dataset = MagicMock()
    processor.dataset.get_staging_area.return_value = tmp_path
    processor.source_dataset = MagicMock(annotation_fields=None, num_rows=len(texts))
    processor.source_dataset.iterate_items.return_value = [{"id": str(i), "body": text} for i, text in enumerate(texts)]
    processor.write_archive_and_finish = MagicMock()

    processor.process()

    assert not processor.dataset.finish_with_error.called
    # one file per interval, and the default interval is 'all'
    tokens = json.loads(tmp_path.joinpath("all.json").read_text(encoding="utf-8"))
    return tokens, processor.write_archive_and_finish.call_args.kwargs.get("warning")


# --- finding words in text ---------------------------------------------------

@pytest.mark.parametrize("match, expected", [
    ("word", [True, False, False]),
    ("start", [True, True, False]),
    ("anywhere", [True, True, True]),
])
def test_korean_word_with_particles(match, expected):
    regex = compile_term_regex([re.escape("학교")], match=match)
    texts = ["나는 학교 간다", "학교에서 공부했다", "고등학교 졸업"]
    assert [bool(regex.search(text)) for text in texts] == expected


def test_whole_words_is_unchanged():
    """'word' is the default, and must find what the processors found before"""
    regex = compile_term_regex([re.escape("cat"), re.escape("dog")], flags=re.IGNORECASE)
    assert regex.pattern == r"\b(cat|dog)\b"
    assert regex.search("A Cat sat")
    assert not regex.search("cats")


def test_chinese_needs_anywhere():
    assert not compile_term_regex(["北京"], match="start").search("我爱北京天安门")
    assert compile_term_regex(["北京"], match="anywhere").search("我爱北京天安门")


def test_start_of_word_works_for_hashtags():
    """with \\b, a term that starts with '#' is only found after a letter or digit"""
    assert compile_term_regex([re.escape("#서울")], match="start").search("오늘 #서울에서")


# --- tokenising with Kiwi ----------------------------------------------------

def test_kiwi_keeps_nouns(kiwi):
    assert Tokenise.get_kiwi_tokenizer(kiwi, ["nouns"])(SENTENCE) == ["학교", "친구", "떡볶이"]


def test_kiwi_gives_dictionary_forms(kiwi):
    assert Tokenise.get_kiwi_tokenizer(kiwi, ["verbs", "adjectives"])(SENTENCE) == ["먹다", "맛있다"]


def test_kiwi_irregular_adjectives_and_social_media(kiwi):
    """irregular forms have tags such as 'VA-I'"""
    tokens = Tokenise.get_kiwi_tokenizer(kiwi, ["adjectives", "social"])("새로운 정책을 발표했다 #주말 @jimin 😂")
    assert tokens == ["새롭다", "#주말", "@jimin", "😂"]


def test_kiwi_default_keeps_verbs_and_adjectives(kiwi):
    """the default leaves out adverbs such as '진짜' (really), and the grammar"""
    config = MagicMock()
    config.get.return_value = Path(__file__).parent.parent
    default = Tokenise.get_options(config=config)["kiwi_word_classes"]["default"]
    assert Tokenise.get_kiwi_tokenizer(kiwi, default)(SENTENCE) == ["학교", "친구", "떡볶이", "먹다", "맛있다"]


def test_kiwi_other_keeps_particles(kiwi):
    tokens = Tokenise.get_kiwi_tokenizer(kiwi, ["nouns", "other"])(SENTENCE)
    assert tokens[:2] == ["학교", "에서"]
    assert "ㅋㅋㅋ" in tokens


def test_kiwi_stopwords_can_be_allowed(kiwi):
    """'사람' (person) and '보다' (to see) are in Kiwi's stop word list"""
    text = "사람들이 떡볶이를 먹고 영화를 봤다"
    assert Tokenise.get_kiwi_tokenizer(kiwi, ["nouns", "verbs"], Stopwords())(text) == ["떡볶이", "먹다", "영화"]
    assert Tokenise.get_kiwi_tokenizer(kiwi, ["nouns", "verbs"], Stopwords(), {"사람", "보다"})(text) == [
        "사람", "떡볶이", "먹다", "영화", "보다"]


def test_korean_sentences(kiwi):
    split, error = Tokenise.get_sentence_method("korean", "sentence", kiwi=kiwi)
    assert not error
    assert split("정부는 새로운 정책을 발표했다. 시민들은 반대했다!", "korean") == [
        "정부는 새로운 정책을 발표했다.", "시민들은 반대했다!"]
    assert split(None, "korean") == []


def test_chinese_sentences():
    split, error = Tokenise.get_sentence_method("chinese", "sentence")
    assert not error
    assert split("我爱北京。你好吗？很好！", "chinese") == ["我爱北京。", "你好吗？", "很好！"]
    assert split(None, "chinese") == []


def test_russian_sentences():
    """razdel takes only the text, but the tokeniser passes the language too"""
    split, error = Tokenise.get_sentence_method("russian", "sentence")
    assert not error
    assert [Tokenise.normalise_segment(s) for s in split("Привет. Как дела?", "russian")] == [
        "Привет.", "Как дела?"]


@pytest.mark.parametrize("language, tokenizer, asks", [
    ("korean", "recommended", False),
    ("korean", "kiwi", False),
    ("korean", "twitter", True),
    ("chinese", "jieba-cut", False),
    ("chinese", "twitter", True),
    ("english", "kiwi", True),
    ("english", "jieba-search", True),
    ("other", "jieba-cut", False),
    ("english", "twitter", False),
])
def test_tokeniser_that_does_not_fit_the_language(language, tokenizer, asks):
    query = {"language": language, "tokenizer_type": tokenizer}
    if asks:
        with pytest.raises(QueryNeedsExplicitConfirmationException):
            Tokenise.validate_query(query, None, None)
        # after the user confirms in the browser, the same options pass
        assert Tokenise.validate_query({**query, "frontend-confirm": True}, None, None)
    else:
        assert Tokenise.validate_query(query, None, None) == query


@pytest.mark.parametrize("language, refused", [
    ("korean", True),
    ("chinese", True),
    ("arabic", True),
    ("english", False),
    ("danish", False),
    ("other", False),
])
def test_word_tokenize_needs_a_sentence_model(language, refused):
    """word_tokenize first splits the text into sentences, which NLTK cannot do for every language"""
    query = {"language": language, "tokenizer_type": "regular"}
    if refused:
        with pytest.raises(QueryParametersException):
            Tokenise.validate_query(query, None, None)
        # confirming a warning does not let it through
        with pytest.raises(QueryParametersException):
            Tokenise.validate_query({**query, "frontend-confirm": True}, None, None)
    else:
        assert Tokenise.validate_query(query, None, None) == query


def test_word_tokenize_without_sentence_model_warns(tmp_path):
    """presets do not pass through validate_query, so the tokeniser itself must cope"""
    tokens, warning = run_tokenise(tmp_path, ["학교에서 공부했다. 친구가 왔다."], language="korean",
                                   tokenizer_type="regular", kiwi_stopwords=False)
    assert tokens == [["학교에서", "공부했다", "친구가", "왔다"]]
    assert "English model" in warning


def test_stop_words_for_every_language():
    """'Stop words for language chosen above' finds a stopwords-iso list for each language"""
    root = Path(__file__).parent.parent
    config = MagicMock()
    config.get.return_value = root
    languages = Tokenise.get_options(config=config)["language"]["options"]
    with root.joinpath("common/assets/stopwords-iso.json").open(encoding="utf-8") as infile:
        stopwords_iso = json.load(infile)

    # Korean has its own stop word option, and 'other' has no list
    for language in set(languages) - {"korean", "other"}:
        assert _tokenise.STOPWORDS_ISO_CODES.get(language) in stopwords_iso, language


# --- other processors ----------------------------------------------------------

def test_accent_folding_keeps_hangul_composed():
    assert AccentFoldingFilter.case_fold("한국어 café") == "한국어 cafe"
    assert AccentFoldingFilter.case_fold(unicodedata.normalize("NFD", "한국어")) == "한국어"


@pytest.mark.parametrize("text, expected", [
    ("Crème brûlée à Noël", "Creme brulee a Noel"),
    ("Tiếng Việt", "Tieng Viet"),
    ("Αθήνα", "Αθηνα"),
    ("كَتَبَ", "كتب"),
    ("שָׁלוֹם", "שלום"),
    # in other scripts the marks are part of the letter
    ("がっこう パン", "がっこう パン"),
    ("हिन्दी किताब", "हिन्दी किताब"),
    ("ёлка йогурт", "ёлка йогурт"),
    ("✌️", "✌️"),
    ("café がっこう", "cafe がっこう"),
])
def test_accent_folding_only_changes_some_scripts(text, expected):
    assert AccentFoldingFilter.case_fold(text) == expected


def test_hashtags_in_any_script():
    assert AttributeRanker.extract(None, "#서울 #kpop스타 #café #BTS!", "hashtags") == [
        "서울", "kpop스타", "café", "BTS"]
