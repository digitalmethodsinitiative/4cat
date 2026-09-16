"""
Tests for LLM model task capabilities:

- `common/lib/llm/models.py` — the task filter that keeps generative and
  embedding models out of each other's processors.
- `common/lib/llm/clients/ollama_client.py` — deriving tasks and media types
  from Ollama's reported capabilities.

These import neither `LLMAdapter` nor any server, so they run on host Python
without the LangChain stack installed.
"""
import pytest

from common.lib.exceptions import LLMServerException
from common.lib.llm.clients.ollama_client import OllamaClient
from common.lib.llm.models import get_model_library, supports_task


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
