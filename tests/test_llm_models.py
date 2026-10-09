"""
Tests for LLM model task capabilities:

- `common/lib/llm/llm_client.py` — the task filter that keeps generative and
  embedding models out of each other's processors.
- `common/lib/llm/clients/ollama_client.py` — deriving tasks and media types
  from Ollama's reported capabilities.

These import neither `LLMAdapter` nor any server, so they run on host Python
without the LangChain stack installed.
"""
import pytest

from common.lib.exceptions import LLMServerException
from common.lib.llm.clients.ollama_client import OllamaClient
from common.lib.llm.llm_client import get_model_library, supports_task


class DummyConfig:
    """Minimal stand-in for the 4CAT config reader."""

    def __init__(self, settings=None):
        self.settings = settings or {}

    def get(self, key, default=None):
        return self.settings.get(key, default)


def make_meta(capabilities):
    """Build an Ollama entry shaped like the one `list_models()` produces."""
    return {"model": "test-model", "metadata": {"capabilities": capabilities}}


@pytest.fixture
def client():
    server = {"name": "Test Ollama", "type": "ollama", "url": "http://localhost:11434",
              "auth_header": "", "auth_key": "", "_id": "ollama-test"}
    return OllamaClient(DummyConfig(), server, log=None)


# --------------------------------------------------------------------------- #
# supports_task

def test_supports_task_reads_declared_tasks():
    assert supports_task({"supported_tasks": ["embed"]}, "embed")
    assert not supports_task({"supported_tasks": ["embed"]}, "generate")
    assert supports_task({"supported_tasks": ["generate", "embed"]}, "generate")


def test_supports_task_defaults_legacy_entries_to_generative():
    """Entries built before `supported_tasks` existed all predate embedding."""
    assert supports_task({}, "generate")
    assert not supports_task({}, "embed")


# --------------------------------------------------------------------------- #
# OllamaClient.parse_supported_tasks

def test_parse_tasks_maps_completion_and_embedding(client):
    assert client.parse_supported_tasks(make_meta(["completion"])) == ["generate"]
    assert client.parse_supported_tasks(make_meta(["embedding"])) == ["embed"]
    assert client.parse_supported_tasks(make_meta(["completion", "embedding"])) == ["generate", "embed"]


def test_parse_tasks_ignores_orthogonal_capabilities(client):
    """
    `qwen3-embedding:latest` reports ["tools", "embedding"] and no "completion".
    Treating any non-embedding capability as evidence of generation would offer
    it in the prompter, where it can only fail.
    """
    assert client.parse_supported_tasks(make_meta(["tools", "embedding"])) == ["embed"]
    assert client.parse_supported_tasks(make_meta(["vision", "completion"])) == ["generate"]


def test_parse_tasks_falls_back_to_generative_when_unknown(client):
    """An unreachable /api/show must not hide a model from every processor."""
    assert client.parse_supported_tasks(None) == ["generate"]
    assert client.parse_supported_tasks({"model": "x"}) == ["generate"]
    assert client.parse_supported_tasks(make_meta([])) == ["generate"]


def test_parse_tasks_reads_inline_capabilities(client):
    """/api/tags reports capabilities inline, without a `metadata` key."""
    assert client.parse_supported_tasks({"model": "x", "capabilities": ["embedding"]}) == ["embed"]


# --------------------------------------------------------------------------- #
# OllamaClient.parse_supported_media_types

def test_embedding_model_still_consumes_text(client):
    """Embedding is a task, not a media type - an embedder still takes text in."""
    assert client.parse_supported_media_types(make_meta(["embedding"])) == ["text"]
    assert "embedding" not in client.parse_supported_media_types(make_meta(["embedding"]))


def test_media_types_still_detect_vision(client):
    assert client.parse_supported_media_types(make_meta(["completion", "vision"])) == ["text", "image"]


def test_media_types_unknown_stays_empty(client):
    assert client.parse_supported_media_types(None) == []


# --------------------------------------------------------------------------- #
# OllamaClient.embed

def test_embed_refuses_media(client):
    """
    Ollama's /api/embed has no image parameter and discards one silently, so a
    media request must fail loudly here rather than come back as a text-only
    vector that looks valid.
    """
    with pytest.raises(LLMServerException, match="multimodal"):
        client.embed("mxbai-embed-large:latest", ["some text"], media=["<base64>"])


def test_embed_refuses_media_before_reaching_the_server(client):
    """The guard must not depend on the server being up, or on there being text."""
    with pytest.raises(LLMServerException):
        client.embed("mxbai-embed-large:latest", [], media=["<base64>"])


def test_embed_short_circuits_on_empty_input(client):
    """No inputs means no request; an empty list is not an error."""
    assert client.embed("mxbai-embed-large:latest", []) == []
    assert client.embed("mxbai-embed-large:latest", [], media=None) == []


# --------------------------------------------------------------------------- #
# get_model_library

@pytest.fixture
def config():
    servers = {"ollama-test": {"name": "Test Ollama", "type": "ollama", "url": "http://localhost:11434",
                               "_id": "ollama-test"}}
    models = {
        "gen": {"name": "Generative", "server": "ollama-test", "supported_tasks": ["generate"]},
        "emb": {"name": "Embedder", "server": "ollama-test", "supported_tasks": ["embed"]},
        "both": {"name": "Both", "server": "ollama-test", "supported_tasks": ["generate", "embed"]},
        "legacy": {"name": "Legacy", "server": "ollama-test"},
        "disabled": {"name": "Disabled", "server": "ollama-test", "supported_tasks": ["embed"]},
    }
    return DummyConfig({
        "llm.available_models": models,
        "llm.enabled_models": ["gen", "emb", "both", "legacy"],
        "llm.servers": servers,
        "llm.access": True,
    })


def test_library_separates_tasks(config):
    assert set(get_model_library(config, task="generate")["Test Ollama"]) == {"gen", "both", "legacy"}
    assert set(get_model_library(config, task="embed")["Test Ollama"]) == {"emb", "both"}


def test_library_defaults_to_generative(config):
    assert get_model_library(config) == get_model_library(config, task="generate")


def test_library_respects_enabled_models(config):
    for task in ("generate", "embed"):
        assert "disabled" not in get_model_library(config, task=task).get("Test Ollama", {})


def test_library_without_local_access_drops_local_models(config):
    """Without `llm.access` only third-party models may be offered."""
    config.settings["llm.access"] = False
    assert get_model_library(config, task="generate") == {}
    assert get_model_library(config, task="embed") == {}


def test_library_empty_when_no_model_supports_task():
    config = DummyConfig({
        "llm.available_models": {"gen": {"name": "Generative", "server": "s", "supported_tasks": ["generate"]}},
        "llm.enabled_models": ["gen"],
        "llm.servers": {"s": {"name": "Server", "_id": "s"}},
        "llm.access": True,
    })
    assert get_model_library(config, task="embed") == {}


# --------------------------------------------------------------------------- #
# name-based task fallback (servers that report no capabilities)

@pytest.fixture
def openai_client():
    from common.lib.llm.clients.openai_client import OpenAICompatibleClient
    server = {"name": "vLLM", "type": "openai-like", "url": "http://gpu:8000/v1",
              "auth_header": "", "auth_key": "", "_id": "vllm-test"}
    return OpenAICompatibleClient(DummyConfig(), server, log=None)


def test_base_url_drops_the_slash_left_by_stripping_v1(openai_client):
    """
    "http://gpu:8000/v1" must not become "http://gpu:8000/", or every request
    goes to a doubled slash - which a real vLLM answers with a 404.
    """
    assert openai_client.base_url == "http://gpu:8000"


def test_name_fallback_reads_embed_from_the_model_id(openai_client):
    assert openai_client.parse_supported_tasks({"key": "Qwen/Qwen3-VL-Embedding-8B"}) == ["embed"]
    assert openai_client.parse_supported_tasks({"key": "mxbai-embed-large"}) == ["embed"]
    assert openai_client.parse_supported_tasks({"key": "meta-llama/Llama-3.1-8B"}) == ["generate"]


def test_name_fallback_is_case_insensitive(openai_client):
    """The vendor spelling is "Embedding", the substring searched for is lowercase."""
    assert openai_client.parse_supported_tasks({"key": "SOME-EMBEDDING-MODEL"}) == ["embed"]


def test_name_fallback_survives_missing_metadata(openai_client):
    assert openai_client.parse_supported_tasks({}) == ["generate"]
    assert openai_client.parse_supported_tasks(None) == ["generate"]


def test_ollama_prefers_real_capabilities_over_the_name(client):
    """
    The heuristic cannot see that bge-m3 and all-minilm are embedders. Ollama
    reports it, so Ollama must not fall back to the name.
    """
    for name in ("bge-m3:latest", "all-minilm:latest"):
        meta = {"model": name, "metadata": {"capabilities": ["embedding"]}}
        assert client.parse_supported_tasks(meta) == ["embed"], name


# --------------------------------------------------------------------------- #
# OpenAI-compatible embed payloads

class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


def test_text_embed_uses_the_standard_input_field(openai_client, monkeypatch):
    sent = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        sent["url"], sent["body"] = url, json
        return FakeResponse(payload={"data": [{"index": 0, "embedding": [0.1, 0.2]},
                                              {"index": 1, "embedding": [0.3, 0.4]}]})

    monkeypatch.setattr(openai_client._session, "post", fake_post)
    vectors = openai_client.embed("m", ["one", "two"])

    assert sent["url"] == "http://gpu:8000/v1/embeddings"
    assert sent["body"] == {"model": "m", "input": ["one", "two"]}
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]


def test_media_embed_uses_messages_with_a_video_part(openai_client, monkeypatch):
    sent = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        sent["body"] = json
        return FakeResponse(payload={"data": [{"index": 0, "embedding": [1.0]}]})

    monkeypatch.setattr(openai_client._session, "post", fake_post)
    media = [{"type": "video", "mime": "video/mp4", "data": "QUJD"}]
    assert openai_client.embed("m", ["describe"], media=media) == [[1.0]]

    content = sent["body"]["messages"][0]["content"]
    assert "input" not in sent["body"]
    assert content[0] == {"type": "video_url", "video_url": {"url": "data:video/mp4;base64,QUJD"}}
    assert {"type": "text", "text": "describe"} in content


def test_media_embed_can_send_the_text_as_an_instruction(openai_client, monkeypatch):
    """
    An instruction steers the embedding from the system turn; left in the user
    turn it would be embedded along with the video.
    """
    sent = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        sent["body"] = json
        return FakeResponse(payload={"data": [{"index": 0, "embedding": [1.0]}]})

    monkeypatch.setattr(openai_client._session, "post", fake_post)
    media = [{"type": "video", "mime": "video/mp4", "data": "QUJD"}]
    openai_client.embed("m", ["Represent the video."], media=media, text_as_instruction=True)

    system, user, assistant = sent["body"]["messages"]
    assert system == {"role": "system", "content": [{"type": "text", "text": "Represent the video."}]}
    assert user == {"role": "user",
                    "content": [{"type": "video_url", "video_url": {"url": "data:video/mp4;base64,QUJD"}}]}
    # left open, so the prompt ends where the model takes its vector
    assert assistant == {"role": "assistant", "content": [{"type": "text", "text": ""}]}
    assert sent["body"]["continue_final_message"] is True
    assert sent["body"]["add_special_tokens"] is True


def test_media_embed_without_text_sends_no_system_turn(openai_client, monkeypatch):
    """No instruction means the model's chat template supplies its default."""
    sent = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        sent["body"] = json
        return FakeResponse(payload={"data": [{"index": 0, "embedding": [1.0]}]})

    monkeypatch.setattr(openai_client._session, "post", fake_post)
    openai_client.embed("m", [""], media=[{"type": "image", "mime": "image/jpeg", "data": "QUJD"}],
                        text_as_instruction=True)

    assert [message["role"] for message in sent["body"]["messages"]] == ["user", "assistant"]


def test_ollama_accepts_the_instruction_flag_and_still_refuses_media(client):
    """The media processor passes the flag to whichever client it has."""
    with pytest.raises(LLMServerException, match="multimodal"):
        client.embed("mxbai-embed-large:latest", ["x"], media=["<base64>"], text_as_instruction=True)


def test_media_embed_rejects_a_length_mismatch(openai_client):
    with pytest.raises(LLMServerException, match="each input needs exactly one media entry"):
        openai_client.embed("m", ["a", "b"], media=[{"type": "video", "data": "x"}])


def test_vectors_are_returned_in_input_order(openai_client, monkeypatch):
    """The API does not promise response order, so it is sorted by `index`."""
    def fake_post(url, headers=None, json=None, timeout=None):
        return FakeResponse(payload={"data": [{"index": 1, "embedding": [2.0]},
                                              {"index": 0, "embedding": [1.0]}]})

    monkeypatch.setattr(openai_client._session, "post", fake_post)
    assert openai_client.embed("m", ["first", "second"]) == [[1.0], [2.0]]


def test_missing_endpoint_is_reported_with_the_url(openai_client, monkeypatch):
    """
    A generatively-served model has no /v1/embeddings route at all, so a 404
    here means the wrong runner rather than a transient failure. The message
    names the URL that was missing.
    """
    def fake_post(url, headers=None, json=None, timeout=None):
        return FakeResponse(status_code=404, payload={"detail": "Not Found"})

    monkeypatch.setattr(openai_client._session, "post", fake_post)
    with pytest.raises(LLMServerException, match="does not exist on this server"):
        openai_client.embed("m", ["hello"])


def test_wrong_vector_count_is_refused(openai_client, monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        return FakeResponse(payload={"data": [{"index": 0, "embedding": [1.0]}]})

    monkeypatch.setattr(openai_client._session, "post", fake_post)
    with pytest.raises(LLMServerException, match="cannot map vectors back"):
        openai_client.embed("m", ["one", "two"])


# --------------------------------------------------------------------------- #
# auth header spellings

@pytest.mark.parametrize("header,key", [
    ("Authorization: Bearer", "SECRET"),
    ("Authorization", "Bearer SECRET"),
    ("Authorization: Bearer", "Bearer SECRET"),
])
def test_bearer_token_spellings_all_produce_one_valid_header(header, key):
    """
    "Authorization: Bearer" is a header *value* prefix, not a name, but it is
    what people paste from curl examples. As a name it makes requests raise
    InvalidHeader, which reaches the user as "server unavailable".
    """
    from common.lib.llm.clients.openai_client import OpenAICompatibleClient
    server = {"name": "v", "type": "openai-like", "url": "http://h/v1",
              "auth_header": header, "auth_key": key, "_id": "v"}
    client = OpenAICompatibleClient(DummyConfig(), server, log=None)

    assert client._headers["Authorization"] == "Bearer SECRET"
    assert not any(":" in name for name in client._headers)


def test_plain_header_name_is_left_alone():
    from common.lib.llm.clients.openai_client import OpenAICompatibleClient
    server = {"name": "v", "type": "openai-like", "url": "http://h/v1",
              "auth_header": "X-API-KEY", "auth_key": "SECRET", "_id": "v"}
    client = OpenAICompatibleClient(DummyConfig(), server, log=None)
    assert client._headers["X-API-KEY"] == "SECRET"


def test_no_auth_header_configured_sends_none():
    from common.lib.llm.clients.openai_client import OpenAICompatibleClient
    server = {"name": "v", "type": "openai-like", "url": "http://h/v1",
              "auth_header": "", "auth_key": "SECRET", "_id": "v"}
    client = OpenAICompatibleClient(DummyConfig(), server, log=None)
    assert list(client._headers) == ["Content-Type"]


# --------------------------------------------------------------------------- #
# clients that cannot embed must fail the way processors expect

def test_client_without_embedding_support_raises_a_catchable_error():
    """
    Processors catch LLMServerException and report it on the dataset. A bare
    NotImplementedError escapes that and crashes the run with a stack trace,
    which is what a third-party embedding model used to do.
    """
    from pathlib import Path
    from common.lib.llm.clients.thirdparty_client import ThirdPartyClient

    class RootConfig(DummyConfig):
        def get(self, key, default=None):
            return Path(__file__).resolve().parent.parent if key == "PATH_ROOT" else default

    server = {"name": "Third-party APIs", "type": "thirdparty", "url": "",
              "auth_header": "", "auth_key": "", "_id": "thirdparty-models"}
    client = ThirdPartyClient(RootConfig(), server, log=None)

    with pytest.raises(LLMServerException, match="not supported"):
        client.embed("text-embedding-3-small", ["hello"])


def test_the_error_names_the_model_and_connection_type():
    """The message has to be enough to act on, since it reaches the user as-is."""
    from pathlib import Path
    from common.lib.llm.clients.thirdparty_client import ThirdPartyClient

    class RootConfig(DummyConfig):
        def get(self, key, default=None):
            return Path(__file__).resolve().parent.parent if key == "PATH_ROOT" else default

    client = ThirdPartyClient(RootConfig(), {"name": "x", "type": "thirdparty", "url": "",
                                             "auth_header": "", "auth_key": "", "_id": "x"}, log=None)
    try:
        client.embed("text-embedding-3-small", ["hello"])
    except LLMServerException as e:
        assert "text-embedding-3-small" in str(e) and "thirdparty" in str(e)
