"""
Tests for how the LLM clients build embedding requests:

- `common/lib/llm/clients/openai_client.py` — plain `input` for OpenAI's own
  API and text-only models, split to stay under OpenAI's limits; the chat
  format vLLM's Qwen3-VL-Embedding example uses for media and for models that
  expect it; refusals that should not be retried.
- `common/lib/llm/clients/ollama_client.py` — refuses media up front.

No server is contacted: the clients' HTTP session is replaced with a fake that
records requests.
"""
import pytest

from common.lib.exceptions import LLMRequestRejectedException, LLMServerException
from common.lib.llm.clients.ollama_client import OllamaClient
from common.lib.llm.clients.openai_client import OpenAICompatibleClient

VIDEO = {"type": "video", "mime": "video/mp4", "data": "AAAA"}


class Response:
    def __init__(self, status_code=200, data=None, text=""):
        self.status_code, self._data, self.text = status_code, data, text

    def json(self):
        return self._data


class Session:
    """Records POSTs and answers each with one vector per input."""

    def __init__(self, models=(), status=200):
        self.models, self.status = list(models), status
        self.posts, self.gets = [], []

    def get(self, url, **kwargs):
        self.gets.append(url)
        return Response(data={"object": "list", "data": self.models})

    def post(self, url, json=None, **kwargs):
        self.posts.append(json)
        if self.status != 200:
            return Response(self.status, text="refused")
        count = len(json["input"]) if "input" in json else 1
        return Response(data={"data": [{"index": i, "embedding": [float(i)]} for i in range(count)]})


def client(url="http://vllm.local:8000/v1", models=(), status=200):
    instance = OpenAICompatibleClient(None, {"url": url, "type": "openai-like", "_id": "test"})
    instance._session = Session(models, status)
    return instance


def vllm_model(model_id, root=None):
    return {"id": model_id, "object": "model", "owned_by": "vllm", "root": root or model_id}


# --------------------------------------------------------------------------- #
# telling servers apart

def test_openai_is_recognised_by_its_host_without_asking_it():
    openai = client("https://api.openai.com/v1")
    assert openai.server_kind() == "openai"
    assert openai._session.gets == []


def test_vllm_is_recognised_by_its_model_listing():
    assert client(models=[vllm_model("Qwen/Qwen3-Embedding-0.6B")]).server_kind() == "vllm"
    assert client(models=[{"id": "some-model", "owned_by": "organization_owner"}]).server_kind() == "other"


def test_the_model_listing_is_fetched_once():
    vllm = client(models=[vllm_model("m")])
    vllm.server_kind()
    vllm.uses_chat_format("m")
    assert len(vllm._session.gets) == 1


# --------------------------------------------------------------------------- #
# plain `input`: OpenAI and text-only models

def test_openai_gets_the_standard_request_and_nothing_else():
    openai = client("https://api.openai.com/v1")
    assert openai.embed("text-embedding-3-small", ["a", "b"]) == [[0.0], [1.0]]
    assert openai._session.posts == [{"model": "text-embedding-3-small", "input": ["a", "b"]}]


def test_openai_requests_stay_under_the_input_limit():
    openai = client("https://api.openai.com/v1")
    vectors = openai.embed("text-embedding-3-small", ["x"] * 3000)
    assert [len(post["input"]) for post in openai._session.posts] == [2048, 952]
    assert len(vectors) == 3000


def test_openai_requests_stay_under_the_token_limit():
    # ~100k estimated tokens each, so no more than two fit in one request
    openai = client("https://api.openai.com/v1")
    openai.embed("text-embedding-3-small", ["x" * 200_000] * 5)
    assert [len(post["input"]) for post in openai._session.posts] == [2, 2, 1]


def test_vllm_truncates_over_long_texts_instead_of_failing():
    vllm = client(models=[vllm_model("Qwen/Qwen3-Embedding-0.6B")])
    vllm.embed("Qwen/Qwen3-Embedding-0.6B", ["a"])
    assert vllm._session.posts[0]["truncate_prompt_tokens"] == -1


def test_other_servers_get_no_vllm_parameters():
    other = client(models=[{"id": "m", "owned_by": "someone"}])
    other.embed("m", ["a"])
    assert other._session.posts == [{"model": "m", "input": ["a"]}]


# --------------------------------------------------------------------------- #
# the chat format: media, and models that expect it for text too

def test_media_goes_in_the_user_turn_and_the_instruction_in_the_system_turn():
    vllm = client(models=[vllm_model("Qwen/Qwen3-VL-Embedding-2B")])
    vllm.embed("Qwen/Qwen3-VL-Embedding-2B", [""], media=[VIDEO], instruction="Represent the video.")

    request = vllm._session.posts[0]
    system, user, assistant = request["messages"]
    assert system == {"role": "system", "content": [{"type": "text", "text": "Represent the video."}]}
    assert user["role"] == "user"
    assert user["content"][0] == {"type": "video_url", "video_url": {"url": "data:video/mp4;base64,AAAA"}}
    # the instruction is not part of what gets embedded
    assert "Represent the video." not in str(user)
    # left open, so the prompt ends where the model takes its vector
    assert assistant == {"role": "assistant", "content": [{"type": "text", "text": ""}]}
    assert request["continue_final_message"] is True and request["add_special_tokens"] is True


def test_media_without_an_instruction_gets_the_models_default():
    vllm = client(models=[vllm_model("Qwen/Qwen3-VL-Embedding-2B")])
    vllm.embed("Qwen/Qwen3-VL-Embedding-2B", [""], media=[VIDEO])
    assert vllm._session.posts[0]["messages"][0]["content"][0]["text"] == "Represent the user's input."


def test_qwen3_vl_embedding_text_uses_the_same_chat_format():
    """Otherwise text and video vectors from one model are built differently."""
    vllm = client(models=[vllm_model("Qwen/Qwen3-VL-Embedding-2B")])
    vectors = vllm.embed("Qwen/Qwen3-VL-Embedding-2B", ["first", "second"])

    assert len(vectors) == 2 and len(vllm._session.posts) == 2
    assert all("input" not in post for post in vllm._session.posts)
    assert vllm._session.posts[1]["messages"][1]["content"] == [{"type": "text", "text": "second"}]


def test_a_model_served_under_another_name_is_still_recognised():
    vllm = client(models=[vllm_model("my-embedder", root="Qwen/Qwen3-VL-Embedding-8B")])
    assert vllm.uses_chat_format("my-embedder")
    assert not vllm.uses_chat_format("something-else")


def test_chat_format_needs_vllm():
    other = client(models=[{"id": "Qwen3-VL-Embedding-2B", "owned_by": "someone"}])
    assert not other.uses_chat_format("Qwen3-VL-Embedding-2B")


# --------------------------------------------------------------------------- #
# refusals

def test_openai_refuses_media_before_sending_anything():
    openai = client("https://api.openai.com/v1")
    assert "only embeds text" in openai.media_embedding_error("text-embedding-3-small")

    with pytest.raises(LLMRequestRejectedException):
        openai.embed("text-embedding-3-small", [""], media=[VIDEO])
    assert openai._session.posts == []


@pytest.mark.parametrize("status,rejected", [(400, True), (404, True), (422, True),
                                             (408, False), (429, False), (500, False), (503, False)])
def test_only_refusals_are_marked_as_not_worth_retrying(status, rejected):
    vllm = client(models=[vllm_model("m")], status=status)
    with pytest.raises(LLMServerException) as error:
        vllm.embed("m", ["a"])
    assert isinstance(error.value, LLMRequestRejectedException) is rejected


def test_ollama_refuses_media_up_front():
    ollama = OllamaClient(None, {"url": "http://localhost:11434", "type": "ollama", "_id": "o"})
    assert ollama.media_embedding_error("any") is not None
    with pytest.raises(LLMRequestRejectedException):
        ollama.embed("any", [""], media=[VIDEO])
