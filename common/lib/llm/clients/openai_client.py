"""
Centralized HTTP client for communicating with an OpenAI compatible server.

This includes vLLM and LM Studio. And LiteLLM, technically, but LiteLLM has
some useful API endpoints exclusive to it that we can benefit from, so use
the dedicated class for tht instead.
"""
import requests

from common.lib.exceptions import LLMServerException
from common.lib.llm.llm_client import LLMServerClient


class OpenAICompatibleClient(LLMServerClient):
    type = "openai-like"

    _models_info_path = "/api/v1/models"
    _models_info_key = "models"
    _model_id_key = "key"

    # vLLM and any strict OpenAI-compatible server expose the standard
    # /v1/models, returning {"object": "list", "data": [{"id": ...}]}. The
    # /api/v1/models shape below is kept as a fallback for servers that only
    # speak that dialect, so existing connections keep working.
    _openai_models_path = "/v1/models"

    def get_status(self) -> bool | int:
        """
        Check whether the server is reachable.

        Probes the same two model-listing dialects `list_models()` does. Without
        this a vLLM server reads as down: the base class only knows
        `_models_info_path`, which vLLM answers with a 404 even while healthy.

        :return:  `200` if either path answers, else the last status code seen,
          or `False` if the server could not be reached at all.
        """
        last_status = False
        for path in (self._openai_models_path, self._models_info_path):
            try:
                response = self._session.get(
                    f"{self.base_url}{path}", headers=self._headers, timeout=self.timeout)
                if response.status_code == 200:
                    return 200
                last_status = response.status_code
            except requests.RequestException as e:
                if self.log:
                    self.log.warning(f"{self.__class__.__name__}: server not available at {self.base_url}{path}: {e}")

        return last_status

    def list_models(self) -> list[dict]:
        """
        List available models, trying the standard OpenAI path first.

        Tries `/v1/models` and falls back to this class's `_models_info_path`.
        vLLM often does not prepend 'api/'...

        :return list[dict]:  List of models available, or `[]` on failure.
        """
        try:
            response = self._session.get(
                f"{self.base_url}{self._openai_models_path}",
                headers=self._headers,
                timeout=self.timeout,
            )
            if response.status_code == 200:
                models = response.json().get("data", [])
                if models:
                    return [{**model, self._model_id_key: model.get("id")} for model in models]
        except (requests.RequestException, ValueError) as e:
            if self.log:
                self.log.debug(
                    f"{self.__class__.__name__}: {self._openai_models_path} not usable at {self.base_url} ({e}), "
                    f"falling back to {self._models_info_path}")

        return super().list_models()

    def embed(self, model_id: str, inputs: list, media: list | None = None, timeout: int = 300) -> list[list[float]]:
        """
        Embed via the server's OpenAI-compatible `/v1/embeddings` endpoint.

        Two request shapes, because the OpenAI spec only covers the first:

        * text only -> `{"input": [...]}`, the standard batched form, one vector
          per input.
        * with media -> `{"messages": [...]}`, vLLM's format, where the
          content parts carry the media. A conversation is a single input, so
          this embeds exactly one item per request; `inputs` and `media` are
          paired by index and each pair becomes its own call.

        A server that is not running a pooling/embedding model has no
        `/v1/embeddings` route at all and answers 404.

        :param str model_id:  Model ID within this server's context.
        :param list inputs:  Texts to embed. With media, `inputs[i]` is the text
          accompanying `media[i]` and may be an empty string.
        :param list media:  Optional media descriptors, one per input - see
          `LLMServerClient.embed`.
        :param int timeout:  Request timeout in seconds.
        :returns list[list[float]]:  One vector per input, in input order.
        :raises LLMServerException:  On transport failure, an error response, or
          a vector count that does not match the input count.
        """
        if not inputs and not media:
            return []

        if media and len(media) != len(inputs):
            raise LLMServerException(
                f"Got {len(media)} media items for {len(inputs)} inputs; each input needs exactly one media entry "
                f"(use an empty string as the text if there is none)")

        if not media:
            return self._post_embeddings({"model": model_id, "input": list(inputs)}, timeout, len(inputs))

        vectors = []
        for text, item_media in zip(inputs, media):
            content = [self._media_content_part(item_media)]
            if text:
                content.append({"type": "text", "text": text})

            payload = {"model": model_id, "messages": [{"role": "user", "content": content}]}
            vectors += self._post_embeddings(payload, timeout, 1)

        return vectors

    @staticmethod
    def _media_content_part(item_media: dict) -> dict:
        """
        Build one OpenAI-style content part for a media descriptor.

        vLLM keys the part by modality - `video_url` for video, `image_url` for
        images - and accepts a `data:` URI in place of an http URL.

        :param dict item_media:  Media descriptor (`type`, `mime`, `data`).
        :return dict:  Content part for the `messages` payload.
        """
        media_type = item_media.get("type", "image")
        mime = item_media.get("mime") or f"{media_type}/*"
        url = item_media.get("url") or f"data:{mime};base64,{item_media.get('data', '')}"

        key = "video_url" if media_type == "video" else "image_url"
        return {"type": key, key: {"url": url}}

    def _post_embeddings(self, payload: dict, timeout: int, expected: int) -> list[list[float]]:
        """
        POST one embeddings request and pull the vectors out of the response.

        :param dict payload:  Request body.
        :param int timeout:  Request timeout in seconds.
        :param int expected:  How many vectors the response must contain.
        :return list[list[float]]:  Vectors, ordered by the response `index`
          field - the API does not promise to return them in input order.
        """
        url = f"{self.base_url}/v1/embeddings"
        try:
            response = self._session.post(url, headers=self._headers, json=payload, timeout=timeout)
        except requests.RequestException as e:
            raise LLMServerException(f"Could not reach {url}: {e}")

        if response.status_code == 404:
            raise LLMServerException(
                f"{url} does not exist on this server.")

        if response.status_code != 200:
            raise LLMServerException(
                f"Server returned status {response.status_code} while embedding with model "
                f"'{payload.get('model')}': {response.text[:500]}")

        try:
            data = response.json().get("data", [])
        except ValueError as e:
            raise LLMServerException(f"Server returned invalid JSON while embedding: {e}")

        if len(data) != expected:
            raise LLMServerException(
                f"Server returned {len(data)} embeddings for {expected} input(s); cannot map vectors back to items")

        ordered = sorted(data, key=lambda row: row.get("index", 0))
        return [row["embedding"] for row in ordered]

    def parse_supported_media_types(self, meta: dict) -> list[str]:
        """
        Derive the media types a model supports from its LiteLLM metadata.

        :param dict meta:  `model info` response dict, or `None`.
        :returns list[str]:  Ordered list of supported media type strings.
          Returns `[]` when `meta` is `None`
        """
        media_types = {"text"}  # far as I can tell, text is always supported

        if meta is None or not meta.get("capabilities"):
            return list(media_types)

        if meta["capabilities"].get("vision"):
            media_types.add("image")

        # no way to tell if model supports embeddings input as far as I can see...

        return list(media_types)

    def format_display_name(self, meta: dict) -> str:
        """
        Build a human-readable display name for a model.
=
        :param dict meta:  `/api/show` response dict, or `None`.
        :returns str:  Human-readable display name string.
        """
        model_name = self.get_model_id(meta)

        if meta.get("display_name"):
            model_name = meta["display_name"]

        extra_bits = []
        if meta.get("publisher"):
            extra_bits.append(meta["publisher"])

        if meta.get("params_string"):
            extra_bits.append(meta["params_string"])

        # only append the parenthetical when there is something to put in it -
        # a plain /v1/models entry has neither publisher nor size
        if extra_bits:
            model_name += f" ({', '.join(extra_bits)})"

        return model_name
